"""分层估计、非应答边界与联营联合覆盖测试。"""

import unittest

from audit.estimation import (
    ad_estimate,
    breakdown_estimates,
    estimate_rate,
    joint_estimate,
)
from audit.models import (
    Campaign,
    Draw,
    EvidenceKind,
    FrameStratum,
    UnitVerdict,
)


def verdict(base, ad="S1", stratum="S10", kind=EvidenceKind.FULFILLED,
            arrival_kind="weekday", family_kind="small", pool="P1",
            arrival="2026-11-09", window="2026-11-09T11", ages=(4, 6)):
    return UnitVerdict(
        base_key=base, ad=ad, stratum=stratum, arrival_kind=arrival_kind,
        family_kind=family_kind, arrival=arrival, search_day="2026-11-09",
        ages=ages, adults=2, rooms=1, pool=pool, window=window,
        member_draws=(base,), kind=kind, reason="",
        payable=600 if kind is EvidenceKind.FULFILLED else None,
    )


FRAME_TWO = [
    FrameStratum("S10", "S1", "weekday", "small", 100, 10),
    FrameStratum("S11", "S1", "weekday", "older", 100, 10),
]
CAMP = Campaign("S1", "portal", "P1", "2026-11-01", "2026-11-18",
                "2026-11-05", "2026-11-23", (15, 15), 699, 0.6, "", None)


class EstimationTests(unittest.TestCase):
    def test_weights_follow_population_per_base_unit(self):
        # 每层 10 个基础单位、人口 100 -> 单位权重 10
        units = [verdict(f"D{i}", stratum="S10") for i in range(5)]
        units += [verdict(f"E{i}", stratum="S10", kind=EvidenceKind.INELIGIBLE)
                  for i in range(5)]
        units += [verdict(f"F{i}", stratum="S11", kind=EvidenceKind.TIMEOUT)
                  for i in range(10)]
        est = ad_estimate(CAMP, units, FRAME_TWO)
        # S10 全分类、半数履约 -> 点估计 0.5；S11 全部无法归类
        self.assertAlmostEqual(est.point, 0.5, places=6)
        self.assertAlmostEqual(est.fulfilled_weight, 50.0)
        self.assertAlmostEqual(est.classified_weight, 100.0)
        self.assertAlmostEqual(est.unclassified_weight, 100.0)

    def test_nonresponse_envelope_spans_both_extremes(self):
        units = [verdict(f"D{i}", stratum="S10") for i in range(5)]
        units += [verdict(f"E{i}", stratum="S10", kind=EvidenceKind.TIMEOUT)
                  for i in range(5)]
        est = ad_estimate(CAMP, units, FRAME_TWO[:1])
        # 5 履约 + 5 无法归类：下界 0.5（timeout 全不履约），上界 1.0（全履约）
        self.assertAlmostEqual(est.nonresponse_bounds[0], 0.5, places=6)
        self.assertAlmostEqual(est.nonresponse_bounds[1], 1.0, places=6)
        self.assertEqual(est.interval[0], min(est.sampling_ci[0], 0.5))
        self.assertEqual(est.interval[1], max(est.sampling_ci[1], 1.0))

    def test_indeterminate_when_interval_crosses_commitment(self):
        # 4 履约 + 6 无法归类：非应答边界 [0.4, 1.0]，承诺 0.6 落在区间内
        units = [verdict(f"D{i}", stratum="S10") for i in range(4)]
        units += [verdict(f"E{i}", stratum="S10", kind=EvidenceKind.TIMEOUT)
                  for i in range(6)]
        est = ad_estimate(CAMP, units, FRAME_TWO[:1])
        self.assertAlmostEqual(est.nonresponse_bounds[0], 0.4, places=6)
        self.assertAlmostEqual(est.nonresponse_bounds[1], 1.0, places=6)
        self.assertEqual(est.decision, "indeterminate")

    def test_met_and_not_met_decisions(self):
        met_units = [verdict(f"D{i}", stratum="S10") for i in range(10)]
        self.assertEqual(ad_estimate(CAMP, met_units, FRAME_TWO[:1]).decision, "met")
        bad_units = [verdict(f"D{i}", stratum="S10",
                             kind=EvidenceKind.PRICE_EXCEEDED) for i in range(10)]
        self.assertEqual(ad_estimate(CAMP, bad_units, FRAME_TWO[:1]).decision, "not_met")

    def test_breakdown_dimensions(self):
        units = [verdict(f"D{i}", stratum="S10", family_kind="small",
                         arrival_kind="weekday") for i in range(10)]
        units += [verdict(f"E{i}", stratum="S11", family_kind="older",
                          arrival_kind="weekday", kind=EvidenceKind.INELIGIBLE)
                  for i in range(10)]
        by_family = breakdown_estimates(CAMP, units, FRAME_TWO, "family_kind")
        labels = {e.label: e for e in by_family}
        self.assertIn("S1 / family_kind=small", labels)
        self.assertAlmostEqual(labels["S1 / family_kind=small"].point, 1.0)
        self.assertAlmostEqual(labels["S1 / family_kind=older"].point, 0.0)


