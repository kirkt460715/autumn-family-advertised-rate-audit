"""规则引擎测试：搜索当日版本回看、房型适配、强制加床与含费价。"""

import unittest

from audit.models import Draw, EvidenceKind, Quote, RoomRule
from audit.rules import RuleBook, assess_quote, family_fits, mandatory_bed_count

RR1 = RoomRule("RR1", "family", "H1", 1, "2026-11-01", "2026-11-01",
               2, 2, 6, 15, 10, 110)
RR2 = RoomRule("RR2", "family", "H1", 2, "2026-11-11", "2026-11-16",
               2, 2, 8, 16, 11, 90)
RR3 = RoomRule("RR3", "double", "H1", 1, "2026-11-01", "2026-11-01",
               2, 1, 6, 12, 8, 125)


def draw(day="2026-11-09", ages=(7, 14), adults=2, rooms=1, key="D1"):
    return Draw(key, "S11", day, "2026-11-13", ages, adults, rooms,
                f"{day}T11", "", "scheduled")


def quote(outcome="bookable", nightly=700, fee=35, bed_included=False,
          room="family", hotel="H1", key="Q1"):
    return Quote(key, "D1", "P1", room, hotel, "2026-11-13", "2026-11-09T11",
                 nightly, fee, outcome, bed_included)


class RuleVersionTests(unittest.TestCase):
    def setUp(self):
        self.book = RuleBook([RR1, RR2, RR3])

    def test_version_visible_only_after_documentation_day(self):
        # 11-15：RR2 虽已生效但尚未登记（documented=11-16），只能看见 RR1
        self.assertEqual(self.book.visible_on("family", "H1", "2026-11-15").rule, "RR1")
        # 11-16 当天 RR2 已登记，可见 rev2
        self.assertEqual(self.book.visible_on("family", "H1", "2026-11-16").rule, "RR2")
        self.assertEqual(self.book.visible_on("family", "H1", "2026-11-20").rule, "RR2")

    def test_no_visible_rule_means_ineligible_not_bookable(self):
        book = RuleBook([RoomRule("RR9", "suite", "H9", 1, "2026-12-01", "2026-12-01",
                                  2, 2, 6, 15, 10, 100)])
        a = assess_quote(quote(room="suite", hotel="H9"), draw(), book)
        self.assertIs(a.kind, EvidenceKind.INELIGIBLE)
        self.assertIsNone(a.payable)


class FamilyFitTests(unittest.TestCase):
    def setUp(self):
        self.book = RuleBook([RR1, RR2, RR3])

    def test_double_room_rejects_two_children(self):
        d = draw(ages=(3, 5))
        fit, reasons = family_fits(RR3, d)
        self.assertFalse(fit)
        self.assertTrue(any("max_children" in r for r in reasons))

    def test_age_cap_uses_rule_visible_on_search_day(self):
        # 16 岁儿童：11-15 仅 RR1 可见（max_age 15）-> 不适配；11-16 后 RR2（16）-> 适配
        d_old = draw(day="2026-11-15", ages=(9, 16))
        fit_before, _ = family_fits(self.book.visible_on("family", "H1", d_old.search_day), d_old)
        self.assertFalse(fit_before)
        d_new = draw(day="2026-11-16", ages=(9, 16), key="D2")
        fit_after, _ = family_fits(self.book.visible_on("family", "H1", d_new.search_day), d_new)
        self.assertTrue(fit_after)

    def test_bookable_label_overridden_when_rule_rejects(self):
        # 酒店接口返回 bookable，但按搜索当日规则超龄 -> 必须改判 ineligible
        d = draw(day="2026-11-11", ages=(9, 16))
        a = assess_quote(quote(nightly=729, bed_included=True), d, self.book)
        self.assertIs(a.kind, EvidenceKind.INELIGIBLE)
        self.assertFalse(a.structurally_fit)


class BedFeeAndPayableTests(unittest.TestCase):
    def setUp(self):
        self.book = RuleBook([RR1, RR2, RR3])

    def test_mandatory_bed_count(self):
        self.assertEqual(mandatory_bed_count(RR1, draw(ages=(10, 13))), 2)
        self.assertEqual(mandatory_bed_count(RR1, draw(ages=(4, 6))), 0)

    def test_payable_adds_bed_fee_when_not_included(self):
        d = draw(ages=(10, 13))
        a = assess_quote(quote(nightly=610, fee=35, bed_included=False), d, self.book)
        # 两张强制加床 × 110
        self.assertEqual(a.mandatory_bed_due, 220)
        self.assertEqual(a.payable, 610 + 35 + 220)

    def test_payable_no_double_count_when_bed_included(self):
        d = draw(ages=(9, 13))
        a = assess_quote(quote(nightly=610, fee=35, bed_included=True), d, self.book)
        self.assertEqual(a.mandatory_bed_due, 0)
        self.assertEqual(a.payable, 645)

    def test_timeout_and_no_inventory_keep_distinct_evidence(self):
        self.assertIs(assess_quote(quote(outcome="timeout", nightly=None, fee=None),
                                   draw(), self.book).kind, EvidenceKind.TIMEOUT)
        self.assertIs(assess_quote(quote(outcome="no_inventory", nightly=None, fee=None),
                                   draw(), self.book).kind, EvidenceKind.NO_INVENTORY)


if __name__ == "__main__":
    unittest.main()
