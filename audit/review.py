"""运营质检：保留承诺、缩窄、暂缓、下架建议，以及联营缩窄后的联动重判。

建议规则（以含非应答边界的履约区间对照承诺比例）：

- ``met``        -> retain（保留承诺）
- ``indeterminate`` -> pause（证据不足以确定是否达标，暂缓补搜）
- ``not_met``    -> 有受支持的子人群/时段可缩窄则 narrow，否则 withdraw（下架）

缩窄一条联合广告后，必须在同一组互不重复的可售机会上重算联合覆盖，
并复核共用库存支持的其余广告；只改页面措辞不自动恢复上线。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .estimation import JointEstimate, RateEstimate, breakdown_estimates
from .models import Campaign, UnitVerdict

RETAIN = "retain"
NARROW = "narrow"
PAUSE = "pause"
WITHDRAW = "withdraw"


@dataclass
class AdRecommendation:
    ad: str
    decision: str
    rationale: str
    supported_scopes: list[str] = field(default_factory=list)
    estimate: RateEstimate | None = None
    recorded_review: Review | None = None
    conflicts_with_record: list[str] = field(default_factory=list)


@dataclass
class JointRecommendation:
    scope: str
    decision: str
    rationale: str
    estimate: RateEstimate
    member_decisions: dict[str, str]


def recommend_for_ad(campaign: Campaign, estimate: RateEstimate,
                     units: list[UnitVerdict], frame_rows,
                     recorded: Review | None) -> AdRecommendation:
    mine = [u for u in units if u.ad == campaign.ad]
    supported: list[str] = []
    sub_estimates: dict[str, RateEstimate] = {}
    for dim in ("arrival_kind", "family_kind"):
        for est in breakdown_estimates(campaign, mine, frame_rows, dim):
            sub_estimates[est.label] = est
            if est.decision == "met":
                supported.append(est.label.split("=", 1)[1])

    if estimate.decision == "met":
        decision, rationale = RETAIN, "履约区间下界不低于承诺比例，证据支持保留原承诺"
    elif estimate.decision == "indeterminate":
        decision, rationale = PAUSE, (
            f"履约区间 {_pct(estimate.interval)} 跨越承诺 {campaign.minimum:.0%}，"
            "证据不足以确定是否达标，暂缓并对 timeout 抽次补搜"
        )
    else:
        if supported:
            decision = NARROW
            rationale = (
                f"履约区间上界 {estimate.interval[1]:.1%} 仍低于承诺 {campaign.minimum:.0%}；"
                f"仅以下受支持范围可保留：{', '.join(sorted(set(supported)))}"
            )
        else:
            decision = WITHDRAW
            rationale = (
                f"履约区间上界 {estimate.interval[1]:.1%} 低于承诺 {campaign.minimum:.0%}，"
                "且无任何子人群/时段达标，建议下架"
            )

    rec = AdRecommendation(campaign.ad, decision, rationale,
                           sorted(set(supported)), estimate, recorded)
    if recorded is not None:
        rec.conflicts_with_record = _check_record(
            campaign, recorded, estimate, decision, sub_estimates,
        )
    return rec


def _check_record(campaign: Campaign, recorded: Review,
                  estimate: RateEstimate, decision: str,
                  sub_estimates: dict[str, RateEstimate]) -> list[str]:
    conflicts: list[str] = []
    if recorded.state == "approved" and decision in {WITHDRAW, NARROW, PAUSE}:
        conflicts.append(
            f"已登记 {recorded.review}=approved（{recorded.term_scope}），"
            f"但复核建议 {decision}，原核准缺乏当前证据支撑"
        )
    if recorded.state in {"candidate", "narrowed"} and recorded.term_scope != "all":
        # 提案缩窄到某范围时，该范围必须有独立达标的子区间估计
        scope_estimates = [
            est for label, est in sub_estimates.items()
            if label.endswith(f"={recorded.term_scope}")
        ]
        scope_ok = bool(scope_estimates) and all(
            est.decision == "met" for est in scope_estimates
        )
        if not scope_ok:
            conflicts.append(
                f"提案缩窄至 {recorded.term_scope}，但该范围的独立估计未达承诺"
                "（证据不足或不达标）；不得只改页面措辞后上线，需重新核验后再决定"
            )
    if recorded.state == "withdrawn" and decision == RETAIN:
        conflicts.append(
            f"已登记下架 {recorded.review}，但当前估计支持保留；需走重新发布流程，"
            "不能自动恢复上线"
        )
    return conflicts


def recommend_joint(joint: JointEstimate,
                    ad_recs: dict[str, AdRecommendation]) -> JointRecommendation:
    est = joint.estimate
    member_decisions = {ad: ad_recs[ad].decision for ad in joint.ads}
    if est.decision == "met":
        decision, rationale = RETAIN, (
            f"联合履约区间下界 {est.interval[0]:.1%} 不低于联合承诺 "
            f"{est.commitment:.0%}，共享房池下的去重机会支持联合宣传"
        )
    elif est.decision == "indeterminate":
        decision, rationale = PAUSE, (
            f"联合履约区间 {_pct(est.interval)} 跨越承诺 {est.commitment:.0%}，"
            "联合宣传暂缓；缩窄任一成员广告后须重算本区间"
        )
    else:
        narrowed = [ad for ad, d in member_decisions.items() if d == NARROW]
        decision = NARROW if narrowed else WITHDRAW
        rationale = (
            f"联合履约区间上界 {est.interval[1]:.1%} 低于联合承诺 {est.commitment:.0%}；"
            f"成员判定 {member_decisions}。缩窄后须在同一组去重机会上重判，"
            "不得把仅一个家庭能订的房按两个入口各计一次"
        )
    return JointRecommendation(joint.scope, decision, rationale, est, member_decisions)


def reevaluate_after_narrow(scope: str, campaigns: dict[str, Campaign],
                            units: list[UnitVerdict], frame_rows,
                            joint_before: JointEstimate | None) -> dict[str, str]:
    """缩窄联合广告后的联动重判说明。

    返回受影响广告 -> 必须重新核验的事项。实际重算由 CLI 以新 term_scope 重新跑全流程，
    这里给出依赖关系，防止只改页面措辞便自动恢复上线。
    """
    if joint_before is None:
        return {}
    affected: dict[str, str] = {}
    for ad in joint_before.ads:
        affected[ad] = (
            f"共用房池 {joint_before.pool}：联合范围 {scope} 缩窄后，"
            "需在互不重复的可售机会上重算单项 minimum 与 joint_minimum，"
            "重判通过前不得恢复联合宣传"
        )
    return affected


def _pct(interval: tuple[float, float]) -> str:
    return f"[{interval[0]:.1%}, {interval[1]:.1%}]"
