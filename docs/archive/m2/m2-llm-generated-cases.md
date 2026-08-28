# LLM 对抗式变体候选清单（待业务方 review）

> grill-with-docs 第 4 决策 C 来源 · LLM 生成的 paraphrase 候选 case
>
> 业务方 review pass 的 case 转 jsonl 合入 `tests/fixtures/golden.jsonl`，
> 标记 `source: llm_paraphrase`（PASS 阈值 80%，比 business_seed 90% 阈值更宽松）。

## 使用流程

1. 业务方对每条候选打勾（`[x]`）或叉（`[ ]`）
2. 工程师批量将打勾的 case 合入 golden.jsonl
3. 跑 `python -m harness run` 验证整体 PASS 率不降

---


## 种子 g001（swap/place_order）

**原话**: @机器人 做一笔招商银行的 TRS，买 1000 手，市价
**expected**: `{"product_type": "swap", "intent": "place_order_request"}`

### 候选变体

- [ ] **g001-v1** (口语化+同义词替换)
  - raw: `@机器人 请帮我做一笔招商银行的互换，购买一千手，市价`
- [ ] **g001-v2** (缩写+词序调整)
  - raw: `@机器人 TRS交易 招商银行 1000手 市价`

## 种子 g002（swap/place_order）

**原话**: 互换下单 帮我买入1000股腾讯控股，市价单
**expected**: `{"product_type": "swap", "intent": "place_order_request"}`

### 候选变体

- [ ] **g002-v1** (缩写+同义词替换)
  - raw: `TRS成交 腾讯控股一千股 市价`
- [ ] **g002-v2** (口语化+词序调整)
  - raw: `可以帮我做一笔互换，买1000股腾讯吗？市价单`

## 种子 g003（swap/place_order_multi）

**原话**: 互换下单 帮我同时买入贵州茅台、腾讯控股、特斯拉各 100 股
**expected**: `{"product_type": "swap", "intent": "place_order_request"}`

### 候选变体

- [ ] **g003-v1** (缩写+同义词+省略)
  - raw: `TRS成交 贵州茅台腾讯控股特斯拉每样100股`
- [ ] **g003-v2** (口语化+词序调整)
  - raw: `请帮我做一笔互换，买入贵州茅台、腾讯控股和特斯拉各一百股`

## 种子 g004（swap/confirm）

**原话**: 确认单号 H-20260304-0000001
**expected**: `{"product_type": "swap", "intent": "confirm_order"}`
**quote**: 互换订单 H-20260304-0000001 已生成...

### 候选变体

- [ ] **g004-v1** (口语化)
  - raw: `请确认订单号 H-20260304-0000001`
  - quote: `互换订单 H-20260304-0000001 已生成...`
- [ ] **g004-v2** (同义词替换+词序调整)
  - raw: `确认编号 H-20260304-0000001 的互换订单`
  - quote: `互换订单 H-20260304-0000001 已生成...`

## 种子 g005（swap/confirm）

**原话**: 互换 确认下单 H-20260304-ABCD12345678
**expected**: `{"product_type": "swap", "intent": "confirm_order"}`

### 候选变体

- [ ] **g005-v1** (缩写+词序调整)
  - raw: `确认 H-20260304-ABCD12345678 的 TRS 下单`
- [ ] **g005-v2** (口语化+同义词替换)
  - raw: `请帮我确认这个互换订单 H-20260304-ABCD12345678`

## 种子 g006（swap/cancel_request）

**原话**: 撤 H-20260304-0000001
**expected**: `{"product_type": "swap", "intent": "cancel_order_request"}`

### 候选变体

- [ ] **g006-v1** (同义词替换)
  - raw: `取消 H-20260304-0000001`
- [ ] **g006-v2** (口语化)
  - raw: `请帮我撤单 H-20260304-0000001`

## 种子 g007（swap/cancel_request）

**原话**: 互换撤单 撤销订单 H-20260304-ABCD12345678
**expected**: `{"product_type": "swap", "intent": "cancel_order_request"}`

### 候选变体

- [ ] **g007-v1** (口语化+同义词替换)
  - raw: `帮我取消 H-20260304-ABCD12345678 的互换订单`
- [ ] **g007-v2** (错别字+词序调整)
  - raw: `撤消编号为H-20260304-ABCD12345678的互换`

## 种子 g008（swap/confirm_modify）

**原话**: swap确认修改订单 H-20260304-ABCD12345678
**expected**: `{"product_type": "swap", "intent": "confirm_modify_order"}`

### 候选变体

- [ ] **g008-v1** (同义词替换)
  - raw: `确认修改互换订单 H-20260304-ABCD12345678`
- [ ] **g008-v2** (口语化+词序调整)
  - raw: `请帮我确认一下这个swap的更改，编号是H-20260304-ABCD12345678`

## 种子 g009（swap/query）

**原话**: TRS 查一下订单 H-20260304-ABCD12345678 的状态
**expected**: `{"product_type": "swap", "intent": "query_order_status"}`

