"""后送补证测试：采纳/驳回边界与三类影响分类。"""

import unittest

from audit.amendments import (
    IMPACT_FUTURE_SCOPE,
    IMPACT_REJECTED,
    IMPACT_STATISTICS,
    process_amendments,
)
from audit.io_csv import load_bundle
from audit.models import Amendment, EvidenceKind
from audit.pipeline import run_audit
from audit.rules import RuleBook, assess_quote
from audit.units import UnitBuilder

DATA = "data"


class AmendmentOnRealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_audit(DATA)
        cls.bundle = cls.result.bundle
        cls.rule_book = RuleBook(cls.bundle.room_rules)
        cls.effects = {
            e.notice: e
            for e in process_amendments(cls.bundle.amendments, cls.bundle.draws,
                                        cls.result.verdicts, cls.rule_book)
        }

    def test_u1_bed_confirmation_rejected_when_no_bed_due(self):
        # X00-00 是 no_inventory 的 double 房，儿童 3|5 岁未达强制加床年龄
        eff = self.effects["U1"]
        self.assertFalse(eff.accepted)
        self.assertEqual(eff.impact, IMPACT_REJECTED)

    def test_u2_reserve_origin_accepted_and_dedupes(self):
        eff = self.effects["U2"]
        self.assertTrue(eff.accepted)
        self.assertEqual(eff.impact, IMPACT_STATISTICS)
        # 联营口径确实折叠了跨入口重复
        self.assertGreater(self.result.joint.duplicates_collapsed, 0)

    def test_u3_past_policy_rejected_keeps_search_day_version(self):
        eff = self.effects["U3"]
        self.assertFalse(eff.accepted)
        self.assertEqual(eff.impact, IMPACT_FUTURE_SCOPE)
        # X05-03 在 11-09 搜索：double 房 RR3 max_age 12，14 岁儿童仍判不适配
        verdict = next(u for u in self.result.verdicts if u.base_key == "X05-03")
        self.assertIs(verdict.kind, EvidenceKind.INELIGIBLE)
        self.assertIn("RR2", eff.detail)  # 说明里明确指出现行版本当时不可见


class BedConfirmationSyntheticTests(unittest.TestCase):
    def test_bed_confirmation_accepted_when_bed_fee_missing(self):
        bundle = load_bundle(DATA)
        rule_book = RuleBook(bundle.room_rules)
        # 选一条经规则引擎确认存在"未计入展示价的强制加床"的可订报价
        target_draw = None
        for q in bundle.quotes:
            if q.outcome != "bookable" or q.bed_included:
                continue
            assessment = assess_quote(q, bundle.draws[q.draw], rule_book)
            if assessment.mandatory_bed_due > 0:
                target_draw = bundle.draws[q.draw]
                break
        self.assertIsNotNone(target_draw)
        notice = Amendment("UX", target_draw.base_key, "bed_confirmation", "RR1",
                           "2026-11-20", "required")
        builder = UnitBuilder(bundle.campaigns, bundle.frame, bundle.draws,
                              bundle.quotes, rule_book, [notice])
        verdicts = builder.build()
        effects = process_amendments([notice], bundle.draws, verdicts, rule_book)
        self.assertTrue(effects[0].accepted)
        self.assertEqual(effects[0].impact, IMPACT_STATISTICS)


if __name__ == "__main__":
    unittest.main()
