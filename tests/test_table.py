"""The table model: handoff parsing, depth slicing, topic numbering.

Pure functions and a temp folder. Nothing here launches a CLI.

    python -m unittest discover -s tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import syncagent.table as T  # noqa: E402
from syncagent.util import TABLE  # noqa: E402

SEATS = {"claude", "gemini", "codex"}


class TestHandoff(unittest.TestCase):
    def test_a_well_formed_block_is_dispatchable(self):
        h = T.parse_handoff(
            "## Findings\n\nstuff\n\n## Handoff\n\nto: claude\n"
            "job: check the numbers\nwhy: you have the spec\n", SEATS)
        self.assertEqual(h["to"], "claude")
        self.assertEqual(h["job"], "check the numbers")
        self.assertTrue(h["dispatchable"])

    def test_none_closes_the_topic_and_is_not_dispatchable(self):
        h = T.parse_handoff("## Handoff\nto: none\njob: -\nwhy: done", SEATS)
        self.assertEqual(h["to"], "none")
        self.assertFalse(h["dispatchable"])

    def test_user_is_normalised_from_the_words_models_actually_use(self):
        for word in ("user", "human", "me"):
            h = T.parse_handoff(f"## Handoff\nto: {word}\njob: decide\nwhy: x", SEATS)
            self.assertEqual(h["to"], "user", word)
            self.assertFalse(h["dispatchable"])

    def test_an_unknown_seat_is_shown_to_the_user_rather_than_dispatched(self):
        h = T.parse_handoff("## Handoff\nto: mistral\njob: x\nwhy: y", SEATS)
        self.assertEqual(h["to"], "user")
        self.assertEqual(h["unknown_seat"], "mistral")
        self.assertFalse(h["dispatchable"])

    def test_a_seat_named_by_its_binary_is_still_dispatched(self):
        # A seat that writes "agy" rather than "antigravity" is quibbling about
        # a name, not refusing - it should not cost a turn.
        h = T.parse_handoff("## Handoff\nto: agy\njob: research it\nwhy: web",
                            {"antigravity", "claude"})
        self.assertEqual(h["to"], "antigravity")
        self.assertTrue(h["dispatchable"])

    def test_an_alias_never_overrides_a_seat_that_really_exists(self):
        h = T.parse_handoff("## Handoff\nto: gpt\njob: x\nwhy: y",
                            {"gpt", "claude"})
        self.assertEqual(h["to"], "gpt")

    def test_no_handoff_section_yields_nothing_rather_than_a_guess(self):
        self.assertIsNone(T.parse_handoff("## Findings\n\njust findings", SEATS))

    def test_a_block_with_no_to_line_is_not_a_handoff(self):
        self.assertIsNone(T.parse_handoff("## Handoff\n\njob: x\nwhy: y", SEATS))

    def test_the_decorations_models_add_are_tolerated(self):
        # bullets, bold, a code fence, a trailing period on the seat name
        h = T.parse_handoff(
            "### Handoff:\n\n```\n- to: Gemini.\n- job: **dig into pricing**\n"
            "- why: you have web access\n```\n", SEATS)
        self.assertEqual(h["to"], "gemini")
        self.assertTrue(h["dispatchable"])


class TestSection(unittest.TestCase):
    def test_it_stops_at_the_next_heading_of_any_level(self):
        md = "## Findings\n\nkeep me\n\n### Confidence\n\ndrop me\n"
        self.assertEqual(T.section(md, "Findings"), "keep me")

    def test_a_missing_section_is_empty_not_the_whole_document(self):
        self.assertEqual(T.section("# Title\n\nbody", "Findings"), "")


class TableCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / TABLE).mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def topic_with_turns(self, bodies, depth="deep"):
        topic = T.create_topic(self.root, "a need", steps=[
            {"seat": "gemini", "job": "research", "depth": "deep"},
            {"seat": "claude", "job": "critique", "depth": depth},
            {"seat": "codex", "job": "tiebreak", "depth": depth},
        ])
        d = T.topic_dir(self.root, topic["id"])
        for i, body in enumerate(bodies, start=1):
            step = topic["steps"][i - 1]
            name = T.turn_filename(step)
            (d / name).write_text(body, encoding="utf-8")
            step["status"] = "done"
            step["file"] = name
        T.save_topic(self.root, topic)
        return topic


class TestDepthSlicing(TableCase):
    BODIES = [
        "## Findings\n\nA-findings\n\n## Confidence\n\nA-confidence\n"
        "\n## Handoff\n\nto: claude\n",
        "## Findings\n\nB-findings\n\n## Confidence\n\nB-confidence\n",
    ]

    def test_deep_sees_every_earlier_turn_in_full(self):
        topic = self.topic_with_turns(self.BODIES)
        text = T.prior_turns(self.root, topic, upto_n=3, depth="deep")
        self.assertIn("A-findings", text)
        self.assertIn("A-confidence", text)
        self.assertIn("B-findings", text)

    def test_light_drops_everything_that_is_not_findings(self):
        topic = self.topic_with_turns(self.BODIES)
        text = T.prior_turns(self.root, topic, upto_n=3, depth="light")
        self.assertIn("A-findings", text)
        self.assertIn("B-findings", text)
        self.assertNotIn("A-confidence", text)
        self.assertNotIn("B-confidence", text)

    def test_glance_sees_only_the_turn_immediately_before_it(self):
        topic = self.topic_with_turns(self.BODIES)
        text = T.prior_turns(self.root, topic, upto_n=3, depth="glance")
        self.assertIn("B-findings", text)
        self.assertNotIn("A-findings", text)

    def test_the_first_turn_has_no_prior_context_at_all(self):
        topic = self.topic_with_turns([])
        self.assertEqual(T.prior_turns(self.root, topic, upto_n=1, depth="deep"), "")

    def test_a_turn_that_ignored_the_headings_still_contributes_something(self):
        # A seat that wrote no `## Findings` must not silently vanish from the
        # context of every later seat.
        topic = self.topic_with_turns(["just a wall of prose, no headings at all\n"])
        text = T.prior_turns(self.root, topic, upto_n=2, depth="light")
        self.assertIn("wall of prose", text)


class TestTopics(TableCase):
    def test_numbering_continues_past_the_highest_rather_than_counting(self):
        # Deleting 002 must not make the next topic reuse the number - the id
        # ends up in filenames and telemetry.
        T.create_topic(self.root, "first")
        second = T.create_topic(self.root, "second")
        import shutil
        shutil.rmtree(T.topic_dir(self.root, second["id"]))
        third = T.create_topic(self.root, "third")
        self.assertTrue(third["id"].startswith("003-"))

    def test_the_slug_is_bounded_however_long_the_need_is(self):
        topic = T.create_topic(self.root, "how is my resume " * 30)
        self.assertLessEqual(len(topic["id"]), 48)

    def test_the_default_plan_is_the_configured_relay_order(self):
        topic = T.create_topic(self.root, "x")
        cfg = T.load_config(self.root)
        self.assertEqual([s["seat"] for s in topic["steps"]], T.seat_order(cfg))

    def test_the_brief_names_the_input_files_so_nobody_pastes_them(self):
        (self.root / TABLE / "inputs").mkdir(parents=True)
        (self.root / TABLE / "inputs" / "resume.pdf").write_text("x", encoding="utf-8")
        topic = T.create_topic(self.root, "check it", lens="resume")
        brief = (T.topic_dir(self.root, topic["id"]) / "BRIEF.md").read_text(encoding="utf-8")
        self.assertIn("resume.pdf", brief)
        self.assertIn("TRUTH CONSTRAINT", brief)

    def test_the_research_chair_is_antigravity_and_gemini_ships_disabled(self):
        # Google withdrew the Gemini CLI's individual free tier, so a seat that
        # merely has the binary must not be put in the relay by default.
        cfg = T.default_config()
        self.assertIn("antigravity", T.seat_order(cfg))
        self.assertNotIn("gemini", T.seat_order(cfg))
        self.assertEqual(cfg["seats"]["antigravity"]["cmd"], "agy")
        self.assertEqual(cfg["seats"]["antigravity"]["depth"], "deep")

    def test_an_unknown_lens_falls_back_rather_than_crashing(self):
        topic = T.create_topic(self.root, "x", lens="nonsense")
        self.assertEqual(topic["lens"], T.DEFAULT_LENS)


if __name__ == "__main__":
    unittest.main()
