# 互换下单 v2 · place_order_request 示例片段

source: `swap/place_order.md` 示例段 `【示例输出】`（1040-1625 行）中 9 个示例的精选 3 条
retained: `1) POV 限价基础` + `5) TWAP 时间窗` + `7.1) 标的排除法（A/B 两案例）`
dropped: 5.1/5.2/5.3（相对时间窗，与 5) 重复）、6 + 6.1/6.2/6.3/6.4（交易品种类型前缀 5 变体，规则段已覆盖）、7（@提及）、8 + 8.1（时间窗边界）、9.1（不完整）
purpose: 和 `v2/_base.md` 通过 `compose_prompt("swap", "place_order", version="v2")` 拼接

## [system]

```
【示例输出】

**【提醒】示例数据污染防护**:
以下示例中的所有账户名、标的代码、数量都是虚构的占位符，仅用于展示 JSON 结构。
实际识别时必须且只能从 `swap_query` 等输入变量中提取数据，绝不使用示例中的任何值。
JSON 输出为纯 JSON，不带 ```json 标记。

---

1) 请求下单（POV 限价，文本输入）:
用户:@机器人 A股 0700.HK 买入 限价 320,POV25,2000股,交易对手:ACCOUNT_L
输出:
{
  "type": "place_order_request",
  "orderList": [
    {
      "orderId": null,
      "placeOrderUltraContractCode": null,
      "placeOrderWindCode": "A股 0700.HK",
      "placeOrderTransactionType": "A_SHARE",
      "placeOrderQuantity": 2000,
      "placeOrderOrderDirection": "BUY",
      "placeOrderPriceType": "LimitOrder",
      "placeOrderAlgorithmType": "POV",
      "placeOrderPrice": 320,
      "placeOrderPovPercent": 25,
      "placeOrderDisplayQty": null,
      "placeOrderStartTime": null,
      "placeOrderEndTime": null,
      "placeOrderShortname": "ACCOUNT_L",
      "placeOrderQuantityTotal": null
    }
  ]
}

---

5) 请求下单（TWAP 时间窗短语）:
用户:@机器人 港股 卖出 TWAP 限价 65,数量10000,上午开盘后到14:15
解析:开始=09:30,结束=14:15
输出:
{
  "type": "place_order_request",
  "orderList": [
    {
      "orderId": null,
      "placeOrderUltraContractCode": null,
      "placeOrderWindCode": null,
      "placeOrderTransactionType": "HK_STOCK",
      "placeOrderQuantity": 10000,
      "placeOrderOrderDirection": "SELL",
      "placeOrderPriceType": "LimitOrder",
      "placeOrderAlgorithmType": "TWAP",
      "placeOrderPrice": 65,
      "placeOrderPovPercent": null,
      "placeOrderDisplayQty": null,
      "placeOrderStartTime": "09:30",
      "placeOrderEndTime": "14:15",
      "placeOrderShortname": null,
      "placeOrderQuantityTotal": null,
      "placeOrderRelativeTimeMinutes": null
    }
  ]
}

---

7.1) 请求下单（标的排除法 - 严禁将交易参数吞入标的名称）:

案例A:
用户:中国平安 买入 3000股 限价50 @智能交易机器人
bot_name_list: ["智能交易机器人"]
解析:排除"买入"(方向)、"3000股"(数量)、"限价50"(价格)、"@智能交易机器人"(机器人名称过滤)后,剩余"中国平安"即为标的
输出:
{
  "type": "place_order_request",
  "orderList": [
    {
      "orderId": null,
      "placeOrderUltraContractCode": null,
      "placeOrderWindCode": "中国平安",
      "placeOrderTransactionType": null,
      "placeOrderQuantity": 3000,
      "placeOrderOrderDirection": "BUY",
      "placeOrderPriceType": "LimitOrder",
      "placeOrderAlgorithmType": null,
      "placeOrderPrice": 50,
      "placeOrderPovPercent": null,
      "placeOrderDisplayQty": null,
      "placeOrderStartTime": null,
      "placeOrderEndTime": null,
      "placeOrderShortname": null,
      "placeOrderQuantityTotal": null,
      "placeOrderRelativeTimeMinutes": null
    }
  ]
}
错误:placeOrderWindCode: "中国平安 买入 3000股 限价50 @智能交易"(严重错误!将整段文本当作标的!)
正确:placeOrderWindCode: "中国平安"(排除所有已知字段后的剩余)

案例B:
用户:宁德时代卖出600股，市价跟量20%鸿运二号 09:30-11:00 @OTC交易助手
bot_name_list: ["OTC交易助手"]
解析:排除"卖出"(方向)、"600股"(数量)、"市价"(价格类型)、"跟量20%"(POV比例)、"09:30-11:00"(时间窗)、"鸿运二号"(交易对手)、"@OTC交易助手"(机器人名称过滤)后,剩余"宁德时代"即为标的
输出:
{
  "type": "place_order_request",
  "orderList": [
    {
      "orderId": null,
      "placeOrderUltraContractCode": null,
      "placeOrderWindCode": "宁德时代",
      "placeOrderTransactionType": null,
      "placeOrderQuantity": 600,
      "placeOrderOrderDirection": "SELL",
      "placeOrderPriceType": "MarketOrder",
      "placeOrderAlgorithmType": "POV",
      "placeOrderPrice": null,
      "placeOrderPovPercent": 20,
      "placeOrderDisplayQty": null,
      "placeOrderStartTime": "09:30",
      "placeOrderEndTime": "11:00",
      "placeOrderShortname": "鸿运二号",
      "placeOrderQuantityTotal": null,
      "placeOrderRelativeTimeMinutes": null
    }
  ]
}

---

【输出前强制检查】(精简版)
1. type 字段必须为字符串 "place_order_request"
2. orderList 必须为数组且长度 ≥ 1
3. 每个订单对象中,所有字段的值都必须来自实际输入 swap_query,不得从上面任何示例复制
4. 金融专业缩写(UBS/S&P/MSCI/CBOT/CME/NASDAQ 等)必须逐字符原样保留,不得中文化或 emoji 化
5. 未提取到的字段一律输出 null,不得推断默认值
```
