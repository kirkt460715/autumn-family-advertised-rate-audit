"""复核领域的不可变数据模型。

空字符串统一保留为 ``""``，含义由各表约定决定；日期与时刻保留 ISO 字符串，
比较依赖 ISO 格式天然的字典序（资料约定固定为年-月-日 / 年-月-日T时）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EvidenceKind(str, Enum):
    """证据分级。不同证据不可互相顶替。"""

    FULFILLED = "fulfilled"          # 含应付费用且整户可接纳、价格不超承诺
    PRICE_EXCEEDED = "price_exceeded"  # 明确搜到了偏高价（可订但贵于承诺）
    INELIGIBLE = "ineligible"        # 酒店/房型规则拒绝该家庭组合
    NO_INVENTORY = "no_inventory"    # 已查实的库存约束（房池关闭/房量为 0）
    TIMEOUT = "timeout"              # 接口未返回，无可用核验信息
    OUT_OF_SCOPE = "out_of_scope"    # 搜索条件超出广告承诺覆盖范围


# 可判为"非履约"的硬证据；timeout 不属于硬证据
HARD_EVIDENCE = frozenset(
    {
        EvidenceKind.PRICE_EXCEEDED,
        EvidenceKind.INELIGIBLE,
        EvidenceKind.NO_INVENTORY,
        EvidenceKind.OUT_OF_SCOPE,
    }
)


@dataclass(frozen=True)
class Campaign:
    ad: str
    channel: str
    pool: str
    running_from: str
    running_through: str
    arrival_lo: str
    arrival_hi: str
    max_ages: tuple[int, ...]
    max_price: int
    minimum: float
    joint_scope: str
    joint_minimum: float | None

    @property
    def has_joint_promise(self) -> bool:
        return bool(self.joint_scope)


@dataclass(frozen=True)
class RoomRule:
    rule: str
    room: str
    hotel: str
    revision: int
    valid_from: str
    documented: str
    max_adults: int
    max_children: int
    free_age: int
    max_age: int
    mandatory_bed_age: int
    bed_fee: int


@dataclass(frozen=True)
class FrameStratum:
    stratum: str
    ad: str
    arrival_kind: str
    family_kind: str
    population: int
    planned_draws: int


@dataclass(frozen=True)
class Draw:
    draw: str
    stratum: str
    search_day: str
    arrival: str
    ages: tuple[int, ...]
    adults: int
    rooms: int
    availability_window: str
    repeat_of: str
    source: str

    @property
    def base_key(self) -> str:
        """同一次抽样的标识；重复观测回到基础抽次。"""
        return self.repeat_of or self.draw

    @property
    def is_repeat(self) -> bool:
        return bool(self.repeat_of)


@dataclass(frozen=True)
class Quote:
    quote: str
    draw: str
    pool: str
    room: str
    hotel: str
    arrival: str
    availability_window: str
    nightly_bundle: int | None
    mandatory_fee: int | None
    outcome: str
    bed_included: bool


@dataclass(frozen=True)
class InventoryCell:
    pool: str
    arrival: str
    window: str
    rooms: int
    state: str


@dataclass(frozen=True)
class Review:
    review: str
    ad: str
    state: str
    term_scope: str
    decided_on: str


@dataclass(frozen=True)
class Amendment:
    notice: str
    draw: str
    kind: str
    rule: str
    received_on: str
    explicit_value: str


@dataclass
class QuoteAssessment:
    """单条报价经规则引擎复核后的结论。"""

    quote: Quote
    rule: RoomRule | None
    structurally_fit: bool
    unfit_reasons: tuple[str, ...]
    mandatory_bed_due: int          # 按规则应补的强制加床费用（元）
    payable: int | None             # 含强制费用后的整住期应付价
    kind: EvidenceKind
    reason: str


@dataclass
class UnitVerdict:
    """一个基础抽样单位（折叠重复观测后）的最终判定。"""

    base_key: str
    ad: str
    stratum: str
    arrival_kind: str
    family_kind: str
    arrival: str
    search_day: str
    ages: tuple[int, ...]
    adults: int
    rooms: int
    pool: str
    window: str
    member_draws: tuple[str, ...]
    kind: EvidenceKind
    reason: str
    payable: int | None
    assessments: tuple[QuoteAssessment, ...] = field(default_factory=tuple)
    amended_notices: tuple[str, ...] = field(default_factory=tuple)

    @property
    def in_scope(self) -> bool:
        return self.kind is not EvidenceKind.OUT_OF_SCOPE

    @property
    def classified(self) -> bool:
        """是否有可验证结果；timeout 折叠后仍无硬证据时为 False。"""
        return self.kind is not EvidenceKind.TIMEOUT
