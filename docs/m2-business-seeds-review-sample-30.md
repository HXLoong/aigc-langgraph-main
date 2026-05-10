# 业务方种子候选池抽样 Review · 30 条（修订后）

> 来源池：289 条 (`tests/fixtures/golden_business_seeds_2026-05.jsonl`，含 7 条自动质量扫描修订)
> 抽样：分层 11 个 intent · seed=20260510

## Review 操作

- `[x] PASS` — raw_content 准确 + intent 映射正确 + quote_content 上下文匹配
- `[ ] FAIL` — 任一字段错误

**通过门**：30 条中 PASS ≥ 27（90%）→ 整体合入 `golden.jsonl`

---

## intent = `new_inquiry` · 期权询价 · 5 条

### `g148` (`option` / `new_inquiry`)

- **raw**: `200万，市价下单`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

### `g329` (`option` / `new_inquiry`)

- **raw**: `快速询价：雪球，600989.SH，70/103，6M，31`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

### `g201` (`option` / `new_inquiry`)

- **raw**: `600519.SH，欧式看涨,1M,80%`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

### `g142` (`option` / `new_inquiry`)

- **raw**: `600519.SH，欧式看涨,1M,80%`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

### `g182` (`option` / `new_inquiry`)

- **raw**: `600519.SH，欧式看涨,1M,80%`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

---

## intent = `place_order_request` · 下单/参数调整请求 · 5 条

### `g226` (`swap` / `place_order_request`)

- **raw**: `603529.SH 市价买入1000股 占35% 16:00-17:00`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

### `g242` (`swap` / `place_order_request`)

- **raw**: `A组合 HTIF2504 空 1657股 市价 占35%  14:00-15:00`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

### `g217` (`swap` / `place_order_request`)

- **raw**: `A组合 HTIF2504 空 1657股 市价 占35%  14:00-15:00`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

### `g234` (`swap` / `place_order_request`)

- **raw**: `帮我下一个互换订单。我要买入603529.SH，数量是5000份，用限价5块钱。算法是POV25，请在下午一点半到三点半执行`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

### `g240` (`swap` / `place_order_request`)

- **raw**: `A组合 HTIF2504 空 1657股 市价 占35%  14:00-15:00`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

---

## intent = `confirm_order` · 确认下单（最终执行） · 5 条

### `g303` (`swap` / `confirm_order`)

- **raw**: `确认下单`
- **quote**: `机器人返回： 互换订单参数信息，包含：标的、方向、数量、价格类型、算法、时间等，并提示用户下一步步骤`

- [ ] PASS  - [ ] FAIL（说明：________）

### `g141` (`option` / `confirm_order`)

- **raw**: `确认下单`
- **quote**: `机器人返回完整得订单信息，并引导用户下一步操作步骤`

- [ ] PASS  - [ ] FAIL（说明：________）

### `g270` (`swap` / `confirm_order`)

- **raw**: `确认下单`
- **quote**: `机器人返回： 互换订单参数信息，包含：标的、方向、数量、价格类型、算法、时间等，并提示用户下一步步骤`

- [ ] PASS  - [ ] FAIL（说明：________）

### `g215` (`option` / `confirm_order`)

- **raw**: `确认下单`
- **quote**: `机器人返回： 贵州茅台欧式看涨期权的实时报价信息、名义本金和建仓指令，并提示用户下一步步骤`

- [ ] PASS  - [ ] FAIL（说明：________）

### `g203` (`option` / `confirm_order`)

- **raw**: `确认下单`
- **quote**: `机器人返回： 贵州茅台欧式看涨期权的实时报价信息、名义本金和建仓指令，并提示用户下一步步骤`

- [ ] PASS  - [ ] FAIL（说明：________）

---

## intent = `place_order_from_quote` · 基于询价后下单（option） · 4 条

### `g195` (`option` / `place_order_from_quote`)

- **raw**: `200万，市价下单`
- **quote**: `机器人返回: 贵州茅台欧式看涨期权（期限1M，执行价格80%）的实时报价信息，包含：标的代码、标的名称、期限、期权类型、执行价格%、交易方向、期权费率、名义本金规模（待补充）、建仓指令（待补充）。`

- [ ] PASS  - [ ] FAIL（说明：________）

### `g174` (`option` / `place_order_from_quote`)

- **raw**: `200万，市价下单`
- **quote**: `机器人返回: 贵州茅台欧式看涨期权（期限1M，执行价格80%）的实时报价信息，包含：标的代码、标的名称、期限、期权类型、执行价格%、交易方向、期权费率、名义本金规模（待补充）、建仓指令（待补充）。`

- [ ] PASS  - [ ] FAIL（说明：________）

### `g202` (`option` / `place_order_from_quote`)

- **raw**: `200万，市价下单`
- **quote**: `机器人返回: 贵州茅台欧式看涨期权（期限1M，执行价格80%）的实时报价信息，包含：标的代码、标的名称、期限、期权类型、执行价格%、交易方向、期权费率、名义本金规模（待补充）、建仓指令（待补充）。`

- [ ] PASS  - [ ] FAIL（说明：________）

### `g171` (`option` / `place_order_from_quote`)

- **raw**: `200万，市价下单`
- **quote**: `机器人返回: 贵州茅台欧式看涨期权（期限1M，执行价格80%）的实时报价信息，包含：标的代码、标的名称、期限、期权类型、执行价格%、交易方向、期权费率、名义本金规模（待补充）、建仓指令（待补充）。`

