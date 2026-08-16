"""The relay: sequencing, handoffs, hop limits, and the no-parallelism guarantee.

Every seat here is a fake. Nothing launches a CLI, so the suite is fast and
runs on a machine with none of the three installed.

    python -m unittest discover -s tests
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import syncagent.runner as R  # noqa: E402
import syncagent.seats as S  # noqa: E402
import syncagent.table as T  # noqa: E402
from syncagent.util import TABLE  # noqa: E402


def turn_text(findings="findings", to="none", job="-", why="-"):
    return (f"## Findings\n\n{findings}\n\n## Confidence\n\nhigh\n\n"
            f"## Handoff\n\nto: {to}\njob: {job}\nwhy: {why}\n")


class FakeSeats:
    """Records every call, and screams if two ever overlap."""

    def __init__(self, script=None, delay=0.0):
        self.script = script or {}
        self.delay = delay
        self.calls = []
        self.live = 0
        self.max_live = 0
        self._lock = threading.Lock()

    def __call__(self, name, seat, prompt, cwd, session=None, writable=False,
                 timeout=None):
        with self._lock:
            self.live += 1
            self.max_live = max(self.max_live, self.live)
        try:
            time.sleep(self.delay)
            self.calls.append({"seat": name, "prompt": prompt, "session": session,
                               "writable": writable})
            reply = self.script.get(name, turn_text())
            if callable(reply):
                reply = reply(len([c for c in self.calls if c["seat"] == name]))
            if isinstance(reply, Exception):
                return S._turn(False, error=str(reply))
            return S._turn(True, text=reply, tokens={"in": 10, "out": 20},
                           session=f"{name}-session")
        finally:
            with self._lock:
                self.live -= 1


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / TABLE).mkdir()
        cfg = T.default_config()
        cfg["auto_answer"] = False
        T.save_config(self.root, cfg)
        self._real = R.S.run_seat

    def tearDown(self):
        R.S.run_seat = self._real
        self.tmp.cleanup()

    def run_topic(self, fake, need="a need", steps=None, lens=None):
        R.S.run_seat = fake
        topic = T.create_topic(self.root, need, lens=lens or T.DEFAULT_LENS,
                               steps=steps)
        runner = R.Runner(self.root)
        runner.enqueue(topic["id"], topic["steps"][0]["n"])
        deadline = time.time() + 20
        while time.time() < deadline:
            runner.q.join()
            time.sleep(0.05)
            if runner.q.empty() and not runner.state()["running"]:
                break
        return T.load_topic(self.root, topic["id"])


class TestSequencing(RunnerCase):
    def test_the_plan_runs_in_order_and_each_turn_writes_a_file(self):
        fake = FakeSeats({"antigravity": turn_text("G", to="claude"),
                          "claude": turn_text("C", to="none")})
        topic = self.run_topic(fake)
        ran = [c["seat"] for c in fake.calls]
        self.assertEqual(ran[:2], ["antigravity", "claude"])
        for step in topic["steps"]:
            if step["status"] == "done":
                self.assertTrue(
                    (T.topic_dir(self.root, topic["id"]) / step["file"]).exists())

    def test_none_ends_the_topic_and_skips_the_rest_of_the_plan(self):
        fake = FakeSeats({"antigravity": turn_text("G", to="none")})
        topic = self.run_topic(fake)
        self.assertEqual(topic["status"], "answered")
        self.assertEqual([c["seat"] for c in fake.calls], ["antigravity"])
        self.assertTrue(any(s["status"] == "skipped" for s in topic["steps"]))

    def test_user_pauses_the_relay_without_skipping_anything(self):
        fake = FakeSeats({"antigravity": turn_text("G", to="user")})
        topic = self.run_topic(fake)
        self.assertEqual(topic["status"], "waiting")
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(any(s["status"] == "queued" for s in topic["steps"]))

    def test_a_failed_turn_stops_the_chain_and_keeps_the_reason(self):
        fake = FakeSeats({"antigravity": RuntimeError("not signed in")})
        topic = self.run_topic(fake)
        first = topic["steps"][0]
        self.assertEqual(first["status"], "failed")
        self.assertIn("not signed in", first["error"])
        self.assertEqual(len(fake.calls), 1)


class TestHandoffs(RunnerCase):
    def test_a_handoff_off_the_plan_inserts_a_detour_then_rejoins(self):
        fake = FakeSeats({
            "antigravity": turn_text("G", to="codex", job="settle the licence question"),
            "codex": turn_text("X", to="claude"),
            "claude": turn_text("C", to="none"),
        })
        topic = self.run_topic(fake, steps=[
            {"seat": "antigravity", "job": "research", "depth": "deep"},
            {"seat": "claude", "job": "critique", "depth": "light"},
        ])
        self.assertEqual([c["seat"] for c in fake.calls], ["antigravity", "codex", "claude"])
        inserted = [s for s in topic["steps"] if s.get("inserted_after")]
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0]["job"], "settle the licence question")

    def test_handing_to_the_next_planned_seat_is_not_counted_as_a_detour(self):
        fake = FakeSeats({"antigravity": turn_text("G", to="claude"),
                          "claude": turn_text("C", to="none")})
        topic = self.run_topic(fake)
        self.assertEqual(topic["hops"], 0)

    def test_two_seats_cannot_volley_past_the_hop_limit(self):
        cfg = T.load_config(self.root)
        cfg["max_hops"] = 2
        cfg["auto_answer"] = False
        T.save_config(self.root, cfg)
        fake = FakeSeats({"antigravity": turn_text("G", to="codex"),
                          "codex": turn_text("X", to="antigravity"),
                          "claude": turn_text("C", to="antigravity")})
        topic = self.run_topic(fake, steps=[
            {"seat": "antigravity", "job": "research", "depth": "deep"}])
        self.assertLessEqual(topic["hops"], 2)
        self.assertLessEqual(len(fake.calls), 4)

    def test_a_handoff_to_an_unknown_seat_stops_rather_than_guessing(self):
        fake = FakeSeats({"antigravity": turn_text("G", to="mistral")})
        topic = self.run_topic(fake, steps=[
            {"seat": "antigravity", "job": "research", "depth": "deep"}])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(topic["steps"][0]["handoff"]["unknown_seat"], "mistral")


class TestGuarantees(RunnerCase):
    def test_only_one_seat_is_ever_alive_at_a_time(self):
        # The whole token argument rests on this. A delay makes any overlap
        # detectable rather than theoretical.
        fake = FakeSeats({"antigravity": turn_text("G", to="claude"),
                          "claude": turn_text("C", to="codex"),
                          "codex": turn_text("X", to="none")}, delay=0.12)
        R.S.run_seat = fake
        topic = T.create_topic(self.root, "a need")
        runner = R.Runner(self.root)
        for step in topic["steps"]:
            runner.enqueue(topic["id"], step["n"])
        deadline = time.time() + 20
        while time.time() < deadline:
            runner.q.join()
            time.sleep(0.05)
            if runner.q.empty() and not runner.state()["running"]:
                break
        self.assertEqual(fake.max_live, 1)

    def test_only_the_scribe_is_given_write_access(self):
        fake = FakeSeats({"antigravity": turn_text("G", to="claude"),
                          "claude": turn_text("C", to="none")})
        self.run_topic(fake)
        writable = {c["seat"]: c["writable"] for c in fake.calls}
        self.assertTrue(writable["claude"])
        self.assertFalse(writable["antigravity"])

    def test_depth_controls_what_the_next_seat_is_actually_sent(self):
        fake = FakeSeats({
            "antigravity": turn_text("SECRET-DEEP-DETAIL", to="claude"),
            "claude": turn_text("C", to="none"),
        })
        self.run_topic(fake, steps=[
            {"seat": "antigravity", "job": "research", "depth": "deep"},
            {"seat": "claude", "job": "critique", "depth": "light"},
        ])
        claude_prompt = [c for c in fake.calls if c["seat"] == "claude"][0]["prompt"]
        # light still gets the findings...
        self.assertIn("SECRET-DEEP-DETAIL", claude_prompt)
        # ...but not the confidence section that sat beside them
        self.assertNotIn("## Confidence", claude_prompt.split("## What to return")[0])

    def test_a_shallow_seat_going_first_is_not_told_to_react_to_nothing(self):
        # "Someone has already done the deep pass" is a lie when the deep seat
        # is blocked, and a seat told to critique absent work either invents it
        # or argues with the prompt.
        fake = FakeSeats({"claude": turn_text("C", to="none")})
        self.run_topic(fake, steps=[
            {"seat": "claude", "job": "critique", "depth": "light"}])
        first = fake.calls[0]["prompt"]
        self.assertIn("You are first", first)
        self.assertNotIn("already done the deep pass", first)

    def test_a_shallow_seat_following_a_deep_one_is_told_not_to_repeat_it(self):
        fake = FakeSeats({"antigravity": turn_text("G", to="claude"),
                          "claude": turn_text("C", to="none")})
        self.run_topic(fake, steps=[
            {"seat": "antigravity", "job": "research", "depth": "deep"},
            {"seat": "claude", "job": "critique", "depth": "light"}])
        claude_prompt = [c for c in fake.calls if c["seat"] == "claude"][0]["prompt"]
        self.assertIn("already done the deep pass", claude_prompt)

    def test_a_resumed_seat_is_not_sent_the_brief_again(self):
        fake = FakeSeats({"antigravity": turn_text("G", to="antigravity"),
                          "claude": turn_text("C", to="none")})
        topic = self.run_topic(fake, steps=[
            {"seat": "antigravity", "job": "research", "depth": "deep"},
            {"seat": "antigravity", "job": "go deeper", "depth": "deep"},
        ])
        calls = [c for c in fake.calls if c["seat"] == "antigravity"]
        self.assertGreaterEqual(len(calls), 2)
        self.assertIn("## The need", calls[0]["prompt"])
        self.assertNotIn("## The need", calls[1]["prompt"])
        self.assertEqual(calls[1]["session"], "antigravity-session")


if __name__ == "__main__":
    unittest.main()


class TestAntigravityAdapter(unittest.TestCase):
    """The agy CLI's own quirks, without launching it."""

    def test_the_prompt_is_capped_because_it_rides_on_the_command_line(self):
        # agy -p takes the prompt as an argv value and Windows caps a command
        # line at 32,767 chars, so an uncapped deep turn would look like an
        # unrelated crash.
        self.assertLess(S.AGY_PROMPT_CAP, 32767)

    def test_the_json_reply_is_parsed_into_the_common_turn_shape(self):
        seen = {}

        def fake_run(cmd, prompt, cwd, timeout):
            seen["cmd"] = cmd
            out = ('{"conversation_id":"abc-123","status":"SUCCESS",'
                   '"response":"the answer","duration_seconds":3.0,"num_turns":1,'
                   '"usage":{"input_tokens":100,"output_tokens":20,'
                   '"thinking_tokens":5,"cache_read_tokens":7,"total_tokens":127}}')

            class P:
                returncode = 0
            return P(), out, ""

        real, S._run = S._run, fake_run
        try:
            turn = S.run_antigravity("hello", ".", {"cmd": "agy", "model": "m"})
        finally:
            S._run = real

        self.assertTrue(turn.ok)
        self.assertEqual(turn["text"], "the answer")
        self.assertEqual(turn["session"], "abc-123")
        self.assertEqual(turn["tokens"]["in"], 100)
        self.assertEqual(turn["tokens"]["cache_read"], 7)
        self.assertEqual(turn["tokens"]["total"], 127)
        # -p must stay last: it consumes whatever argument follows it.
        self.assertEqual(seen["cmd"][-2], "-p")

    def test_an_advisory_seat_gets_plan_mode_and_the_scribe_gets_edits(self):
        seen = []

        def fake_run(cmd, prompt, cwd, timeout):
            seen.append(cmd)

            class P:
                returncode = 0
            return P(), '{"conversation_id":"x","status":"SUCCESS","response":"ok"}', ""

        real, S._run = S._run, fake_run
        try:
            S.run_antigravity("hi", ".", {"cmd": "agy"}, writable=False)
            S.run_antigravity("hi", ".", {"cmd": "agy"}, writable=True)
        finally:
            S._run = real
        # read-only is the sandbox, not plan mode: plan refuses every tool,
        # so a research seat could not open table/inputs/ at all.
        self.assertIn("--sandbox", seen[0])
        self.assertNotIn("accept-edits", seen[0])
        self.assertIn("accept-edits", seen[1])
        self.assertNotIn("--sandbox", seen[1])

    def test_an_empty_response_is_a_failure_with_a_usable_reason(self):
        # status SUCCESS with an empty response is how plan mode reports that
        # the model reached for a tool it may not use.
        def fake_run(cmd, prompt, cwd, timeout):
            class P:
                returncode = 0
            return P(), '{"conversation_id":"x","status":"SUCCESS","response":""}', ""

        real, S._run = S._run, fake_run
        try:
            turn = S.run_antigravity("hi", ".", {"cmd": "agy"})
        finally:
            S._run = real
        self.assertFalse(turn.ok)
        self.assertIn("empty response", turn["error"])


class TestAnswerTiming(RunnerCase):
    def test_waiting_on_a_human_with_nothing_queued_still_gets_a_synthesis(self):
        # Two finished turns and an empty queue is the end of the chain even
        # though a human was asked a question. Leaving ANSWER.md unwritten
        # makes the reader parse raw turns to find the conclusion.
        cfg = T.load_config(self.root)
        cfg["auto_answer"] = True
        T.save_config(self.root, cfg)
        fake = FakeSeats({"antigravity": turn_text("G", to="claude"),
                          "claude": turn_text("C", to="user")})
        topic = self.run_topic(fake)
        self.assertEqual(topic["status"], "waiting")
        self.assertTrue((T.topic_dir(self.root, topic["id"]) / "ANSWER.md").exists())

    def test_waiting_with_work_still_queued_does_not_synthesise_early(self):
        cfg = T.load_config(self.root)
        cfg["auto_answer"] = True
        T.save_config(self.root, cfg)
        fake = FakeSeats({"antigravity": turn_text("G", to="user")})
        topic = self.run_topic(fake)
        self.assertEqual(topic["status"], "waiting")
        self.assertFalse((T.topic_dir(self.root, topic["id"]) / "ANSWER.md").exists())