### 候选变体

- [ ] **g009-v1** (口语化+同义词)
  - raw: `请查一下 H-20260304-ABCD12345678 这个互换订单的状态`
- [ ] **g009-v2** (缩写+无空格)
  - raw: `TRS单号H-20260304-ABCD12345678状态查询`

## 种子 g010（swap/ticker_fuzzy）

**原话**: 做 纳指 一笔互换
**expected**: `{"product_type": "swap", "intent": "place_order_request"}`

### 候选变体

- [ ] **g010-v1** (同义词替换+省略)
  - raw: `纳斯达克指数互换成交`
- [ ] **g010-v2** (口语化+缩写)
  - raw: `请帮我做纳指 TRS`

## 种子 g011（swap/ticker_futures）

**原话**: 沪金下月合约互换 买 100 手
**expected**: `{"product_type": "swap", "intent": "place_order_request"}`

### 候选变体

- [ ] **g011-v1** (词序调整+省略空格)
  - raw: `下月沪金合约互换 买 100手`
- [ ] **g011-v2** (口语化+同义词替换)
  - raw: `请帮我做一个黄金下个月的互换交易，数量是100手`

## 种子 g012（option/quick_inquiry）

**原话**: 参与型看涨 腾讯控股 1个月
**expected**: `{"product_type": "option", "intent": "new_inquiry"}`

### 候选变体

- [ ] **g012-v1** (口语化+同义词替换)
  - raw: `我想了解一下腾讯控股的参与型看涨期权，期限一个月`
- [ ] **g012-v2** (缩写+错别字)
  - raw: `参涨 腾讯 控股 1月`

## 种子 g013（option/quick_inquiry）

**原话**: 参与型看跌 阿里巴巴 3个月
**expected**: `{"product_type": "option", "intent": "new_inquiry"}`

### 候选变体

- [ ] **g013-v1** (同义词替换)
  - raw: `阿里巴巴看跌期权 3个月`
- [ ] **g013-v2** (口语化+缩写)
  - raw: `我想了解一下参与型看跌 阿里 三个月的`

## 种子 g014（option/quick_inquiry_snowball）

**原话**: 雪球询价 腾讯控股
**expected**: `{"product_type": "option", "intent": "new_inquiry"}`

### 候选变体

- [ ] **g014-v1** (词序调整+同义词)
  - raw: `询价腾讯的雪球产品`
- [ ] **g014-v2** (口语化)
  - raw: `查一下腾讯控股的雪球价格`

## 种子 g015（option/standard_inquiry）

**原话**: 帮我询价茅台 3 个月雪球 名义 1000w
**expected**: `{"product_type": "option", "intent": "new_inquiry"}`

### 候选变体

- [ ] **g015-v1** (词序调整+同义词)
  - raw: `询一下茅台的3个月雪球，名义金额1000万`
- [ ] **g015-v2** (错别字+口语化+缩写)
  - raw: `请询价茅苔三个月雪球产品，面值1kw`

## 种子 g016（option/standard_inquiry）

**原话**: 期权询价 腾讯控股 欧式看涨 行权价500 1个月
**expected**: `{"product_type": "option", "intent": "new_inquiry"}`

### 候选变体

- [ ] **g016-v1** (词序调整+同义词替换)
  - raw: `欧式看涨期权询价，腾讯控股，行权价格500，期限1个月`
- [ ] **g016-v2** (口语化+详细描述)
  - raw: `请问一下腾讯控股的欧式看涨期权，行权价是500，一个月到期的报价是多少？`

## 种子 g017（option/place_order）

**原话**: 期权下单 茅台 欧式看涨 行权价 1800 期限 1M 名义 500万
**expected**: `{"product_type": "option", "intent": "place_order_from_quote"}`

### 候选变体

- [ ] **g017-v1** (词序调整+同义词替换)
  - raw: `欧式看涨期权 茅台 行权价格1800 期限1个月 名义本金500万`
- [ ] **g017-v2** (缩写+错别字)
  - raw: `茅欧式看涨期权，行权价1800，期限1M，名义5百万`

## 种子 g018（option/cancel）

**原话**: 期权撤单 OPT-20260304-0001
**expected**: `{"product_type": "option", "intent": "request_cancel_order"}`

### 候选变体

- [ ] **g018-v1** (同义词替换)
  - raw: `取消期权订单 OPT-20260304-0001`
- [ ] **g018-v2** (词序调整+口语化)
  - raw: `撤销期权编号OPT-20260304-0001的单子`

## 种子 g019（option/confirm_from_quote）

**原话**: 确认第二笔
**expected**: `{"product_type": "option", "intent": "confirm_order"}`
**quote**: 报价明细：
1. 茅台 行权价400 ...
2. 五粮液 行权价150 ...

### 候选变体