- [ ] PASS  - [ ] FAIL（说明：________）

---

## intent = `close_order_request` · 平仓请求 · 3 条

### `g337` (`option_close` / `close_order_request`)

- **raw**: `序号二 限10平三分之一`
- **quote**: `机器人返回: 以下平仓申请，请核对详情后确认： -----场外期权平仓详情----- 序号：1 合约编号：OPT-LYAFT20260001 单号：CO-20260506-DEAF117C 申请时间：2026-05-06 15:03 期权类型：欧式看涨 标的代码：000155.SZ 标的名称：川能动力 交易方向：卖出 平仓名义本金：5,000,000 平仓价格方式：市价单 若要对以上订单执行平仓操作，请引用本消息回复【确认平仓】`

- [ ] PASS  - [ ] FAIL（说明：________）

### `g341` (`option_close` / `close_order_request`)

- **raw**: `序号1 市价平掉所有持仓`
- **quote**: `机器人返回: 以下平仓申请，请核对详情后确认： -----场外期权平仓详情----- 序号：1 合约编号：OPT-LYAFT20260001 单号：CO-20260506-DEAF117C 申请时间：2026-05-06 15:21 期权类型：欧式看涨 标的代码：000155.SZ 标的名称：川能动力 交易方向：卖出 平仓名义本金：5,000,000 平仓价格方式：市价单   若要对以上订单执行平仓操作，请引用本消息回复【确认平仓】`

- [ ] PASS  - [ ] FAIL（说明：________）

### `g345` (`option_close` / `close_order_request`)

- **raw**: `序号1市价平掉超过 200 万的部分`
- **quote**: `机器人返回: 以下平仓申请，请核对详情后确认： -----场外期权平仓详情----- 序号：1 合约编号：OPT-LYAFT20260001 单号：CO-20260506-DEAF117C 申请时间：2026-05-06 15:18 期权类型：欧式看涨 标的代码：000155.SZ 标的名称：川能动力 交易方向：卖出 平仓名义本金：7,000,000 平仓价格方式：市价单 若要对以上订单执行平仓操作，请引用本消息回复【确认平仓】`

- [ ] PASS  - [ ] FAIL（说明：________）

---

## intent = `cancel_order_request` · 撤单请求 · 2 条

### `g265` (`swap` / `cancel_order_request`)

- **raw**: `我要撤单，麻烦快一点`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

### `g204` (`option` / `cancel_order_request`)

- **raw**: `撤单`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

---

## intent = `confirm_cancel_order` · 确认撤单（最终执行） · 1 条

### `g276` (`swap` / `confirm_cancel_order`)

- **raw**: `确认撤单`
- **quote**: `机器人返回： 订单号，提示用户已接收撤单指令，并提示用户下一步步骤`

- [ ] PASS  - [ ] FAIL（说明：________）

---

## intent = `confirm_modify_order` · 确认改单（最终执行） · 1 条

### `g359` (`swap` / `confirm_modify_order`)

- **raw**: `确认改单`
- **quote**: `机器人推送消息： "互换订单{单号}交易中：交易对手：%s，已成交数量：%s，已成交均价：%s，已成交金额：%s"`

- [ ] PASS  - [ ] FAIL（说明：________）

---

## intent = `request_modify_order` · 请求改单（option） · 1 条

### `g168` (`option` / `request_modify_order`)

- **raw**: `改为 限价6.3`
- **quote**: `机器人返回： 贵州茅台欧式看涨期权的实时报价信息、名义本金和建仓指令（市价下单），并提示用户下一步步骤`

- [ ] PASS  - [ ] FAIL（说明：________）

---

## intent = `close_order_query` · 可平持仓查询 · 1 条

### `g334` (`option_close` / `close_order_query`)

- **raw**: `查可平持仓`
- **quote**: (无)

- [ ] PASS  - [ ] FAIL（说明：________）

---

## intent = `unknown_intent` · 无法识别（反例噪声 / v1 prompt 不支持的口语） · 2 条

### `g146` (`option` / `unknown_intent`)

- **raw**: `123456789`
- **quote**: `机器人返回: 贵州茅台欧式看涨期权（期限1M，执行价格80%）的实时报价信息，包含：标的代码、标的名称、期限、期权类型、执行价格%、交易方向、期权费率、名义本金规模（待补充）、建仓指令（待补充）。`
- **notes**: 纯数字噪声，配 quote=报价信息但无业务意义；自动质量扫描修订（原 new_inquiry）

- [ ] PASS  - [ ] FAIL（说明：________）

### `g181` (`option` / `unknown_intent`)

- **raw**: `好的可以`
- **quote**: `机器人返回： 贵州茅台欧式看涨期权的实时报价信息、名义本金和建仓指令，并提示用户下一步步骤`
- **notes**: raw='好的可以' 口语确认；v1 prompt 严格要求'确认下单' → unknown_intent；prompt 改进 backlog（原 confirm_order）

- [ ] PASS  - [ ] FAIL（说明：________）

---

## 汇总（review 完后填）

| 项 | 数量 |
|---|---|
| 总抽样 | 30 |
| PASS | __ |
| FAIL | __ |
| PASS 率 | __ % |
| 是否达 90% 门 | YES / NO |
