"""Unit tests for the limits gauge.

The gauge no longer estimates anything: it runs `claude -p /usage` and reads the
answer. So what is worth testing is the parser - every shape of that report we
have seen, plus the shapes that mean "ask failed" - and the once-a-minute cache
in front of it. Nothing here launches a real CLI.

Run from the repo root:

    python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import syncagent as sa  # noqa: E402
import syncagent.usage as usage  # noqa: E402

REPORT = """You are currently using your subscription to power your Claude Code usage

Current session: 5% used · resets Aug 16, 10:30pm (America/Toronto)
Current week (all models): 17% used · resets Aug 22, 7am (America/Toronto)

What's contributing to your limits usage?
Approximate, based on local sessions on this machine.

Last 24h · 266 requests · 16 sessions
  55% of your usage was at >150k context
"""


class TestParser(unittest.TestCase):
    def test_the_session_line_is_the_five_hour_window(self):
        r = sa.parse_usage(REPORT)
        self.assertTrue(r["available"])
        self.assertEqual(r["window"]["percent"], 5.0)
        self.assertEqual(r["window"]["resets"], "Aug 16, 10:30pm (America/Toronto)")

    def test_the_week_line_is_kept_with_its_own_label(self):
        r = sa.parse_usage(REPORT)
        self.assertEqual(len(r["weeks"]), 1)
        self.assertEqual(r["weeks"][0]["label"], "week (all models)")
        self.assertEqual(r["weeks"][0]["percent"], 17.0)

    def test_a_plan_with_two_week_limits_reports_both(self):
        r = sa.parse_usage(
            "Current session: 1% used · resets Aug 16, 10:30pm\n"
            "Current week (all models): 12% used · resets Aug 22, 7am\n"
            "Current week (Opus): 44% used · resets Aug 22, 7am\n")
        self.assertEqual([k["percent"] for k in r["weeks"]], [12.0, 44.0])

    def test_the_prose_lines_around_it_are_not_mistaken_for_limits(self):
        # "55% of your usage was at >150k context" is a behaviour breakdown, not
        # a ceiling, and counting it as one would double the gauge.
        r = sa.parse_usage(REPORT)
        self.assertIsNone(next((b for b in r["weeks"] if b["percent"] == 55.0), None))

    def test_a_fractional_percent_survives(self):
        r = sa.parse_usage("Current session: 7.5% used · resets tomorrow")
        self.assertEqual(r["window"]["percent"], 7.5)

    def test_a_line_without_a_reset_clause_still_parses(self):
        r = sa.parse_usage("Current session: 3% used")
        self.assertEqual(r["window"]["percent"], 3.0)
        self.assertEqual(r["window"]["resets"], "")

    def test_a_plain_hyphen_separator_parses_too(self):
        # Not every console can encode a middle dot.
        r = sa.parse_usage("Current session: 9% used - resets Aug 16, 10:30pm")
        self.assertEqual(r["window"]["resets"], "Aug 16, 10:30pm")

    def test_an_answer_that_is_not_a_usage_report_is_unavailable(self):
        r = sa.parse_usage("I don't see a question here.")
        self.assertFalse(r["available"])
        self.assertIn("reason", r)
        self.assertIsNone(r["window"])
        self.assertEqual(r["weeks"], [])

    def test_empty_output_is_unavailable_rather_than_zero_percent(self):
        self.assertFalse(sa.parse_usage("")["available"])


class TestAsk(unittest.TestCase):
    def test_a_missing_claude_says_so_instead_of_raising(self):
        r = sa.ask_claude(Path.cwd(), cmd="definitely-not-a-real-cli")
        self.assertFalse(r["available"])
        self.assertIn("PATH", r["reason"])


class TestMeter(unittest.TestCase):
    def test_the_first_report_is_a_placeholder_not_a_blank_gauge(self):
        m = sa.UsageMeter(Path.cwd())
        self.assertFalse(m.report()["available"])
        self.assertIn("Asking", m.report()["reason"])

    def test_the_page_reads_the_cache_and_never_the_cli(self):
        m = sa.UsageMeter(Path.cwd())
        calls = []

        def fake_ask(root, cmd, **kw):
            calls.append(cmd)
            return usage.parse_usage(REPORT)

        real, usage.ask_claude = usage.ask_claude, fake_ask
        try:
            m._report = usage.ask_claude(m.root, m.cmd)
            for _ in range(50):
                m.report()
        finally:
            usage.ask_claude = real
        self.assertEqual(len(calls), 1)
        self.assertEqual(m.report()["window"]["percent"], 5.0)


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
