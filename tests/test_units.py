"""单位折叠与展示价履约测试：重复观测、证据分级、覆盖范围、跨入口去重。"""

import unittest

from audit.models import (
    Campaign,
    Draw,
    EvidenceKind,
    FrameStratum,
    Quote,
    RoomRule,
)
from audit.rules import RuleBook
from audit.units import UnitBuilder, in_ad_scope, opportunity_key

RULES = [
    RoomRule("RR1", "family", "H1", 1, "2026-11-01", "2026-11-01",
             2, 2, 6, 15, 10, 110),
]
CAMPAIGN = Campaign("S1", "portal", "P1", "2026-11-01", "2026-11-18",
                    "2026-11-05", "2026-11-23", (15, 15), 699, 0.6, "J1", 0.7)
FRAME = {
    "S10": FrameStratum("S10", "S1", "weekday", "small", 72, 12),
}


def d(draw_id, day="2026-11-09", arrival="2026-11-13", ages=(4, 6),
      repeat_of="", window=None):
    return Draw(draw_id, "S10", day, arrival, ages, 2, 1,
                window or f"{day}T11", repeat_of, "repeat" if repeat_of else "scheduled")


def q(quote_id, draw_id, outcome="bookable", nightly=600, fee=35, bed=True,
     pool="P1", room="family", hotel="H1", arrival="2026-11-13", window="2026-11-09T11"):
    return Quote(quote_id, draw_id, pool, room, hotel, arrival, window,
                 nightly if outcome == "bookable" else None,
                 fee if outcome == "bookable" else None, outcome,
                 bed if outcome == "bookable" else False)


def build(draws, quotes):
    return UnitBuilder({"S1": CAMPAIGN}, FRAME, {x.draw: x for x in draws},
                       quotes, RuleBook(RULES)).build()


class ScopeTests(unittest.TestCase):
    def test_arrival_outside_window(self):
        ok, reasons = in_ad_scope(CAMPAIGN, d("D1", arrival="2026-11-30"))
        self.assertFalse(ok)
        self.assertTrue(any("入住日" in r for r in reasons))

    def test_search_outside_running_window(self):
        ok, reasons = in_ad_scope(CAMPAIGN, d("D1", day="2026-11-25"))
        self.assertFalse(ok)
        self.assertTrue(any("投放期" in r for r in reasons))

    def test_age_over_advertised_cap(self):
        ok, reasons = in_ad_scope(CAMPAIGN, d("D1", ages=(10, 16)))
        self.assertFalse(ok)
        self.assertTrue(any("适用上限" in r for r in reasons))

    def test_out_of_scope_unit_not_bookable_even_with_quote(self):
        draws = [d("D1", day="2026-11-25")]
        verdicts = build(draws, [q("Q1", "D1")])
        self.assertIs(verdicts[0].kind, EvidenceKind.OUT_OF_SCOPE)


class FoldTests(unittest.TestCase):
    def test_timeout_rescued_by_repeat_bookable(self):
        # 同一次抽样：首次 timeout，重复观测拿到可订报价 -> 履约，不是无法归类
        draws = [d("D1"), d("D1R", repeat_of="D1")]
        quotes = [q("Q1", "D1", outcome="timeout", nightly=None, fee=None),
                  q("Q1R", "D1R", nightly=600, fee=35)]
        verdicts = build(draws, quotes)
        self.assertEqual(len(verdicts), 1)
        self.assertIs(verdicts[0].kind, EvidenceKind.FULFILLED)
        self.assertEqual(verdicts[0].member_draws, ("D1", "D1R"))

    def test_all_timeout_is_unclassified_not_breach(self):
        draws = [d("D1"), d("D1R", repeat_of="D1")]
        quotes = [q("Q1", "D1", outcome="timeout", nightly=None, fee=None),
                  q("Q1R", "D1R", outcome="timeout", nightly=None, fee=None)]
        self.assertIs(build(draws, quotes)[0].kind, EvidenceKind.TIMEOUT)

    def test_bookable_over_cap_is_price_exceeded(self):
        verdicts = build([d("D1")], [q("Q1", "D1", nightly=700, fee=35)])
        self.assertIs(verdicts[0].kind, EvidenceKind.PRICE_EXCEEDED)
        self.assertEqual(verdicts[0].payable, 735)

    def test_cheapest_bookable_wins_across_observations(self):
        draws = [d("D1"), d("D1R", repeat_of="D1")]
        quotes = [q("Q1", "D1", nightly=680, fee=35),
                  q("Q1R", "D1R", nightly=610, fee=35)]
        verdict = build(draws, quotes)[0]
        self.assertIs(verdict.kind, EvidenceKind.FULFILLED)
        self.assertEqual(verdict.payable, 645)

    def test_ineligible_hard_evidence_beats_timeout(self):
        draws = [d("D1"), d("D1R", repeat_of="D1")]
        quotes = [q("Q1", "D1", outcome="timeout", nightly=None, fee=None),
                  q("Q1R", "D1R", outcome="ineligible", nightly=None, fee=None)]
        self.assertIs(build(draws, quotes)[0].kind, EvidenceKind.INELIGIBLE)

    def test_no_inventory_distinct_from_ineligible(self):
        v1 = build([d("D1")], [q("Q1", "D1", outcome="no_inventory", nightly=None, fee=None)])[0]
        self.assertIs(v1.kind, EvidenceKind.NO_INVENTORY)
        v2 = build([d("D2")], [q("Q2", "D2", outcome="ineligible", nightly=None, fee=None)])[0]
        self.assertIs(v2.kind, EvidenceKind.INELIGIBLE)


class OpportunityKeyTests(unittest.TestCase):
    def test_same_pool_signature_is_one_opportunity(self):
        a = d("D1", window="2026-11-09T11")
        b = d("D2", window="2026-11-09T11")
        self.assertEqual(opportunity_key("P1", a), opportunity_key("P1", b))

    def test_different_pool_is_different_opportunity(self):
        a = d("D1")
        b = d("D2")
        self.assertNotEqual(opportunity_key("P1", a), opportunity_key("P2", b))


if __name__ == "__main__":
    unittest.main()
