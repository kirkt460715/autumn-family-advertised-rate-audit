"""促销方后送补证的接收、回看与影响分类。

三类补证（见 evidence_amendments.csv）：

- ``bed_confirmation``（required）：酒店确认该次搜索强制加床确需付费，
  用于固化"展示价未含必付加床费"的判定，影响的是**统计支撑**（该机会不能算履约）。
- ``reserve_origin``（pool_shared）：确认两个入口共享同一预留房量，
  用于联营去重，影响的是**可售机会口径**，不得把一个家庭能订的房算成两份机会。
- ``past_policy``（not_visible）：声称现在的房型规则可以解释过去的拒单。
  按约定，规则补录后仍按搜索当日可见版本回看；该类补证被驳回，
  原广告确实违反的条款不因新规则而改变。

每条补证输出一个 :class:`AmendmentEffect`，告诉收报人核对结果改变的是：
统计支撑（statistics）、原广告条款违反（violation）还是下一轮发布范围（future_scope）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Amendment, Draw, UnitVerdict
from .rules import RuleBook

IMPACT_STATISTICS = "statistics"
IMPACT_VIOLATION = "violation"
IMPACT_FUTURE_SCOPE = "future_scope"
IMPACT_REJECTED = "rejected"


@dataclass
class AmendmentEffect:
    notice: str
    draw: str
    kind: str
    accepted: bool
    impact: str
    detail: str
    # 该补证指向的具体广告条款（如有）。补证本身不改变历史判定，
    # 这里只登记"原广告确实违反的条款"，与 impact（改变了什么）分开报告。
    clause_violations: tuple[str, ...] = ()


def process_amendments(amendments: list[Amendment],
                       draws: dict[str, Draw],
                       verdicts: list[UnitVerdict],
                       rule_book: RuleBook) -> list[AmendmentEffect]:
    by_base = {u.base_key: u for u in verdicts}
    rules_index = {
        rule.rule: rule
        for versions in rule_book._by_room.values()
        for rule in versions
    }
    effects: list[AmendmentEffect] = []
    for am in amendments:
        draw = draws[am.draw]
        verdict = by_base.get(draw.base_key)
        if am.kind == "bed_confirmation":
            effects.append(_bed_confirmation(am, verdict))
        elif am.kind == "reserve_origin":
            effects.append(_reserve_origin(am, verdict))
        else:
            referenced = rules_index.get(am.rule)
            if referenced is None:
                effects.append(AmendmentEffect(
                    am.notice, am.draw, am.kind, accepted=False, impact=IMPACT_REJECTED,
                    detail=f"补证引用的规则 {am.rule} 不存在，不予采纳",
                ))
                continue
            effects.append(_past_policy(am, draw, referenced, rule_book))
    return effects


def _bed_confirmation(am: Amendment, verdict: UnitVerdict | None) -> AmendmentEffect:
    has_unpriced_bed = any(
        a.mandatory_bed_due > 0 for a in (verdict.assessments if verdict else ())
    )
    if not has_unpriced_bed:
        return AmendmentEffect(
            am.notice, am.draw, am.kind, accepted=False, impact=IMPACT_REJECTED,
            detail="该抽次不存在未计入展示价的强制加床，补证与证据不符，不予采纳",
        )
    clauses = tuple(sorted({
        f"{a.quote.quote}：展示价未含强制加床费 {a.mandatory_bed_due} 元，"
        "违反'展示价须含应付费用'条款"
        for a in verdict.assessments if a.mandatory_bed_due > 0
    }))
    return AmendmentEffect(
        am.notice, am.draw, am.kind, accepted=True, impact=IMPACT_STATISTICS,
        detail=("酒店确认强制加床需付费，展示价缺少必付费用，"
                "该机会不得计入履约分子；改变的是统计支撑，条款违反在原始复核中已成立"),
        clause_violations=clauses,
    )


def _reserve_origin(am: Amendment, verdict: UnitVerdict | None) -> AmendmentEffect:
    return AmendmentEffect(
        am.notice, am.draw, am.kind, accepted=True, impact=IMPACT_STATISTICS,
        detail=(
            "确认入口共享同一预留房量；联营联合口径下该机会只计一次，"
            f"关联抽次 {verdict.member_draws if verdict else am.draw}"
        ),
    )


def _past_policy(am: Amendment, draw: Draw, referenced,
                 rule_book: RuleBook) -> AmendmentEffect:
    """补录规则不能回溯解释当时的拒单。"""
    visible = rule_book.visible_on(referenced.room, referenced.hotel, draw.search_day)
    latest = rule_book.latest(referenced.room, referenced.hotel)
    if visible is None or latest is None or visible.revision == latest.revision:
        return AmendmentEffect(
            am.notice, am.draw, am.kind, accepted=False, impact=IMPACT_REJECTED,
            detail="搜索当日可见版本与现行版本一致，补证不产生改变",
        )
    detail = (
        f"搜索日 {draw.search_day} 仅可见 {visible.rule}（rev {visible.revision}，"
        f"登记日 {visible.documented}）；{latest.rule}（rev {latest.revision}，"
        f"登记日 {latest.documented}）在当时未登记。按搜索当日版本回看，"
        "原拒单/超龄判定维持不变；现行规则只能用于界定下一轮允许发布的范围，"
        "不能改写历史结论或原广告违反条款"
    )
    return AmendmentEffect(am.notice, am.draw, am.kind, accepted=False,
                           impact=IMPACT_FUTURE_SCOPE, detail=detail)