class JointEstimateTests(unittest.TestCase):
    def _campaigns(self):
        s1 = Campaign("S1", "portal", "P1", "2026-11-01", "2026-11-18",
                      "2026-11-05", "2026-11-23", (15, 15), 699, 0.6, "J1", 0.7)
        s2 = Campaign("S2", "hotel", "P1", "2026-11-01", "2026-11-18",
                      "2026-11-05", "2026-11-23", (15, 15), 719, 0.64, "J1", 0.7)
        return {"S1": s1, "S2": s2}

    def _frame(self):
        return [
            FrameStratum("S10", "S1", "weekday", "small", 100, 10),
            FrameStratum("S20", "S2", "weekday", "small", 120, 10),
        ]

    def test_shared_pool_opportunity_counted_once(self):
        # 两个入口各观察同一批 10 个机会，签名两两一致 -> 联合口径只有 10 个机会
        units = []
        for i in range(10):
            arrival = f"2026-11-{10 + i:02d}"
            window = f"2026-11-{i + 1:02d}T11"
            units.append(verdict(f"A{i}", ad="S1", stratum="S10",
                                 arrival=arrival, window=window))
            units.append(verdict(f"B{i}", ad="S2", stratum="S20",
                                 arrival=arrival, window=window))
        joint = joint_estimate(self._campaigns(), units, self._frame())
        self.assertEqual(joint.duplicates_collapsed, 10)
        # 联合人口取成员层人口并集上界 max(100,120)=120
        self.assertEqual(joint.estimate.population, 120)
        self.assertEqual(joint.estimate.decision, "met")

    def test_separate_entry_evaluation_would_double_count(self):
        # 反证：分别评估时两广告结论相反；联合去重后每个机会只判一次
        units = []
        for i in range(10):
            arrival = f"2026-11-{10 + i:02d}"
            window = f"2026-11-{i + 1:02d}T11"
            units.append(verdict(f"A{i}", ad="S1", stratum="S10",
                                 arrival=arrival, window=window))
            units.append(verdict(f"B{i}", ad="S2", stratum="S20",
                                 kind=EvidenceKind.INELIGIBLE,
                                 arrival=arrival, window=window))
        joint = joint_estimate(self._campaigns(), units, self._frame())
        # 合并后每个签名一条履约一条不适配 -> 保留更强的 fulfilled，10 个全履约
        self.assertEqual(joint.duplicates_collapsed, 10)
        self.assertAlmostEqual(joint.estimate.point, 1.0)
        # 单项估计里 S2 仍是 0，说明分别评估会给出与联合口径相反的结论
        self.assertAlmostEqual(joint.member_estimates["S2"].point, 0.0)

    def test_joint_rejects_mismatched_pools(self):
        campaigns = self._campaigns()
        campaigns["S2"] = Campaign("S2", "hotel", "P9", "2026-11-01", "2026-11-18",
                                   "2026-11-05", "2026-11-23", (15, 15), 719,
                                   0.64, "J1", 0.7)
        units = [verdict("A1", ad="S1", stratum="S10"),
                 verdict("B1", ad="S2", stratum="S20", pool="P9")]
        with self.assertRaises(ValueError):
            joint_estimate(campaigns, units, self._frame())


if __name__ == "__main__":
    unittest.main()
