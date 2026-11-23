"""CSV 资料装载与完整性校验（仅标准库）。

校验范围：表头、记录键唯一、外键关联、枚举值与基础数值约束。
校验失败抛出 :class:`DataContractError`，错误信息中给出全部问题，避免逐次往返。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .models import Amendment, Campaign, Draw, FrameStratum, InventoryCell, Quote, Review, RoomRule

TABLE_FIELDS: dict[str, list[str]] = {
    "campaigns": "ad channel pool running_from running_through arrival_lo arrival_hi max_ages max_price minimum joint_scope joint_minimum".split(),
    "room_rules": "rule room hotel revision valid_from documented max_adults max_children free_age max_age mandatory_bed_age bed_fee".split(),
    "frame": "stratum ad arrival_kind family_kind population planned_draws".split(),
    "draws": "draw stratum search_day arrival ages adults rooms availability_window repeat_of source".split(),
    "quotes": "quote draw pool room hotel arrival availability_window nightly_bundle mandatory_fee outcome bed_included".split(),
    "inventory": "pool arrival window rooms state".split(),
    "reviews": "review ad state term_scope decided_on".split(),
    "evidence_amendments": "notice draw kind rule received_on explicit_value".split(),
}

KEY_FIELDS: dict[str, list[str]] = {
    "campaigns": ["ad"],
    "room_rules": ["rule"],
    "frame": ["stratum"],
    "draws": ["draw"],
    "quotes": ["quote"],
    "inventory": ["pool", "arrival", "window"],
    "reviews": ["review"],
    "evidence_amendments": ["notice"],
}

OUTCOMES = frozenset({"bookable", "no_inventory", "timeout", "ineligible"})
REVIEW_STATES = frozenset({"approved", "candidate", "narrowed", "paused", "withdrawn"})
REVIEW_SCOPES = frozenset({"all", "weekday", "weekend", "small", "older"})
AMENDMENT_KINDS = frozenset({"bed_confirmation", "reserve_origin", "past_policy"})
AMENDMENT_VALUES = frozenset({"required", "pool_shared", "not_visible"})


class DataContractError(ValueError):
    """资料不符合约定时抛出。"""


@dataclass
class DataBundle:
    campaigns: dict[str, Campaign]
    room_rules: list[RoomRule]
    frame: dict[str, FrameStratum]
    draws: dict[str, Draw]
    quotes: list[Quote]
    inventory: dict[tuple[str, str, str], InventoryCell]
    reviews: list[Review]
    amendments: list[Amendment]

    @property
    def ads(self) -> list[str]:
        return list(self.campaigns)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != TABLE_FIELDS[path.stem]:
            raise DataContractError(
                f"{path.name} 表头不符：期望 {TABLE_FIELDS[path.stem]}，实际 {reader.fieldnames}"
            )
        rows = list(reader)
    if not rows:
        raise DataContractError(f"{path.name} 为空")
    for i, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise DataContractError(f"{path.name} 第 {i} 行存在未声明字段或缺列")
    return rows


def _int_or_none(value: str) -> int | None:
    return int(value) if value != "" else None


def load_bundle(data_dir: str | Path) -> DataBundle:
    data_dir = Path(data_dir)
    problems: list[str] = []
    raw: dict[str, list[dict[str, str]]] = {}
    for name in TABLE_FIELDS:
        path = data_dir / f"{name}.csv"
        if not path.exists():
            raise DataContractError(f"缺少资料文件 {path}")
        raw[name] = _read_rows(path)
        _check_unique(name, raw[name], problems)

    campaigns = {
        r["ad"]: Campaign(
            ad=r["ad"], channel=r["channel"], pool=r["pool"],
            running_from=r["running_from"], running_through=r["running_through"],
            arrival_lo=r["arrival_lo"], arrival_hi=r["arrival_hi"],
            max_ages=tuple(int(a) for a in r["max_ages"].split("|")),
            max_price=int(r["max_price"]), minimum=float(r["minimum"]),
            joint_scope=r["joint_scope"],
            joint_minimum=float(r["joint_minimum"]) if r["joint_minimum"] else None,
        )
        for r in raw["campaigns"]
    }
    room_rules = [
        RoomRule(
            rule=r["rule"], room=r["room"], hotel=r["hotel"], revision=int(r["revision"]),
            valid_from=r["valid_from"], documented=r["documented"],
            max_adults=int(r["max_adults"]), max_children=int(r["max_children"]),
            free_age=int(r["free_age"]), max_age=int(r["max_age"]),
            mandatory_bed_age=int(r["mandatory_bed_age"]), bed_fee=int(r["bed_fee"]),
        )
        for r in raw["room_rules"]
    ]
    frame = {
        r["stratum"]: FrameStratum(
            stratum=r["stratum"], ad=r["ad"], arrival_kind=r["arrival_kind"],
            family_kind=r["family_kind"], population=int(r["population"]),
            planned_draws=int(r["planned_draws"]),
        )
        for r in raw["frame"]
    }
    draws = {
        r["draw"]: Draw(
            draw=r["draw"], stratum=r["stratum"], search_day=r["search_day"],
            arrival=r["arrival"], ages=tuple(int(a) for a in r["ages"].split("|")),
            adults=int(r["adults"]), rooms=int(r["rooms"]),
            availability_window=r["availability_window"], repeat_of=r["repeat_of"],
            source=r["source"],
        )
        for r in raw["draws"]
    }
    quotes = [
        Quote(
            quote=r["quote"], draw=r["draw"], pool=r["pool"], room=r["room"],
            hotel=r["hotel"], arrival=r["arrival"], availability_window=r["availability_window"],
            nightly_bundle=_int_or_none(r["nightly_bundle"]),
            mandatory_fee=_int_or_none(r["mandatory_fee"]),
            outcome=r["outcome"], bed_included=r["bed_included"] == "yes",
        )
        for r in raw["quotes"]
    ]
    inventory = {
        (r["pool"], r["arrival"], r["window"]): InventoryCell(
            pool=r["pool"], arrival=r["arrival"], window=r["window"],
            rooms=int(r["rooms"]), state=r["state"],
        )
        for r in raw["inventory"]
    }
    reviews = [
        Review(review=r["review"], ad=r["ad"], state=r["state"],
               term_scope=r["term_scope"], decided_on=r["decided_on"])
        for r in raw["reviews"]
    ]
    amendments = [
        Amendment(notice=r["notice"], draw=r["draw"], kind=r["kind"], rule=r["rule"],
                  received_on=r["received_on"], explicit_value=r["explicit_value"])
        for r in raw["evidence_amendments"]
    ]

    _cross_checks(problems, campaigns, frame, draws, quotes, inventory, reviews,
                  amendments, room_rules)
    if problems:
        raise DataContractError("资料关联校验失败：\n- " + "\n- ".join(problems))
    return DataBundle(campaigns, room_rules, frame, draws, quotes, inventory, reviews, amendments)


def _check_unique(name: str, rows: list[dict[str, str]], problems: list[str]) -> None:
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(row[f] for f in KEY_FIELDS[name])
        if not all(key):
            problems.append(f"{name} 存在空记录键 {key}")
        elif key in seen:
            problems.append(f"{name} 记录键重复 {key}")
        else:
            seen.add(key)


def _cross_checks(problems, campaigns, frame, draws, quotes, inventory, reviews,
                  amendments, room_rules) -> None:
    for f in frame.values():
        if f.ad not in campaigns:
            problems.append(f"frame {f.stratum} 引用未知广告 {f.ad}")
    strata = set(frame)
    for d in draws.values():
        if d.stratum not in strata:
            problems.append(f"draws {d.draw} 引用未知分层 {d.stratum}")
        if d.repeat_of and d.repeat_of not in draws:
            problems.append(f"draws {d.draw} 的 repeat_of 指向不存在的抽次 {d.repeat_of}")
        if d.repeat_of and d.source != "repeat":
            problems.append(f"draws {d.draw} 是重复观测但 source={d.source}")
    quote_draws = set()
    for q in quotes:
        quote_draws.add(q.draw)
        if q.draw not in draws:
            problems.append(f"quotes {q.quote} 引用未知抽次 {q.draw}")
        cell = inventory.get((q.pool, q.arrival, q.availability_window))
        if cell is None:
            problems.append(
                f"quotes {q.quote} 的房池键 ({q.pool},{q.arrival},{q.availability_window}) 在 inventory 缺失"
            )
        if q.outcome not in OUTCOMES:
            problems.append(f"quotes {q.quote} outcome 非法 {q.outcome}")
        if q.outcome == "bookable" and (q.nightly_bundle is None or q.mandatory_fee is None):
            problems.append(f"quotes {q.quote} 标记 bookable 但缺少价格字段")
        if q.outcome != "bookable" and q.nightly_bundle is not None:
            problems.append(f"quotes {q.quote} 非 bookable 却带价格")
    missing_quote = sorted(set(draws) - quote_draws)
    if missing_quote:
        problems.append(f"以下抽次缺少报价记录：{missing_quote}")
    # 广告房池与报价房池必须一致（房池是地区/库存口径的载体）
    draw_ad = {}
    for d in draws.values():
        f = frame.get(d.stratum)
        if f is not None and f.ad in campaigns:
            draw_ad[d.draw] = campaigns[f.ad]
    for q in quotes:
        campaign = draw_ad.get(q.draw)
        if campaign is not None and q.pool != campaign.pool:
            problems.append(
                f"quotes {q.quote} 房池 {q.pool} 与广告 {campaign.ad} "
                f"声明房池 {campaign.pool} 不一致"
            )
    # 报价涉及的房型在搜索当日必须存在至少一条已登记规则（规则版本选择在引擎中完成）
    rule_rooms = {(r.room, r.hotel) for r in room_rules}
    for q in quotes:
        if (q.room, q.hotel) not in rule_rooms:
            problems.append(
                f"quotes {q.quote} 引用的房型 {q.room}/{q.hotel} 在 room_rules 中无任何版本"
            )
    for cell in inventory.values():
        if cell.state not in {"open", "closed"}:
            problems.append(f"inventory 状态非法 {cell.state}")
        if cell.state == "closed" and cell.rooms != 0:
            problems.append(f"inventory {cell.pool}/{cell.arrival}/{cell.window} 关闭但房量非 0")
        if cell.state == "open" and cell.rooms <= 0:
            problems.append(f"inventory {cell.pool}/{cell.arrival}/{cell.window} 开放但房量为 0")
    for rv in reviews:
        if rv.ad not in campaigns:
            problems.append(f"reviews {rv.review} 引用未知广告 {rv.ad}")
        if rv.state not in REVIEW_STATES:
            problems.append(f"reviews {rv.review} state 非法 {rv.state}")
        if rv.term_scope not in REVIEW_SCOPES:
            problems.append(f"reviews {rv.review} term_scope 非法 {rv.term_scope}")
    for am in amendments:
        if am.draw not in draws:
            problems.append(f"evidence_amendments {am.notice} 引用未知抽次 {am.draw}")
        if am.kind not in AMENDMENT_KINDS:
            problems.append(f"evidence_amendments {am.notice} kind 非法 {am.kind}")
        if am.explicit_value not in AMENDMENT_VALUES:
            problems.append(f"evidence_amendments {am.notice} explicit_value 非法 {am.explicit_value}")
