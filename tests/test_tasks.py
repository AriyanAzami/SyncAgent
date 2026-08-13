"""Unit tests for the ledger's pure logic - ordering, disjointness, validation.

No workspace, no filesystem, no git. Run from the repo root:

    python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from syncagent import (  # noqa: E402
    find_cycle, natural_key, order_key, parallel_batch, ready_tasks,
    tasks_summary, validate_tasks,
)


def task(tid, **kw):
    base = {"id": tid, "title": f"task {tid}", "files": [f"{tid}.py"],
            "depends_on": [], "acceptance": "AC-1", "value": "medium",
            "size": "M", "assignee": "claude", "status": "todo"}
    base.update(kw)
    return base


class TestOrdering(unittest.TestCase):
    def test_value_beats_dependency_order(self):
        tasks = [task("T1", value="low"), task("T2", value="high")]
        self.assertEqual([t["id"] for t in ready_tasks(tasks)], ["T2", "T1"])

    def test_size_breaks_a_value_tie(self):
        tasks = [task("T1", value="high", size="L"), task("T2", value="high", size="S")]
        self.assertEqual([t["id"] for t in ready_tasks(tasks)], ["T2", "T1"])

    def test_id_breaks_the_remaining_tie_numerically(self):
        tasks = [task("T10"), task("T2")]
        self.assertEqual([t["id"] for t in ready_tasks(tasks)], ["T2", "T10"])
        self.assertLess(natural_key("T2"), natural_key("T10"))

    def test_unmet_dependency_is_not_ready(self):
        tasks = [task("T1", status="todo"), task("T2", depends_on=["T1"])]
        self.assertEqual([t["id"] for t in ready_tasks(tasks)], ["T1"])

    def test_met_dependency_becomes_ready(self):
        tasks = [task("T1", status="done"), task("T2", depends_on=["T1"])]
        self.assertEqual([t["id"] for t in ready_tasks(tasks)], ["T2"])

    def test_doing_and_blocked_are_not_ready(self):
        tasks = [task("T1", status="doing"), task("T2", status="blocked")]
        self.assertEqual(ready_tasks(tasks), [])

    def test_missing_value_and_size_default_to_the_middle(self):
        self.assertEqual(order_key({"id": "T1"}), order_key(task("T1")))


class TestParallel(unittest.TestCase):
    def test_never_returns_two_tasks_sharing_a_file(self):
        tasks = [task("T1", files=["a.py", "b.py"]), task("T2", files=["b.py"]),
                 task("T3", files=["c.py"])]
        batch = parallel_batch(ready_tasks(tasks))
        self.assertEqual([t["id"] for t in batch], ["T1", "T3"])

    def test_empty_files_runs_alone(self):
        tasks = [task("T1", files=[], value="high"), task("T2", files=["c.py"])]
        batch = parallel_batch(ready_tasks(tasks))
        self.assertEqual([t["id"] for t in batch], ["T1"])

    def test_empty_files_never_joins_an_existing_batch(self):
        tasks = [task("T1", files=["a.py"], value="high"), task("T2", files=[])]
        batch = parallel_batch(ready_tasks(tasks))
        self.assertEqual([t["id"] for t in batch], ["T1"])

    def test_respects_the_cap(self):
        tasks = [task(f"T{i}", files=[f"{i}.py"]) for i in range(1, 6)]
        self.assertEqual(len(parallel_batch(ready_tasks(tasks), 2)), 2)

    def test_zero_cap_returns_nothing(self):
        self.assertEqual(parallel_batch([task("T1")], 0), [])


class TestValidation(unittest.TestCase):
    def errors(self, tasks):
        return validate_tasks({"tasks": tasks})[0]

    def test_a_clean_ledger_has_no_errors(self):
        self.assertEqual(self.errors([task("T1"), task("T2", depends_on=["T1"])]), [])

    def test_duplicate_id_is_named(self):
        errs = self.errors([task("T1"), task("T1")])
        self.assertTrue(any("T1" in e and "duplicate" in e for e in errs))

    def test_unknown_dependency_names_both_ids(self):
        errs = self.errors([task("T1", depends_on=["T9"])])
        self.assertTrue(any("T1" in e and "T9" in e for e in errs))

    def test_cycle_is_detected(self):
        errs = self.errors([task("T1", depends_on=["T2"]), task("T2", depends_on=["T1"])])
        self.assertTrue(any("cycle" in e for e in errs))

    def test_self_dependency_is_a_cycle(self):
        self.assertIsNotNone(find_cycle([task("T1", depends_on=["T1"])]))

    def test_bad_enum_value_is_rejected(self):
        errs = self.errors([task("T1", value="critical")])
        self.assertTrue(any("value" in e for e in errs))

    def test_missing_acceptance_warns_but_does_not_block(self):
        errors, warnings = validate_tasks({"tasks": [task("T1", acceptance="")]})
        self.assertEqual(errors, [])
        self.assertTrue(any("acceptance" in w for w in warnings))

    def test_not_an_object(self):
        self.assertTrue(validate_tasks([])[0])


class TestSummary(unittest.TestCase):
    def test_value_weighted_completion(self):
        # high=3 done, of high=3 + low=1 total -> 75%
        tasks = [task("T1", value="high", status="done"), task("T2", value="low")]
        self.assertEqual(tasks_summary(tasks)["value_percent"], 75)

    def test_empty_roadmap_does_not_divide_by_zero(self):
        self.assertEqual(tasks_summary([])["value_percent"], 0)

    def test_counts_by_status(self):
        s = tasks_summary([task("T1", status="done"), task("T2", status="blocked")])
        self.assertEqual(s["done"], 1)
        self.assertEqual(s["by_status"]["blocked"], 1)


if __name__ == "__main__":
    unittest.main()
