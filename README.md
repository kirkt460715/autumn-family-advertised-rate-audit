# 亲子住宿广告价的可订性复核

酒店联营活动的广告窗口、真实可订条件与分层搜索核验。 `data/` 中的记录均为虚构业务数据。

使用 Python 3.11.2。资料核验仅依赖标准库。

## 运行复核

隔离模式（`-I`，不读取环境变量与当前目录，避免资料目录中的同名模块被导入）下，
通过仓库根的入口脚本运行：

```bash
python3 -I run_audit.py --data data            # 人读文本报告
python3 -I run_audit.py --data data --json     # 机器读 JSON
python3 -I run_tests.py                        # 全部单元测试
```

普通模式下等价命令同样可用：

```bash
python3 -m unittest discover -s tests -v
python3 -m audit --data data
```

## 复核口径（摘要）

- **规则回看**：房型规则按 `valid_from` 与搜索当日已登记（`documented`）的最高版本选取；
  后补规则不能解释搜索当日的拒单。
- **展示价履约**：报价须整户适配房型规则、含强制加床等应付费用，且不高于广告承诺价；
  `bed_included=no` 且儿童达到强制加床年龄时，按规则补加床费后再比价。
- **证据分级**：`fulfilled / price_exceeded / ineligible / no_inventory / timeout / out_of_scope`
  六类互斥；`timeout` 是无法归类的搜索，不计违约，仅进入非应答边界。
- **重复观测**：`repeat_of` 折叠回同一基础抽样单位，权重只计一次；重复观测中的可订证据
  可以救回首次 timeout，但重复观察永远不是独立家庭。
- **分层估计**：层权重 `population/基础抽次数`，报告点估计、分层 95% 抽样区间，
  以及"不可归类全履约/全不履约"的非应答边界，取外包络后对照承诺比例给出
  达标 / 不达标 / 证据不足。
- **联营联合覆盖**：同一房池按（入住日、放房时窗、家庭参数）去重，联合承诺在互不重复的
  可售机会上核对；分别评估入口会把一个家庭能订的房算成两份机会，工具不采用该口径。
- **质检决定**：保留（retain）/ 缩窄（narrow）/ 暂缓（pause）/ 下架（withdraw），
  并与 `reviews.csv` 的已登记决定对账；联合广告缩窄后须重算共用房池支持的其余广告。
- **后送补证**：区分改变的是统计支撑、原广告确实违反的条款，还是下一轮允许发布的范围；
  `past_policy=not_visible` 类补证一律驳回回溯适用。

完整方法见 [docs/methodology.md](docs/methodology.md)，各表字段见 [资料约定](data-contract.md)。

## 代码结构

```
audit/
  io_csv.py      资料装载与契约校验（表头、键值、外键、房池/房型关联）
  models.py      领域模型与证据分级
  rules.py       搜索当日规则版本、房型适配、强制加床与含费应付价
  units.py       覆盖范围核对、重复观测折叠、承诺价判定、联营去重键
  estimation.py  分层加权、置信区间、非应答边界、联合覆盖
  amendments.py  后送补证的采纳/驳回与影响分类
  review.py      质检建议、已登记决定冲突、联营联动重判
  pipeline.py    全流程编排与抽样对账
  report.py      文本/JSON 报告与 CLI
tests/           53 个单元与集成测试（含原有资料契约测试）
run_audit.py     隔离模式入口
run_tests.py     隔离模式测试入口
```
