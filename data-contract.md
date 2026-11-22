# 资料约定

CSV 采用 UTF-8 编码。日期使用年、月、日，数值以十进制表示。字段为空表示来源未提供该项或该项不适用，含义以表约定为准。

住宿价格为整住期人民币元。儿童年龄取入住日周岁，不含成年监护人。查询中 rooms 是家庭愿支付的房间数，当前只有整组可住的搜价才匹配承诺。价格含税及强制加床；adults 和 ages 对照合法组合，同一房池的来源查询不是独立库存。room_rules 按规则生效日期以及搜索发生时登记的版本选择。
抽样框按广告承诺覆盖的人群和入住日构造，frame 中 population 是该层机会数；draw 中 repeat_of 指同一次抽样的重复观测，纳入权重按同一 draw。其中 availability_window 是搜索允许使用的放房区间，pool 中 rooms 是该区间对应的可订房量。结果中的 `timeout` 是没有可用核验信息，`no_inventory` 是已查实库存约束，`ineligible` 是房型拒绝。联营承诺除各自比例外有一条 joint_minimum；joint_scope 中的承诺须以共享房量及互不重复的可订机会核对。

## 文件来源

- `campaigns.csv`。广告承诺与联营覆盖。minimum 和 joint_minimum 是承诺比例。 记录键为 `ad`。
- `room_rules.csv`。房型年龄上限、加床条件和变更后报送日。 记录键为 `rule`。
- `frame.csv`。分层抽样框。 记录键为 `stratum`。
- `draws.csv`。搜索抽样、家庭参数和记录关联。 记录键为 `draw`。
- `quotes.csv`。搜索的整住期原始报价和必付项，bed_included 表示已含强制加床。 记录键为 `quote`。
- `inventory.csv`。同等搜索时窗内的房池与开闭。 记录键为 `pool`、`arrival`、`window`。
- `reviews.csv`。已发宣传决定和新提案。 记录键为 `review`。
- `evidence_amendments.csv`。运营后送的搜索和房型解释。 记录键为 `notice`。
