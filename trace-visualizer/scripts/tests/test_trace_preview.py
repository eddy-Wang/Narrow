import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("trace_preview", Path(__file__).parents[1] / "build-trace-preview.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class SnapshotTests(unittest.TestCase):
    def test_missing_snapshot_is_unknown(self):
        self.assertEqual(preview.snapshot_stage("x", "x", None, "target")["status"], "unknown")

    def test_truncated_snapshot_does_not_prove_absence(self):
        value = preview.snapshot_stage("x", "x", {"count": 100, "top": [{"parent_asin": "other"}]}, "target")
        self.assertEqual(value["status"], "unknown")
        self.assertIsNone(value["targetRank"])

    def test_complete_snapshot_proves_absence(self):
        self.assertEqual(preview.snapshot_stage("x", "x", {"count": 0, "top": []}, "target")["status"], "absent")

    def test_present_rank_is_exact(self):
        value = preview.snapshot_stage("x", "x", {"count": 100, "top": [{"parent_asin": "other"}, {"parent_asin": "target"}]}, "target")
        self.assertEqual(value["targetRank"], 2)

    def make_stages(self):
        return [preview.snapshot_stage(name, label, None, "target") for name, label, _ in preview.STAGES] + [preview.snapshot_stage("response", "最终", {"count": 0, "top": []}, "target")]

    def test_unknown_retrieval_does_not_become_recall_failure(self):
        self.assertEqual(preview.diagnosis(self.make_stages(), True)[0], "unknown")

    def test_filter_present_and_ranked_outside_top20_proves_rerank_miss(self):
        stages = self.make_stages()
        stages[4] = preview.snapshot_stage("filter", "过滤", {"count": 100, "top": [{"parent_asin": "target"}]}, "target")
        stages[5] = preview.snapshot_stage("rerank", "精排", {"count": 100, "top": [{"parent_asin": str(i)} for i in range(20)]}, "target")
        self.assertEqual(preview.diagnosis(stages, True)[0], "rerank")

    def test_pre_override_recommendation_is_gated(self):
        stages = self.make_stages()
        stages[-1] = preview.snapshot_stage("response", "最终", {"count": 1, "top": [{"parent_asin": "target"}]}, "target")
        self.assertEqual(preview.diagnosis(stages, False)[0], "gated")
        self.assertEqual(preview.diagnosis(stages, True)[0], "hit")


if __name__ == "__main__":
    unittest.main()
