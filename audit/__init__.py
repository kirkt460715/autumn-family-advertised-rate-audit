"""亲子住宿广告价可订性复核工具。

模块划分：

- ``io_csv``   : 资料装载与格式/键值/关联校验
- ``rules``    : 搜索当日房型规则版本、家庭适配与应付费用
- ``units``    : 重复观测折叠、证据分级、展示价履约判定
- ``estimation``: 分层加权、置信区间、不可归类区间、联营联合覆盖
- ``amendments``: 运营后送补证的处理与影响分类
- ``review``   : 缩窄/暂缓/下架建议与联营重判
- ``report``   : CLI 与报告产出
"""

from .models import (
    Campaign,
    Draw,
    EvidenceKind,
    FrameStratum,
    InventoryCell,
    Quote,
    Review,
    RoomRule,
    UnitVerdict,
)

__all__ = [
    "Campaign",
    "Draw",
    "EvidenceKind",
    "FrameStratum",
    "InventoryCell",
    "Quote",
    "Review",
    "RoomRule",
    "UnitVerdict",
]
