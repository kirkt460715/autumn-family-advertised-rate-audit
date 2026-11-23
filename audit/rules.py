"""房型规则引擎：按搜索当日可见版本回看，不允许用后补规则解释当时的拒单。

规则版本选择（针对同一 room+hotel）：

1. ``valid_from`` 不晚于搜索日；且
2. ``documented``（报送/登记日）不晚于搜索日——搜索时还没登记的版本不可见；
3. 取满足条件的最高 ``revision``。

没有任何可见版本时，该报价不能被当作可接纳证据。
"""

from __future__ import annotations

from collections import defaultdict

from .models import Draw, EvidenceKind, Quote, QuoteAssessment, RoomRule


class RuleBook:
    """按 room+hotel 索引的房型规则集合。"""

    def __init__(self, rules: list[RoomRule]):
        self._by_room: dict[tuple[str, str], list[RoomRule]] = defaultdict(list)
        for rule in rules:
            self._by_room[(rule.room, rule.hotel)].append(rule)
        for versions in self._by_room.values():
            versions.sort(key=lambda r: (r.valid_from, r.revision))

    def visible_on(self, room: str, hotel: str, search_day: str) -> RoomRule | None:
        """搜索当日实际可查看到的规则版本。"""
        candidates = [
            r
            for r in self._by_room.get((room, hotel), ())
            if r.valid_from <= search_day and r.documented <= search_day
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.revision)

    def latest(self, room: str, hotel: str) -> RoomRule | None:
        versions = self._by_room.get((room, hotel))
        return max(versions, key=lambda r: r.revision) if versions else None


def family_fits(rule: RoomRule, draw: Draw) -> tuple[bool, tuple[str, ...]]:
    """按规则判断整户能否被该房型接纳。"""
    reasons: list[str] = []
    if draw.adults > rule.max_adults:
        reasons.append(f"adults {draw.adults} > max_adults {rule.max_adults}")
    if len(draw.ages) > rule.max_children:
        reasons.append(f"children {len(draw.ages)} > max_children {rule.max_children}")
    over_age = [a for a in draw.ages if a > rule.max_age]
    if over_age:
        reasons.append(f"child ages {over_age} exceed max_age {rule.max_age}")
    return not reasons, tuple(reasons)


def mandatory_bed_count(rule: RoomRule, draw: Draw) -> int:
    """达到强制加床年龄的儿童人数。"""
    return sum(1 for age in draw.ages if age >= rule.mandatory_bed_age)


def assess_quote(quote: Quote, draw: Draw, rule_book: RuleBook) -> QuoteAssessment:
    """对单条原始报价做规则复核，给出证据分级与含费应付价。

    - 接口未返回（timeout）：没有可用核验信息，不参与履约/违约判断；
    - 已查实库存约束（no_inventory）：库存证据优先；
    - 房型拒绝（ineligible）：结合搜索当日规则复核；
    - bookable：先做房型适配，再核算强制加床费与承诺价。
    """
    rule = rule_book.visible_on(quote.room, quote.hotel, draw.search_day)

    if quote.outcome == "timeout":
        return QuoteAssessment(quote, rule, False, (), 0, None,
                               EvidenceKind.TIMEOUT, "接口未返回，无可用核验信息")
    if quote.outcome == "no_inventory":
        return QuoteAssessment(quote, rule, False, (), 0, None,
                               EvidenceKind.NO_INVENTORY, "已查实房池无可用库存")
    if rule is None:
        return QuoteAssessment(
            quote, None, False, ("搜索当日无已登记的房型规则版本",), 0, None,
            EvidenceKind.INELIGIBLE, "搜索当日无可见房型规则，不能按可接纳处理",
        )

    fit, reasons = family_fits(rule, draw)
    if quote.outcome == "ineligible" or not fit:
        label = "原始结果标记 ineligible" if quote.outcome == "ineligible" else "展示可订但房型规则不接纳"
        return QuoteAssessment(quote, rule, fit, reasons, 0, None,
                               EvidenceKind.INELIGIBLE, f"{label}：{'；'.join(reasons) or '酒店拒绝该组合'}")

    # bookable 且结构适配：核算应付费用
    beds_due = mandatory_bed_count(rule, draw)
    extra_bed_fee = 0
    fee_notes: list[str] = []
    if not quote.bed_included and beds_due:
        extra_bed_fee = beds_due * rule.bed_fee
        fee_notes.append(f"强制加床 {beds_due} 张 × {rule.bed_fee} 元未计入展示价")
    assert quote.nightly_bundle is not None and quote.mandatory_fee is not None
    payable = quote.nightly_bundle + quote.mandatory_fee + extra_bed_fee
    return QuoteAssessment(
        quote, rule, True, tuple(fee_notes), extra_bed_fee, payable,
        EvidenceKind.FULFILLED,  # 价格越线在单位层对照广告承诺后再改判
        "含应付费用的整住期报价" + (f"（{fee_notes[0]}）" if fee_notes else ""),
    )
