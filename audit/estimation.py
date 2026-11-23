"""分层加权估计、置信区间、不可归类区间与联营联合覆盖。

估计口径：

- 抽样单位是折叠重复观测后的基础抽次；重复观察不增加权重（frame 权重落在基础抽次上）。
- 层内权重 ``w_h = population_h / 实际基础抽次数``，计划抽次与实际抽次同时报告以便对账。
- 比例估计采用分层公式，95% 区间用正态近似；层内零方差时保守取 0。
- timeout（接口未返回）是无法归类的搜索，不计入分子也不计入已分类分母；
  另用"全部不可归类均履约 / 均不履约"给出非应答边界，与抽样区间取外包络。
- 联营联合口径下，同一房池的同一机会只计一次，覆盖比例建立在互不重复的可售机会上。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import EvidenceKind, UnitVerdict
from .units import OpportunityKey, opportunity_key

Z_95 = 1.959963984540054


@dataclass
class StratumStats:
    stratum: str
    arrival_kind: str
    family_kind: str
    population: int
    planned_draws: int
    observed_units: int
    counts: dict[str, int]
    weight: float


@dataclass
class RateEstimate:
    """一个总体口径下的承诺兑现率估计。"""

    label: str
    population: int
    observed_units: int
    classified_weight: float
    unclassified_weight: float
    fulfilled_weight: float
    point: float                      # 已分类单位上的加权履约率
    sampling_ci: tuple[float, float]
    nonresponse_bounds: tuple[float, float]
    interval: tuple[float, float]    # 抽样区间与非应答边界的外包络
    commitment: float | None
    decision: str                     # met / not_met / indeterminate
    strata: list[StratumStats] = field(default_factory=list)

    @property
    def nonresponse_share(self) -> float:
        base = self.classified_weight + self.unclassified_weight
        return self.unclassified_weight / base if base else 0.0


def _strata_stats(units: list[UnitVerdict], populations: dict[str, int],
                  planned: dict[str, int], meta: dict[str, tuple[str, str]]
                  ) -> list[StratumStats]:
    grouped: dict[str, list[UnitVerdict]] = {}
    for u in units:
        grouped.setdefault(u.stratum, []).append(u)
    out: list[StratumStats] = []
    for sid in sorted(grouped):
        rows = grouped[sid]
        counts: dict[str, int] = {}
        for u in rows:
            counts[u.kind.value] = counts.get(u.kind.value, 0) + 1
        pop = populations.get(sid, sum(1 for _ in rows))
        out.append(StratumStats(
            stratum=sid, arrival_kind=meta[sid][0], family_kind=meta[sid][1],
            population=pop, planned_draws=planned.get(sid, len(rows)),
            observed_units=len(rows), counts=counts, weight=pop / len(rows),
        ))
    return out


def _weighted(strata: list[StratumStats], units: list[UnitVerdict]):
    weight_by_unit: dict[str, float] = {}
    by_stratum: dict[str, list[UnitVerdict]] = {}
    for u in units:
        by_stratum.setdefault(u.stratum, []).append(u)
    for s in strata:
        for u in by_stratum[s.stratum]:
            weight_by_unit[u.base_key] = s.weight

    fulfilled = classified = unclassified = 0.0
    for u in units:
        w = weight_by_unit[u.base_key]
        if u.kind is EvidenceKind.OUT_OF_SCOPE:
            continue
        if u.kind is EvidenceKind.TIMEOUT:
            unclassified += w
        else:
            classified += w
            if u.kind is EvidenceKind.FULFILLED:
                fulfilled += w
    return weight_by_unit, fulfilled, classified, unclassified


def _stratified_variance(strata: list[StratumStats], units: list[UnitVerdict],
                         weight_by_unit: dict[str, float]) -> float:
    """分层比例方差：sum W_h^2 * (1-f_h) * p_h(1-p_h)/(n_h-1)。"""
    total_pop = sum(s.population for s in strata)
    if total_pop == 0:
        return 0.0
    grouped: dict[str, list[UnitVerdict]] = {}
    for u in units:
        grouped.setdefault(u.stratum, []).append(u)
    variance = 0.0
    for s in strata:
        rows = [u for u in grouped.get(s.stratum, [])
                if u.kind is not EvidenceKind.OUT_OF_SCOPE
                and u.kind is not EvidenceKind.TIMEOUT]
        n_h = len(rows)
        if n_h <= 1:
            continue
        p_h = sum(1 for u in rows if u.kind is EvidenceKind.FULFILLED) / n_h
        f_h = s.observed_units / s.population if s.population else 1.0
        w_h = s.population / total_pop
        variance += w_h ** 2 * (1 - f_h) * p_h * (1 - p_h) / (n_h - 1)
    return variance


def estimate_rate(label: str, units: list[UnitVerdict], populations: dict[str, int],
                  planned: dict[str, int], meta: dict[str, tuple[str, str]],
                  commitment: float | None = None) -> RateEstimate:
    strata = _strata_stats(units, populations, planned, meta)
    weights, fulfilled, classified, unclassified = _weighted(strata, units)
    base = classified + unclassified
    point = fulfilled / classified if classified else 0.0
    variance = _stratified_variance(strata, units, weights)
    half = Z_95 * math.sqrt(variance)
    sampling_ci = (max(0.0, point - half), min(1.0, point + half))
    if base:
        nr_lo = fulfilled / base
        nr_hi = (fulfilled + unclassified) / base
    else:
        nr_lo = nr_hi = point
    interval = (min(sampling_ci[0], nr_lo), max(sampling_ci[1], nr_hi))
    decision = _decide(interval, commitment)
    return RateEstimate(
        label=label, population=round(base), observed_units=len(units),
        classified_weight=round(classified, 2), unclassified_weight=round(unclassified, 2),
        fulfilled_weight=round(fulfilled, 2), point=point,
        sampling_ci=sampling_ci, nonresponse_bounds=(nr_lo, nr_hi),
        interval=interval, commitment=commitment, decision=decision, strata=strata,
    )


def _decide(interval: tuple[float, float], commitment: float | None) -> str:
    if commitment is None:
        return "no_commitment"
    lo, hi = interval
    if lo >= commitment:
        return "met"
    if hi < commitment:
        return "not_met"
    return "indeterminate"


# --------------------------------------------------------------------------- #
# 单广告口径
# --------------------------------------------------------------------------- #

def ad_estimate(campaign: Campaign, units: list[UnitVerdict], frame_rows) -> RateEstimate:
    mine = [u for u in units if u.ad == campaign.ad]
    populations = {f.stratum: f.population for f in frame_rows if f.ad == campaign.ad}
    planned = {f.stratum: f.planned_draws for f in frame_rows if f.ad == campaign.ad}
    meta = {f.stratum: (f.arrival_kind, f.family_kind)
            for f in frame_rows if f.ad == campaign.ad}
    return estimate_rate(f"广告 {campaign.ad}（{campaign.channel}）", mine,
                         populations, planned, meta, campaign.minimum)


def breakdown_estimates(campaign: Campaign, units: list[UnitVerdict], frame_rows,
                        dimension: str) -> list[RateEstimate]:
    """按入住分层（weekday/weekend）或团型（small/older）拆分。"""
    idx = "arrival_kind" if dimension == "arrival_kind" else "family_kind"
    mine = [u for u in units if u.ad == campaign.ad]
    values = sorted({getattr(u, dimension) for u in mine})
    out: list[RateEstimate] = []
    for value in values:
        sub = [u for u in mine if getattr(u, dimension) == value]
        populations = {f.stratum: f.population for f in frame_rows
                       if f.ad == campaign.ad and getattr(f, idx) == value}
        planned = {f.stratum: f.planned_draws for f in frame_rows
                   if f.ad == campaign.ad and getattr(f, idx) == value}
        meta = {f.stratum: (f.arrival_kind, f.family_kind)
                for f in frame_rows if f.ad == campaign.ad and getattr(f, idx) == value}
        out.append(estimate_rate(f"{campaign.ad} / {dimension}={value}", sub,
                                 populations, planned, meta, campaign.minimum))
    return out


# --------------------------------------------------------------------------- #
# 联营联合口径
# --------------------------------------------------------------------------- #

@dataclass
class JointEstimate:
    scope: str
    ads: list[str]
    pool: str
    estimate: RateEstimate
    member_estimates: dict[str, RateEstimate]
    duplicates_collapsed: int


def joint_estimate(campaigns: dict[str, Campaign], units: list[UnitVerdict],
                   frame_rows) -> JointEstimate | None:
    """在同一组互不重复的可售机会上核对联合覆盖承诺。"""
    scopes = {c.joint_scope: c for c in campaigns.values() if c.has_joint_promise}
    if not scopes:
        return None
    scope, anchor = next(iter(scopes.items()))
    members = [c for c in campaigns.values() if c.joint_scope == scope]
    member_ads = {c.ad for c in members}
    pool = anchor.pool
    if any(c.pool != pool for c in members):
        raise ValueError(f"联营 {scope} 成员广告未共用同一房池")

    seen: dict[OpportunityKey, UnitVerdict] = {}
    duplicates = 0
    for u in units:
        if u.ad not in member_ads:
            continue
        key = opportunity_key(pool, _draw_like(u))
        if key in seen:
            duplicates += 1
            seen[key] = _merge_opportunity(seen[key], u)
        else:
            seen[key] = u
    union_units = sorted(seen.values(), key=lambda u: u.base_key)

    # 联合总体：同一维度上取成员广告层人口的并集上界（max），避免重复计人口
    pop_by_dim: dict[tuple[str, str], int] = {}
    planned_by_dim: dict[tuple[str, str], int] = {}
    for f in frame_rows:
        if f.ad not in member_ads:
            continue
        dim = (f.arrival_kind, f.family_kind)
        pop_by_dim[dim] = max(pop_by_dim.get(dim, 0), f.population)
        planned_by_dim[dim] = max(planned_by_dim.get(dim, 0), f.planned_draws)

    # 给去重后的单位挂联合分层人口
    union_strata: dict[str, _JointStratum] = {}
    for u in union_units:
        sid = f"J:{u.arrival_kind}:{u.family_kind}"
        dim = (u.arrival_kind, u.family_kind)
        if sid not in union_strata:
            union_strata[sid] = _JointStratum(
                sid, u.arrival_kind, u.family_kind,
                pop_by_dim.get(dim, 0), planned_by_dim.get(dim, 0),
            )
        union_strata[sid].units.append(u)
    populations = {s.name: s.population for s in union_strata.values()}
    planned = {s.name: s.planned for s in union_strata.values()}
    meta = {s.name: (s.arrival_kind, s.family_kind) for s in union_strata.values()}
    remapped = [_restratify(u, f"J:{u.arrival_kind}:{u.family_kind}") for u in union_units]

    estimate = estimate_rate(
        f"联营 {scope} 联合覆盖（房池 {pool}，去重后机会）", remapped,
        populations, planned, meta, anchor.joint_minimum,
    )
    member_estimates = {
        c.ad: ad_estimate(c, [u for u in units if u.ad == c.ad], frame_rows)
        for c in members
    }
    return JointEstimate(scope, [c.ad for c in members], pool, estimate,
                         member_estimates, duplicates)


@dataclass
class _JointStratum:
    name: str
    arrival_kind: str
    family_kind: str
    population: int
    planned: int
    units: list = field(default_factory=list)


def _draw_like(u: UnitVerdict):
    """从单位判定重建去重键所需的抽次形状（避免上层再持有 Draw）。"""
    class _Shape:
        pass
    shape = _Shape()
    shape.arrival = u.arrival
    shape.availability_window = u.window
    shape.ages = u.ages
    shape.adults = u.adults
    shape.rooms = u.rooms
    return shape


def _merge_opportunity(existing: UnitVerdict, other: UnitVerdict) -> UnitVerdict:
    """同一机会在两个入口被观察到时，保留更强证据与最低含费价。"""
    order = [EvidenceKind.FULFILLED, EvidenceKind.PRICE_EXCEEDED,
             EvidenceKind.INELIGIBLE, EvidenceKind.NO_INVENTORY,
             EvidenceKind.TIMEOUT, EvidenceKind.OUT_OF_SCOPE]
    rank = {k: i for i, k in enumerate(order)}
    chosen = existing if rank[existing.kind] <= rank[other.kind] else other
    payable_candidates = [p for p in (existing.payable, other.payable) if p is not None]
    payable = min(payable_candidates) if payable_candidates else None
    return UnitVerdict(
        base_key=chosen.base_key, ad=f"{existing.ad}+{other.ad}",
        stratum=chosen.stratum, arrival_kind=chosen.arrival_kind,
        family_kind=chosen.family_kind, arrival=chosen.arrival,
        search_day=chosen.search_day, ages=chosen.ages, adults=chosen.adults,
        rooms=chosen.rooms, pool=chosen.pool, window=chosen.window,
        member_draws=tuple(sorted(set(existing.member_draws + other.member_draws))),
        kind=chosen.kind, reason=chosen.reason, payable=payable,
        assessments=existing.assessments + other.assessments,
        amended_notices=tuple(sorted(set(existing.amended_notices + other.amended_notices))),
    )


def _restratify(u: UnitVerdict, stratum: str) -> UnitVerdict:
    import dataclasses
    return dataclasses.replace(u, stratum=stratum)
