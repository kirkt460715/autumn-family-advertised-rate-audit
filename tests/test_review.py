"""运营质检建议与联营联动重判测试。"""

import unittest

from audit.io_csv import load_bundle
from audit.models import Review
from audit.pipeline import run_audit
from audit.review import (
    PAUSE,
    WITHDRAW,
    recommend_for_ad,
    reevaluate_after_narrow,
)

DATA = "data"


class ReviewOnRealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_audit(DATA)
        cls.bundle = cls.result.bundle

    def test_s1_s2_withdraw_and_conflict_with_approved_record(self):
        rec_s1 = self.result.recommendations["S1"]
        rec_s2 = self.result.recommendations["S2"]
        self.assertEqual(rec_s1.decision, WITHDRAW)
        self.assertEqual(rec_s2.decision, WITHDRAW)
        self.assertTrue(any("approved" in c for c in rec_s1.conflicts_with_record))

    def test_s3_pause_with_supported_small_scope(self):
        rec = self.result.recommendations["S3"]
        self.assertEqual(rec.decision, PAUSE)
        self.assertIn("small", rec.supported_scopes)
        # 已登记提案是 weekday，但 weekday 子区间证据不足 -> 必须提示冲突
        self.assertTrue(any("weekday" in c for c in rec.conflicts_with_record))

    def test_joint_recommendation_withdraws_on_shared_pool(self):
        jr = self.result.joint_recommendation
        self.assertEqual(jr.decision, WITHDRAW)
        self.assertEqual(set(jr.member_decisions), {"S1", "S2"})

    def test_reevaluate_after_narrow_covers_all_shared_ads(self):
        affected = reevaluate_after_narrow(
            "J1", self.bundle.campaigns, self.result.verdicts,
            list(self.bundle.frame.values()), self.result.joint,
        )
        self.assertEqual(set(affected), {"S1", "S2"})
        for msg in affected.values():
            self.assertIn("joint_minimum", msg)

    def test_narrowed_candidate_cannot_relaunch_by_wording_alone(self):
        review = Review("RX", "S3", "candidate", "weekday", "2026-11-17")
        rec = recommend_for_ad(
            self.bundle.campaigns["S3"], self.result.ad_estimates["S3"],
            self.result.verdicts, list(self.bundle.frame.values()), review,
        )
        self.assertTrue(any("weekday" in c for c in rec.conflicts_with_record))

    def test_supported_scope_proposal_passes_when_subestimate_met(self):
        # small 团型点估计达标，提案缩窄到 small 不应报冲突
        review = Review("RY", "S3", "candidate", "small", "2026-11-17")
        rec = recommend_for_ad(
            self.bundle.campaigns["S3"], self.result.ad_estimates["S3"],
            self.result.verdicts, list(self.bundle.frame.values()), review,
        )
        self.assertFalse(any("small" in c for c in rec.conflicts_with_record))


if __name__ == "__main__":
    unittest.main()
