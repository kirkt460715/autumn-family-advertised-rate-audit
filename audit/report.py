"""命令行报告：人读文本与机器读 JSON 两种输出。"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .estimation import RateEstimate
from .pipeline import AuditResult, run_audit


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _est_line(label: str, est: RateEstimate) -> list[str]:
    commit = f"承诺 {_pct(est.commitment)}" if est.commitment is not None else "无比例承诺"
    decision_cn = {
        "met": "达标", "not_met": "不达标", "indeterminate": "证据不足",
        "no_commitment": "无承诺",
    }[est.decision]
    return [
        f"  {label}",
        f"    结论：{decision_cn}（{commit}）  点估计 {_pct(est.point)}  "
        f"抽样95%区间 [{_pct(est.sampling_ci[0])}, {_pct(est.sampling_ci[1])}]  "
        f"含不可归类外包络 [{_pct(est.interval[0])}, {_pct(est.interval[1])}]",
        f"    覆盖人口 {est.population}；已分类权重 {est.classified_weight}；"
        f"无法归类权重 {est.unclassified_weight}（占比 {_pct(est.nonresponse_share)}）；"
        f"履约权重 {est.fulfilled_weight}",
    ]


def render_text(result: AuditResult) -> str:
    lines: list[str] = []
    lines.append("亲子住宿广告价可订性复核报告")
    lines.append("=" * 60)
    lines.append("证据计数（基础抽样单位，重复观测已折叠）："
                 + "，".join(f"{k}={v}" for k, v in sorted(result.verdict_counts().items())))
    lines.append("")

    lines.append("一、抽样计划对账（分层权重 / 重复抽取 / 可验证结果 / 无法归类）")
    lines.append("-" * 60)
    for r in result.reconciliation:
        lines.append(
            f"  {r.stratum} {r.ad}/{r.arrival_kind}/{r.family_kind} "
            f"人口={r.population} 计划={r.planned_draws} 实际基础抽次={r.base_units} "
            f"重复观测={r.repeat_observations} 可验证={r.classified} "
            f"无法归类={r.unclassified} 超范围={r.out_of_scope} 层权重={r.weight:.2f}"
        )
    lines.append("")

    lines.append("二、单广告承诺兑现")
    lines.append("-" * 60)
    for ad, est in result.ad_estimates.items():
        lines.extend(_est_line(f"广告 {ad}", est))
        for dim, label in (("arrival_kind", "入住分层"), ("family_kind", "团型")):
            decision_cn = {
                "met": "达标", "not_met": "不达标",
                "indeterminate": "证据不足", "no_commitment": "无承诺",
            }
            for sub in result.ad_breakdowns[ad][dim]:
                lines.append(
                    f"    - {label} {sub.label.split('=', 1)[1]}：点估计 {_pct(sub.point)} "
                    f"区间 [{_pct(sub.interval[0])}, {_pct(sub.interval[1])}] "
                    f"-> {decision_cn[sub.decision]}"
                )
    lines.append("")

    lines.append("三、联营联合覆盖（同一房池、互不重复的可售机会）")
    lines.append("-" * 60)
    if result.joint:
        j = result.joint
        lines.extend(_est_line(f"联营 {j.scope}（房池 {j.pool}，折叠跨入口重复 {j.duplicates_collapsed} 个）",
                               j.estimate))
        for ad, est in j.member_estimates.items():
            lines.append(f"    - 成员 {ad} 单项：点估计 {_pct(est.point)} "
                         f"区间 [{_pct(est.interval[0])}, {_pct(est.interval[1])}]")
        jr = result.joint_recommendation
        lines.append(f"    联合质检建议：{jr.decision} —— {jr.rationale}")
    lines.append("")

    lines.append("四、运营质检建议")
    lines.append("-" * 60)
    for ad, rec in result.recommendations.items():
        lines.append(f"  {ad}: {rec.decision} —— {rec.rationale}")
        if rec.supported_scopes:
            lines.append(f"    受支持可保留范围：{', '.join(rec.supported_scopes)}")
        for conflict in rec.conflicts_with_record:
            lines.append(f"    [与已登记决定冲突] {conflict}")
    lines.append("")

    lines.append("五、后送补证处理（统计支撑 / 条款违反 / 下一轮范围）")
    lines.append("-" * 60)
    for eff in result.amendment_effects:
        flag = "采纳" if eff.accepted else "驳回"
        lines.append(f"  {eff.notice}（{eff.kind}，{flag}，影响={eff.impact}）：{eff.detail}")
        for clause in eff.clause_violations:
            lines.append(f"      条款违反：{clause}")
    return "\n".join(lines)


def _to_jsonable(obj):
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "value"):
        return obj.value
    return obj


def render_json(result: AuditResult) -> str:
    payload = {
        "verdict_counts": result.verdict_counts(),
        "reconciliation": _to_jsonable(result.reconciliation),
        "ad_estimates": {ad: _to_jsonable(est) for ad, est in result.ad_estimates.items()},
        "ad_breakdowns": _to_jsonable(result.ad_breakdowns),
        "joint": _to_jsonable(result.joint) if result.joint else None,
        "recommendations": _to_jsonable(result.recommendations),
        "joint_recommendation": _to_jsonable(result.joint_recommendation),
        "amendment_effects": _to_jsonable(result.amendment_effects),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="亲子住宿广告价可订性复核")
    parser.add_argument("--data", default="data", help="CSV 资料目录（默认 data）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非文本报告")
    args = parser.parse_args(argv)
    result = run_audit(Path(args.data))
    print(render_json(result) if args.json else render_text(result))
    return 0
