"""抽样单位构建：覆盖范围核对、重复观测折叠、展示价履约判定与联营去重。

证据折叠规则（同一基础抽样单位的多次观测，含 repeat_of 重复抽次）：

1. 只要存在一条"含应付费用、整户可接纳且不超承诺价"的报价，单位即履约；
2. 否则存在可订但偏高的报价 -> ``price_exceeded``（明确搜到了偏高价）；
3. 否则取最强的硬证据：ineligible / no_inventory / out_of_scope；
4. 全部观测均为 timeout 才是 timeout（接口没返回，属无法归类，不是违约）。

同一房池、同入住日、同放房时窗、同家庭参数的报价是同一可订机会，
跨入口（portal/hotel）不得计作两份机会。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .models import (
    Amendment,
    Campaign,
    Draw,
    EvidenceKind,
    FrameStratum,
    HARD_EVIDENCE,
    Quote,
    UnitVerdict,
)
from .rules import RuleBook, assess_quote

# 硬证据优先级（数字越小越优先；履约与偏价在折叠时先于这两类处理）
_EVIDENCE_RANK = {
    EvidenceKind.INELIGIBLE: 0,
    EvidenceKind.NO_INVENTORY: 1,
    EvidenceKind.OUT_OF_SCOPE: 2,
    EvidenceKind.PRICE_EXCEEDED: 3,
    EvidenceKind.FULFILLED: 4,
    EvidenceKind.TIMEOUT: 5,
}


@dataclass(frozen=True)
class OpportunityKey:
    """联营口径下识别"同一可售机会"的去重键。"""

    pool: str
    arrival: str
    window: str
    ages: tuple[int, ...]
    adults: int
    rooms: int


def opportunity_key(pool: str, draw: Draw) -> OpportunityKey:
    return OpportunityKey(pool, draw.arrival, draw.availability_window,
                          draw.ages, draw.adults, draw.rooms)


def in_ad_scope(campaign: Campaign, draw: Draw) -> tuple[bool, tuple[str, ...]]:
    """核对广告覆盖的入住日期、张贴时刻（搜索日落在投放期）与家庭构成。"""
    reasons: list[str] = []
    if not campaign.arrival_lo <= draw.arrival <= campaign.arrival_hi:
        reasons.append(f"入住日 {draw.arrival} 超出广告入住区间 "
                       f"{campaign.arrival_lo}~{campaign.arrival_hi}")
    if not campaign.running_from <= draw.search_day <= campaign.running_through:
        reasons.append(f"搜索日 {draw.search_day} 落在投放期 "
                       f"{campaign.running_from}~{campaign.running_through} 之外")
    over = [a for a, cap in zip(draw.ages, campaign.max_ages) if a > cap]
    if over:
        reasons.append(f"儿童年龄 {over} 超出广告适用上限 {campaign.max_ages}")
    if len(draw.ages) > len(campaign.max_ages):
        reasons.append("儿童人数超出广告适用说明")
    return not reasons, tuple(reasons)


class UnitBuilder:
    """把报价、抽次、规则与广告承诺组装成单位判定。"""

    def __init__(self, campaigns: dict[str, Campaign], frame: dict[str, FrameStratum],
                 draws: dict[str, Draw], quotes: list[Quote], rule_book: RuleBook,
                 amendments: list[Amendment] | None = None):
        self._campaigns = campaigns
        self._frame = frame
        self._draws = draws
        self._rule_book = rule_book
        self._quotes_by_draw: dict[str, list[Quote]] = defaultdict(list)
        for q in quotes:
            self._quotes_by_draw[q.draw].append(q)
        self._amendments_by_draw: dict[str, list[Amendment]] = defaultdict(list)
        for am in amendments or []:
            self._amendments_by_draw[am.draw].append(am)

    def build(self) -> list[UnitVerdict]:
        bases: dict[str, list[Draw]] = defaultdict(list)
        for draw in self._draws.values():
            bases[draw.base_key].append(draw)

        verdicts: list[UnitVerdict] = []
        for base_key in sorted(bases):
            members = sorted(bases[base_key], key=lambda d: d.draw)
            verdicts.append(self._build_one(base_key, members))
        return verdicts

    def _build_one(self, base_key: str, members: list[Draw]) -> UnitVerdict:
        primary = members[0]
        stratum = self._frame[primary.stratum]
        campaign = self._campaigns[stratum.ad]
        notices = tuple(am.notice for am in self._amendments_by_draw.get(base_key, ()))

        in_scope, scope_reasons = in_ad_scope(campaign, primary)
        if not in_scope:
            return UnitVerdict(
                base_key=base_key, ad=campaign.ad, stratum=stratum.stratum,
                arrival_kind=stratum.arrival_kind, family_kind=stratum.family_kind,
                arrival=primary.arrival, search_day=primary.search_day,
                ages=primary.ages, adults=primary.adults, rooms=primary.rooms,
                pool=campaign.pool, window=primary.availability_window,
                member_draws=tuple(d.draw for d in members),
                kind=EvidenceKind.OUT_OF_SCOPE, reason="；".join(scope_reasons),
                payable=None, assessments=(), amended_notices=notices,
            )

        assessments: list[QuoteAssessment] = []
        for draw in members:
            for quote in self._quotes_by_draw[draw.draw]:
                assessments.append(assess_quote(quote, draw, self._rule_book))

        kind, reason, payable = self._fold(campaign, assessments)
        return UnitVerdict(
            base_key=base_key, ad=campaign.ad, stratum=stratum.stratum,
            arrival_kind=stratum.arrival_kind, family_kind=stratum.family_kind,
            arrival=primary.arrival, search_day=primary.search_day,
            ages=primary.ages, adults=primary.adults, rooms=primary.rooms,
            pool=campaign.pool, window=primary.availability_window,
            member_draws=tuple(d.draw for d in members),
            kind=kind, reason=reason, payable=payable,
            assessments=tuple(assessments), amended_notices=notices,
        )

    def _fold(self, campaign: Campaign, assessments: list[QuoteAssessment]):
        """折叠同一单位的全部观测，并对照广告承诺价改判偏价。"""
        cap = campaign.max_price
        priced: list[QuoteAssessment] = []
        for a in assessments:
            if a.kind is EvidenceKind.FULFILLED and a.payable is not None:
                if a.payable <= cap:
                    return (EvidenceKind.FULFILLED,
                            f"含应付费用 {a.payable} 元 <= 承诺价 {cap} 元，整户可接纳",
                            a.payable)
                priced.append(a)
        if priced:
            cheapest = min(priced, key=lambda a: a.payable)  # type: ignore[arg-type]
            return (EvidenceKind.PRICE_EXCEEDED,
                    f"最低含费报价 {cheapest.payable} 元高于承诺价 {cap} 元",
                    cheapest.payable)

        hard = [a for a in assessments if a.kind in HARD_EVIDENCE]
        if hard:
            best = min(hard, key=lambda a: _EVIDENCE_RANK[a.kind])
            return best.kind, best.reason, None
        if all(a.kind is EvidenceKind.TIMEOUT for a in assessments):
            return EvidenceKind.TIMEOUT, "全部观测接口未返回，无法归类", None
        return EvidenceKind.TIMEOUT, "缺少可验证的搜索结果", None