- [ ] **g019-v1** (口语化+数字替换)
  - raw: `请确认第2条`
  - quote: `报价明细：\n1. 茅台 行权价400 ...\n2. 五粮液 行权价150 ...`
- [ ] **g019-v2** (同义词替换)
  - raw: `确定第二个订单`
  - quote: `报价明细：\n1. 茅台 行权价400 ...\n2. 五粮液 行权价150 ...`

## 种子 g020（close/query）

**原话**: 我有哪些期权持仓
**expected**: `{"product_type": "option_close", "intent": "close_order_query"}`

### 候选变体

- [ ] **g020-v1** (口语化+同义词)
  - raw: `请告诉我现在手上的期权仓位`
- [ ] **g020-v2** (词序调整)
  - raw: `我现在的期权持仓有哪些？`

## 种子 g021（close/query）

**原话**: 查一下我现在的持仓
**expected**: `{"product_type": "option_close", "intent": "close_order_query"}`

### 候选变体

- [ ] **g021-v1** (口语化)
  - raw: `请帮我查下目前的持仓情况`
- [ ] **g021-v2** (错别字)
  - raw: `查询我当下的持仑`

## 种子 g022（close/request）

**原话**: 平 CO-20260304-4FE9C941 全部
**expected**: `{"product_type": "option_close", "intent": "close_order_request"}`

### 候选变体

- [ ] **g022-v1** (同义词替换+口语化)
  - raw: `平掉 CO-20260304-4FE9C941 所有`
- [ ] **g022-v2** (词序调整)
  - raw: `全部平仓 CO-20260304-4FE9C941`

## 种子 g023（close/request）

**原话**: 帮我平仓 CO-20260304-ABCD1234
**expected**: `{"product_type": "option_close", "intent": "close_order_request"}`

### 候选变体

- [ ] **g023-v1** (同义词替换+口语化)
  - raw: `清掉 CO-20260304-ABCD1234 的仓位`
- [ ] **g023-v2** (词序调整)
  - raw: `CO-20260304-ABCD1234 平仓`

## 种子 g024（close/confirm）

**原话**: 确认平仓 CO-20260304-ABCD1234
**expected**: `{"product_type": "option_close", "intent": "close_order_confirm"}`

### 候选变体

- [ ] **g024-v1** (同义词替换)
  - raw: `确认结清 CO-20260304-ABCD1234`
- [ ] **g024-v2** (口语化)
  - raw: `请帮我确认平仓 CO-20260304-ABCD1234，谢谢`

## 种子 g025（close/cancel）

**原话**: 撤销平仓单 CO-20260304-ABCD1234
**expected**: `{"product_type": "option_close", "intent": "close_order_cancel_request"}`

### 候选变体

- [ ] **g025-v1** (同义词替换)
  - raw: `取消平仓订单 CO-20260304-ABCD1234`
- [ ] **g025-v2** (口语化)
  - raw: `请帮我撤销这个平仓单 CO-20260304-ABCD1234 好吗？`

## 种子 g026（close/confirm_cancel）

**原话**: 确认撤销平仓 CO-20260304-ABCD1234
**expected**: `{"product_type": "option_close", "intent": "close_order_cancel_confirm"}`

### 候选变体

- [ ] **g026-v1** (同义词替换)
  - raw: `取消平仓操作 CO-20260304-ABCD1234`
- [ ] **g026-v2** (词序调整+错别字)
  - raw: `确认撤消编号为CO-20260304-ABCD1234的平仓`

## 种子 g027（unknown）

**原话**: 你好，在吗
**expected**: `{"product_type": "unknown"}`

### 候选变体

- [ ] **g027-v1** (同义词替换)
  - raw: `嗨，有人吗`
- [ ] **g027-v2** (口语化)
  - raw: `在不在呀？`

## 种子 g028（unknown）

**原话**: 今天天气怎么样
**expected**: `{"product_type": "unknown"}`

### 候选变体

- [ ] **g028-v1** (词序调整)
  - raw: `今天的天气如何`
- [ ] **g028-v2** (口语化)
  - raw: `今儿个天气咋样啊`

## 种子 g029（priority/order_no_over_keyword）

**原话**: 互换订单 CO-20260304-ABCD1234 帮我平仓
**expected**: `{"product_type": "option_close", "intent": "close_order_request"}`

### 候选变体

- [ ] **g029-v1** (口语化+词序调整)
  - raw: `帮我平掉 CO-20260304-ABCD1234 的互换订单`
- [ ] **g029-v2** (缩写+省略)
  - raw: `CO-20260304-ABCD1234 TRS 平仓`

## 种子 g030（priority/contract_no）

**原话**: 查询 OPTG-WFJJ202509030002 的状态
**expected**: `{"product_type": "option_close"}`

### 候选变体

- [ ] **g030-v1** (同义词替换)
  - raw: `查一下 OPTG-WFJJ202509030002 的情况`
- [ ] **g030-v2** (词序调整+口语化)
  - raw: `OPTG-WFJJ202509030002 现在是什么状态？`
