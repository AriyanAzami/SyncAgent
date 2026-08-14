"""Unit tests for the measured-usage engine - transcript parsing, weighting,
window arithmetic and liveness.

Writes a synthetic transcript tree under a temp dir and points the module at it,
so nothing here touches a real ~/.claude. Run from the repo root:

    python -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import syncagent as sa  # noqa: E402


def turn(minutes_ago, msg_id, session="S1", inp=100, out=200,
         cache_write=0, cache_read=0):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return json.dumps({
        "type": "assistant",
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "sessionId": session,
        "requestId": "req_" + msg_id,
        "message": {
            "id": msg_id,
            "model": "claude-opus-5",
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_creation_input_tokens": cache_write,
                "cache_read_input_tokens": cache_read,
            },
        },
    })


class TranscriptCase(unittest.TestCase):
    """A workspace whose transcripts we control line by line."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ws"
        (self.root / sa.ORCH).mkdir(parents=True)
        self.projects = Path(self.tmp.name) / "projects"
        self.transcripts = self.projects / sa.project_slug(self.root)
        self.transcripts.mkdir(parents=True)
        self._real_projects = sa.CLAUDE_PROJECTS
        sa.CLAUDE_PROJECTS = self.projects

    def tearDown(self):
        sa.CLAUDE_PROJECTS = self._real_projects
        self.tmp.cleanup()

    def write(self, name, lines):
        (self.transcripts / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def config(self, **limits):
        base = {"agents": {"claude": {"model": "opus", "budget_tokens_per_day": 1}},
                "limits": dict(sa.DEFAULT_LIMITS)}
        base["limits"].update(limits)
        return base


class TestParsing(TranscriptCase):
    def test_weighting_follows_the_configured_prices(self):
        self.write("a.jsonl", [turn(1, "m1", inp=1000, out=100,
                                    cache_write=400, cache_read=10000)])
        rec = sa.read_claude_usage(self.root)[0]
        # 1000*1 + 100*5 + 400*1.25 + 10000*0.1 = 3000
        self.assertEqual(rec["weighted"], 3000)
        self.assertEqual(rec["total"], 11500)

    def test_a_call_repeated_across_transcripts_is_counted_once(self):
        # Resuming a session copies earlier turns into the new file.
        self.write("a.jsonl", [turn(9, "m1"), turn(8, "m2")])
        self.write("b.jsonl", [turn(8, "m2"), turn(7, "m3")])
        self.assertEqual(len(sa.read_claude_usage(self.root)), 3)

    def test_non_assistant_and_malformed_lines_are_skipped(self):
        self.write("a.jsonl", [
            turn(1, "m1"),
            json.dumps({"type": "user", "message": {"usage": {"input_tokens": 9}}}),
            '{"type": "assistant", "message": {"usage": broken',
            json.dumps({"type": "assistant", "timestamp": "not-a-date",
                        "message": {"id": "m9", "usage": {"input_tokens": 5}}}),
        ])
        self.assertEqual(len(sa.read_claude_usage(self.root)), 1)

    def test_no_transcripts_reports_unavailable_rather_than_zero(self):
        report = sa.claude_usage_report(self.root, self.config())
        self.assertFalse(report["available"])
        self.assertIn("reason", report)


class TestWindows(TranscriptCase):
    def test_only_the_rolling_window_counts_against_the_window_limit(self):
        self.write("a.jsonl", [turn(60 * 9, "old", out=1000),   # 9h back, expired
                               turn(30, "new", out=1000)])
        r = sa.claude_usage_report(self.root, self.config(window_hours=5,
                                                          window_tokens=100000))
        self.assertEqual(r["window"]["calls"], 1)
        self.assertEqual(r["week"]["calls"], 2)

    def test_percent_and_remaining_track_the_ceiling(self):
        self.write("a.jsonl", [turn(10, "m1", inp=0, out=1000, cache_read=0)])
        r = sa.claude_usage_report(self.root, self.config(window_tokens=10000))
        self.assertEqual(r["window"]["weighted"], 5000)
        self.assertEqual(r["window"]["percent"], 50.0)
        self.assertEqual(r["window"]["remaining"], 5000)
        self.assertFalse(r["window"]["over"])

    def test_going_over_the_ceiling_clamps_the_meter_but_flags_it(self):
        self.write("a.jsonl", [turn(10, "m1", inp=0, out=1000)])
        r = sa.claude_usage_report(self.root, self.config(window_tokens=1000))
        self.assertEqual(r["window"]["percent"], 100.0)
        self.assertEqual(r["window"]["remaining"], 0)
        self.assertTrue(r["window"]["over"])
        self.assertEqual(r["hours_left"], 0.0)

    def test_the_window_resets_five_hours_after_its_first_call(self):
        self.write("a.jsonl", [turn(120, "m1")])
        r = sa.claude_usage_report(self.root, self.config(window_hours=5))
        self.assertAlmostEqual(r["window"]["resets_in_hours"], 3.0, places=1)

    def test_headroom_comes_from_the_binding_limit(self):
        self.write("a.jsonl", [turn(30, "m1", inp=0, out=1000),
                               turn(10, "m2", inp=0, out=1000)])
        r = sa.claude_usage_report(self.root, self.config(window_tokens=20000,
                                                          weekly_tokens=11000))
        self.assertEqual(r["binding"], "week")
        # 10000 weighted burned in the last hour, 1000 left on the week
        self.assertEqual(r["burn_per_hour"], 10000)
        self.assertAlmostEqual(r["hours_left"], 0.1, places=2)

    def test_the_live_session_is_the_one_that_spoke_last(self):
        self.write("a.jsonl", [turn(200, "m1", session="OLD"),
                               turn(5, "m2", session="NEW"),
                               turn(4, "m3", session="NEW")])
        r = sa.claude_usage_report(self.root, self.config())
        self.assertEqual(r["session"]["id"], "NEW")
        self.assertEqual(r["session"]["calls"], 2)


class TestLimits(unittest.TestCase):
    def test_a_plan_name_supplies_both_ceilings(self):
        limits = sa.resolve_limits({"limits": {"plan": "max-20x"}})
        self.assertEqual(limits["window_tokens"], sa.PLAN_LIMITS["max-20x"]["window"])
        self.assertEqual(limits["weekly_tokens"], sa.PLAN_LIMITS["max-20x"]["weekly"])

    def test_an_explicit_ceiling_overrides_the_plan(self):
        limits = sa.resolve_limits({"limits": {"plan": "pro", "window_tokens": 7}})
        self.assertEqual(limits["window_tokens"], 7)
        self.assertEqual(limits["weekly_tokens"], sa.PLAN_LIMITS["pro"]["weekly"])

    def test_an_empty_config_still_yields_usable_defaults(self):
        limits = sa.resolve_limits({})
        self.assertTrue(limits["window_tokens"] > 0)
        self.assertEqual(limits["weights"]["output"], 5.0)


class TestLiveness(unittest.TestCase):
    def test_a_missing_binary_outranks_any_recency(self):
        self.assertEqual(sa.agent_state(False, 1), "missing")

    def test_states_step_down_with_silence(self):
        self.assertEqual(sa.agent_state(True, 5), "live")
        self.assertEqual(sa.agent_state(True, sa.LIVE_SECONDS + 1), "idle")
        self.assertEqual(sa.agent_state(True, sa.IDLE_SECONDS + 1), "cold")

    def test_an_installed_agent_that_never_ran_is_not_live(self):
        self.assertEqual(sa.agent_state(True, None), "never")


if __name__ == "__main__":
    unittest.main()
