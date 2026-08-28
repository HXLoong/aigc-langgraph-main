# 业务方种子候选池 · 自动质量扫描报告

扫描总数：289 条 · 发现可疑：28 条

严重度：HIGH = 强烈建议修；MID = 需人工核对；LOW = 信息提示

| 严重度 | 数量 |
|---|---|
| MID | 18 |
| HIGH | 10 |

## 规则触发分布

| 规则 | 数量 |
|---|---|
| `too_short_raw` | 17 |
| `pure_digits_noise` | 5 |
| `new_inquiry_with_param_prompt_quote` | 3 |
| `confirm_intent_missing_keyword` | 2 |
| `close_intent_missing_keyword` | 1 |

## 完整可疑列表

### 严重度 HIGH

#### `g181` · `option/confirm_order` · 规则 `confirm_intent_missing_keyword`

- raw: `好的可以`
- quote: `机器人返回： 贵州茅台欧式看涨期权的实时报价信息、名义本金和建仓指令，并提示用户下一步步骤`
- 建议: intent=confirm_order 但 raw 不含 ['确认下单'] 任一关键词

#### `g245` · `swap/confirm_order` · 规则 `confirm_intent_missing_keyword`

- raw: `好的可以`
- quote: `机器人返回： 互换订单参数信息，包含：标的、方向、数量、价格类型、算法、时间等，并提示用户下一步步骤`
- 建议: intent=confirm_order 但 raw 不含 ['确认下单'] 任一关键词

#### `g116` · `option/new_inquiry` · 规则 `new_inquiry_with_param_prompt_quote`

- raw: `欧式看涨，100%`
- quote: `机器人提示用户输入缺失信息. “已收到您的期权询价请求，请问您期望的期权类型，执行价格百分比是？  例：期权类型：欧式看...`
- 建议: new_inquiry 不该有 quote_content + 补参数提示；建议 place_order_from_quote 或 request_modify_order

#### `g140` · `option/new_inquiry` · 规则 `new_inquiry_with_param_prompt_quote`

- raw: `临沂阿凡提`
- quote: `机器人提示用户补充交易对手.`
- 建议: new_inquiry 不该有 quote_content + 补参数提示；建议 place_order_from_quote 或 request_modify_order

#### `g146` · `option/new_inquiry` · 规则 `new_inquiry_with_param_prompt_quote`

- raw: `123456789`
- quote: `机器人返回: 贵州茅台欧式看涨期权（期限1M，执行价格80%）的实时报价信息，包含：标的代码、标的名称、期限、期权类型、...`
- 建议: new_inquiry 不该有 quote_content + 补参数提示；建议 place_order_from_quote 或 request_modify_order

#### `g146` · `option/new_inquiry` · 规则 `pure_digits_noise`

- raw: `123456789`
- quote: `机器人返回: 贵州茅台欧式看涨期权（期限1M，执行价格80%）的实时报价信息，包含：标的代码、标的名称、期限、期权类型、...`
- 建议: 纯数字 raw_content 应标 unknown_intent

#### `g239` · `swap/place_order_request` · 规则 `pure_digits_noise`

- raw: `123456789`
- quote: `机器人返回： 互换订单参数信息，包含：标的、方向、数量、价格类型、算法、时间等，并提示用户下一步步骤`
- 建议: 纯数字 raw_content 应标 unknown_intent

#### `g282` · `swap/place_order_request` · 规则 `pure_digits_noise`

- raw: `2800`
- quote: `机器人返回（图中有2个交易对手，则拆为2单）： 互换订单信息，包含：标的、方向、数量、价格类型、算法、时间、交易对手等，...`
- 建议: 纯数字 raw_content 应标 unknown_intent

#### `g284` · `swap/place_order_request` · 规则 `pure_digits_noise`

- raw: `1100`
- quote: `机器人返回（图中有2个交易对手，则拆为2单）： 互换订单信息，包含：标的、方向、数量、价格类型、算法、时间、交易对手等，...`
- 建议: 纯数字 raw_content 应标 unknown_intent

#### `g297` · `swap/place_order_request` · 规则 `pure_digits_noise`

- raw: `2800`
- quote: `机器人提示： 哪个订单的委托数量参数缺失，提供缺失参数示例，并引导用户补充`
- 建议: 纯数字 raw_content 应标 unknown_intent

### 严重度 MID

#### `g352` · `option_close/close_order_request` · 规则 `close_intent_missing_keyword`

- raw: `序号1，100 万，拉满跟量`
- quote: `机器人返回: 以下平仓申请，请核对详情后确认： -----场外期权平仓详情----- 序号：1 合约编号：OPT-LYA...`
- 建议: close_order_request 但 raw 未含平/平仓/订单号关键词

#### `g188` · `option/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g192` · `option/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g197` · `option/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g204` · `option/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g212` · `option/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤销`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g216` · `option/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g250` · `swap/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g253` · `swap/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g257` · `swap/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g262` · `swap/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g268` · `swap/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤销`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g271` · `swap/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g275` · `swap/cancel_order_request` · 规则 `too_short_raw`

- raw: `撤单`
- quote: `机器人返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g279` · `swap/place_order_request` · 规则 `too_short_raw`

- raw: `市价`
- quote: `机器人以拆单的方式解析返回： 订单号，提示用户已接收下单指令，等待交易员审核`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g280` · `swap/place_order_request` · 规则 `too_short_raw`

- raw: `卖出`
- quote: `机器人返回（图中有2个交易对手，则拆为2单）： 互换订单信息，包含：标的、方向、数量、价格类型、算法、时间、交易对手等，...`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g291` · `swap/place_order_request` · 规则 `too_short_raw`

- raw: `市价`
- quote: `机器人提示： 哪个订单的价格类型参数缺失，提供缺失参数示例，并引导用户补充`
- 建议: raw_content ≤2 字符，需确认是否反例噪声

#### `g293` · `swap/place_order_request` · 规则 `too_short_raw`

- raw: `卖出`
- quote: `机器人提示： 哪个订单的委托方向参数缺失，提供缺失参数示例，并引导用户补充`
- 建议: raw_content ≤2 字符，需确认是否反例噪声
