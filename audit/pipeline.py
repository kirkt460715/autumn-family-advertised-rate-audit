"""全流程编排：资料装载 -> 规则复核 -> 单位折叠 -> 分层估计 -> 联营重判 -> 补证与质检。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .amendments import AmendmentEffect, process_amendments
from .estimation import (
    JointEstimate,
    ad_estimate,
    breakdown_estimates,
    joint_estimate,
)
from .io_csv import DataBundle, load_bundle
from .models import EvidenceKind
from .review import (
    AdRecommendation,
    JointRecommendation,
    recommend_for_ad,
    recommend_joint,
)
from .rules import RuleBook
from .units import UnitBuilder


@dataclass
class ReconciliationRow:
    """抽样计划与实际证据的对账行。"""

    stratum: str
    ad: str
    arrival_kind: str
    family_kind: str
    population: int
    planned_draws: int
    base_units: int
    repeat_observations: int
    classified: int
    unclassified: int
    out_of_scope: int
    weight: float


@dataclass
class AuditResult:
    bundle: DataBundle
    verdicts: list[UnitVerdict]
    ad_estimates: dict[str, RateEstimate]
    ad_breakdowns: dict[str, dict[str, list[RateEstimate]]]
    joint: JointEstimate | None
    recommendations: dict[str, AdRecommendation]
    joint_recommendation: JointRecommendation | None
    amendment_effects: list[AmendmentEffect]
    reconciliation: list[ReconciliationRow]

    def verdict_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for u in self.verdicts:
            counts[u.kind.value] = counts.get(u.kind.value, 0) + 1
        return counts


def run_audit(data_dir: str | Path) -> AuditResult:
    bundle = load_bundle(data_dir)
    rule_book = RuleBook(bundle.room_rules)
    builder = UnitBuilder(
        bundle.campaigns, bundle.frame, bundle.draws, bundle.quotes,
        rule_book, bundle.amendments,
    )
    verdicts = builder.build()

    ad_estimates: dict[str, RateEstimate] = {}
    ad_breakdowns: dict[str, dict[str, list[RateEstimate]]] = {}
    frame_rows = list(bundle.frame.values())
    for ad, campaign in bundle.campaigns.items():
        ad_estimates[ad] = ad_estimate(campaign, verdicts, frame_rows)
        ad_breakdowns[ad] = {
            dim: breakdown_estimates(campaign, verdicts, frame_rows, dim)
            for dim in ("arrival_kind", "family_kind")
        }

    joint = joint_estimate(bundle.campaigns, verdicts, frame_rows)

    recorded_by_ad = {rv.ad: rv for rv in bundle.reviews}
    recommendations = {
        ad: recommend_for_ad(
            campaign, ad_estimates[ad], verdicts, frame_rows,
            recorded_by_ad.get(ad),
        )
        for ad, campaign in bundle.campaigns.items()
    }
    joint_rec = recommend_joint(joint, recommendations) if joint else None
    effects = process_amendments(bundle.amendments, bundle.draws, verdicts, rule_book)
    reconciliation = _reconciliation(bundle, verdicts)
    return AuditResult(
        bundle=bundle, verdicts=verdicts, ad_estimates=ad_estimates,
        ad_breakdowns=ad_breakdowns, joint=joint,
        recommendations=recommendations, joint_recommendation=joint_rec,
        amendment_effects=effects, reconciliation=reconciliation,
    )


def _reconciliation(bundle: DataBundle, verdicts: list[UnitVerdict]) -> list[ReconciliationRow]:
    bases_per_stratum: dict[str, list[UnitVerdict]] = {}
    for u in verdicts:
        bases_per_stratum.setdefault(u.stratum, []).append(u)
    repeats_per_stratum: dict[str, int] = {}
    for draw in bundle.draws.values():
        if draw.is_repeat:
            repeats_per_stratum[draw.stratum] = repeats_per_stratum.get(draw.stratum, 0) + 1

    rows: list[ReconciliationRow] = []
    for sid in sorted(bundle.frame):
        f = bundle.frame[sid]
        units = bases_per_stratum.get(sid, [])
        n = len(units) or 1
        rows.append(ReconciliationRow(
            stratum=sid, ad=f.ad, arrival_kind=f.arrival_kind, family_kind=f.family_kind,
            population=f.population, planned_draws=f.planned_draws,
            base_units=len(units),
            repeat_observations=repeats_per_stratum.get(sid, 0),
            classified=sum(1 for u in units if u.classified and u.in_scope),
            unclassified=sum(1 for u in units
                             if u.kind is EvidenceKind.TIMEOUT),
            out_of_scope=sum(1 for u in units
                             if u.kind is EvidenceKind.OUT_OF_SCOPE),
            weight=f.population / n,
        ))
    return rows
