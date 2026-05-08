# 全局公共参数

**全局Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| clientid | TL_AGENT | string | 是 | - |
| clientsecret | tltest | string | 是 | - |
| signature | clientid+timestamp+clientsalt | string | 是 | md5签名，16位大写 |
| timestamp | 1111111111111 | string | 是 | 当前时间戳ms |

# 场外期权


## 期权询价查询

**接口URL**

> /api/internal/agent/get_option_rfq

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10955866372569317@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |
| agentsubid | 1688856778752437 | string | 是 | 智能体对客身份子ID（针对微信渠道，指用户ID） |

**请求Body参数**

```javascript
{
    "chatType": "json",
    "chatInstrument": "快速询价：欧式看涨，688472.SH，100，6M",
    "productType": "EUROPEAN_VANILLA",
    "productSubtypeList": [],
    "fuzzyCodeList": ["688472.SH"],
    "tenor": [],
    "strike": [],
    "participateRate": [],
    "knockInPrice": [],
    "knockOutPrice": [],
    "estimateMargin": []
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| chatType | json | String | 是 | 响应类型，固定传json，以json形式返回 |
| chatInstrument | 快速询价：雪球，600989.SH，70/103，6M，30 | String | 是 | 询价指令内容 |
| productType | AUTOCALL | String | 是 | 产品结构，AUTOCALL-雪球/PARTICIPATORY-参与型看涨/EUROPEAN_VANILLA-欧式看涨 |
| productSubtypeList | - | Array | 是 | 雪球子类型列表，SNOWBALLX-普通大雪球/PUTCAP-保底大雪球/NONCONSTANT-降敲出雪球 |
| fuzzyCodeList | - | Array | 否 | wind代码列表 |
| tenor | - | Array | 是 | 期限列表 |
| strike | - | Array | 是 | 执行价 |
| knockInPrice | - | Array | 是 | 敲入价列表 |
| knockOutPrice | - | Array | 是 | 敲出价列表 |
| estimateMargin | - | Array | 是 | 保证金要求列表 |

**响应示例**

* 成功(200)

```javascript
{
	"errMsg": null,
	"errCode": {
		"code": 200,
		"chs": "请求成功",
		"eng": "SUCCESS_REQUEST"
	},
	"data": {
		"chatType": "json",
		"chatResult": [
			{
				"id": 34743226,
				"productType": "EUROPEAN_VANILLA",
				"productSubtype": null,
				"windName": "阿特斯",
				"windCode": "688472.SH",
				"currency": "CNY",
				"callPut": "CALL",
				"tenor": "1M",
				"strike": 0.8,
				"participateRate": 1,
				"structure": null,
				"price": 0.206,
				"initialObservationDate": null,
				"knockOutPrice": null,
				"knockInPrice": null,
				"maximumLossLevel": null,
				"estimateMargin": null,
				"annualizedCouponRate": null,
				"stepDown": null,
				"insFamily": "EQUITY",
				"exchange": "SSE",
				"crossCurrencyType": null,
				"settlementCurrency": null,
				"balance": 500
			}
		]
	}
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| errMsg | - | Null | 返回的错误详情信息，用于描述接口调用异常原因 |
| errCode | - | Object | - |
| errCode.code | 200 | Number | 系统返回的错误代码，用于标识请求状态 |
| errCode.chs | 请求成功 | String | 错误码对应的中文说明，便于用户理解错误含义 |
| errCode.eng | SUCCESS_REQUEST | String | 错误码对应的英文说明，用于国际化系统对接 |
| data | - | Object | 返回数据 |
| data.chatType | json | String | 指定会话数据格式类型，当前为JSON结构 |
| data.chatResult | - | Array | 会话返回的详细结果数据，包含产品与交易信息 |
| data.chatResult.id | 34743226 | Number | 产品唯一标识编号，用于系统内部识别 |
| data.chatResult.productType | EUROPEAN_VANILLA | String | 产品主类型，表示为欧式普通型金融衍生品 |
| data.chatResult.productSubtype | - | String | 产品具体细分类型，如期权、互换等 |
| data.chatResult.windName | 阿特斯 | String | 产品在万得系统中的中文名称 |
| data.chatResult.windCode | 688472.SH | String | 产品在万得系统中的唯一代码标识 |
| data.chatResult.currency | CNY | String | 产品计价所使用的货币代码，如人民币CNY |
| data.chatResult.callPut | CALL | Null | 标识期权为看涨或看跌类型，CALL表示看涨 |
| data.chatResult.tenor | 1M | String | 产品到期时间周期，如1M表示一个月期 |
| data.chatResult.strike | 0.8 | Null | 期权的行权价格，以当前货币单位表示 |
| data.chatResult.participateRate | 1 | Null | 产品收益计算中对标的资产的参与比例 |
| data.chatResult.structure | - | Null | 产品具体结构描述，如普通期权、障碍期权等 |
| data.chatResult.price | 0.206 | Null | 价格 |
| data.chatResult.initialObservationDate | - | String | 产品首次观察标的资产价格的日期 |
| data.chatResult.knockOutPrice | - | Number | 障碍期权的敲出触发价格，高于此价则提前终止 |
| data.chatResult.knockInPrice | - | Number | 障碍期权的敲入触发价格，低于此价则触发收益条款 |
| data.chatResult.maximumLossLevel | - | Number | 产品可能面临的最大亏损比例，用于风险提示 |
| data.chatResult.estimateMargin | - | Number | 产品交易所需预估的保证金金额，单位为元 |
| data.chatResult.annualizedCouponRate | - | Number | 产品年化收益回报率，以百分比形式表示 |
| data.chatResult.stepDown | - | Number | 产品收益逐步下调的触发比例，用于结构化产品设计 |
| data.chatResult.insFamily | EQUITY | String | 产品所属的金融衍生品家族，如权益类、利率类等 |
| data.chatResult.exchange | SSE | String | 产品交易的证券交易所代码，如上交所SSE |
| data.chatResult.crossCurrencyType | - | Null | 标的资产与结算货币是否跨币种，如无则为空 |
| data.chatResult.settlementCurrency | - | Null | 产品最终结算所使用的货币类型，如人民币CNY |
| data.chatResult.balance | 500 | Number | 用户账户当前可用余额，单位为人民币元 |

* 失败(404)

```javascript
暂无数据
```


## 场外期权下单

**接口URL**

> /api/internal/agent/option/order

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10821094351495088@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |
| agentsubid | 1688855175747584 | string | 是 | 智能体对客身份子ID（针对微信渠道，指用户ID） |

**请求Body参数**

```javascript
{
    "id": 34176993,
    "contractType": "PARTICIPATORY",
    // "contractSubType": "PUTCAP",
    "direction": "CALL",
    "tradeDirection": "BUY",
    "quotationOrderType": "QUOTATION_FILE",
    "openPositionType": "MARKET_PRICE",
    // "initialUnderlyingPriceOrder": 8.8,
    "collateralNotional": 1000000
    // "algorithmOrderVol": null,
    // "algorithmOrderStartTime": "2025-08-26 08:00:00",
    // "algorithmOrderEndTime": "2025-08-26 20:00:00",
    // "shortName": "10698测试短名"
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| id | 33078968 | Number | 是 | 文章ID |
| contractType | EUROPEAN_VANILLA | String | 是 | 期权类型 |
| direction | CALL | String | 是 | 期权方向，CALL |
| tradeDirection | BUY | String | 是 | 交易方向，BUY |
| quotationOrderType | QUOTATION_FILE | String | 否 | 下单方式，QUOTATION_FILE |
| openPositionType | LIMIT_PRICE | String | 是 | 建仓方式，LIMIT_PRICE, MARKET_PRICE, TWAP, POV |
| initialUnderlyingPriceOrder | 5 | Number | 是 | 限定价格,MARKET_PRICE时不用传 |
| collateralNotional | 1000000 | Number | 是 | 下单金额 |
| algorithmOrderVol | - | Null | 否 | pov比例-当建仓方式为【POV】时必填,范围：0.01-0.25 |
| algorithmOrderStartTime | 2025-08-26 08:00:00 | String | 否 | 算法起始时刻,当建仓方式为【TWAP】时必填，YYYY-MM-DD HH:mm:ss |
| algorithmOrderEndTime | 2025-08-26 20:00:00 | String | 否 | 算法终止时刻,当建仓方式为【TWAP】时必填，YYYY-MM-DD HH:mm:ss |
| shortName | 10698测试短名 | Null | 否 | 交易对手简称，选填 |

**响应示例**

* 成功(200)

```javascript
{
    "errMsg": null,
    "errCode": {
        "code": 200,
        "chs": "成功",
        "eng": "success"
    },
    "data": "9285b286d6754274b99d7d4b3a8a2783"
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| errMsg | - | Null | - |
| errCode | - | Object | - |
| errCode.code | 200 | Number | - |
| errCode.chs | 成功 | String | - |
| errCode.eng | success | String | - |
| data | 9285b286d6754274b99d7d4b3a8a2783 | String | 订单ID |

* 失败(404)

```javascript
暂无数据
```


## 期权下单状态查询接口【轮询】

**接口URL**

> /api/internal/agent/option/order/status?orderId=1689eeab08334a348ebf91ceea13096c

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> GET

**Content-Type**

> none

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10955866372569317@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |

**请求Query参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| orderId | 1689eeab08334a348ebf91ceea13096c | string | 是 | 订单ID |

**响应示例**

* 成功(200)

```javascript
{
    "errMsg": null,
    "errCode": {
        "code": 200,
        "chs": "成功",
        "eng": "success"
    },
    "data": {
        "success": null,
        "failureMsg": null,
        "keyStockOrderId": null,
        "completed": false
    }
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| errMsg | - | string | - |
| errCode | - | Object | - |
| errCode.code | 200 | Number | - |
| errCode.chs | 成功 | String | - |
| errCode.eng | success | String | - |
| data | - | Object | 订单ID |
| data.success | - | boolean | 成功响应 |
| data.failureMsg | - | string | 失败信息 |
| data.keyStockOrderId | - | integer | 订单id |
| data.completed | false | Boolean | false、true，true代表审核通过，已下单 |

* 失败(404)

```javascript
暂无数据
```


## 期权下单结果查询接口

**接口URL**

> /api/internal/agent/option/order/query

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10955866372569317@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |

**请求Body参数**

```javascript
{
    "filter": {
        "contractType": "AUTOCALL",
        "keyStockOrderId": 973409
    },
    "pageNum": 1,
    "pageSize": 100
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| filter | - | Object | 是 | - |
| filter.contractType | EUROPEAN_VANILLA | String | 是 | 期权类型，EUROPEAN_VANILLA,AUTOCALL,PARTICIPATORY |
| filter.keyStockOrderId | 271473 | Number | 是 | 状态查询接口返回的订单id |
| pageNum | 1 | Number | 是 | - |
| pageSize | 100 | Number | 是 | - |

**响应示例**

* 成功(200)

```javascript
{
    "errMsg": null,
    "errCode": {
        "code": 200,
        "chs": "成功",
        "eng": "success"
    },
    "data": {
        "pageNum": 1,
        "pageSize": 2,
        "total": 2,
        "queryResults": [
            {
                "trdGoatsOptionOrder": {
                    "keyGoatsOptionOrderId": 29033,
                    "keyStockOrderId": 270985,
                    "keyOTCTradeId": null,
                    "tradeDate": "2025-08-26",
                    "tradeTime": "2025-08-26 19:30:44",
                    "orderTakingTime": null,
                    "orderCompletedTime": null,
                    "dealNotional": null,
                    "dealPrice": null,
                    "createdDateTime": "2025-08-26 19:30:44",
                    "createdBy": "SYSTEM",
                    "updatedDateTime": "2025-08-26 19:30:44",
                    "updatedBy": "SYSTEM",
                    "optOrderId": "f1171d83080845a3a8d7dac32f5be4c7",
                    "keyCtptyId": 15912,
                    "ctptyName": "15912测试账户",
                    "account": 13918,
                    "gftUsername": "chenyikun",
                    "underlyingWindCode": "000021.SZ",
                    "underlyingWindName": "深科技",
                    "tradeDirection": "BUY",
                    "timeToMaturity": "1M",
                    "orderStatus": "OTC_REJECTED",
                    "customerId": "5414",
                    "customerPhone": "13902214901",
                    "keyRFQId": null,
                    "feedbackType": "MID_END",
                    "premium": null,
                    "initialMargin": null,
                    "quotationOrderType": "QUOTATION_FILE"
                },
                "trdGoatsOptionStructure": {
                    "keyTrdGoatsOptionOrderId": "f1171d83080845a3a8d7dac32f5be4c7",
                    "initialMarginRatio": 0,
                    "estimatePremium": 206000,
                    "estimateMargin": 0,
                    "estimateCoupon": null,
                    "initialUnderlyingPrice": 21,
                    "contractType": "EUROPEAN_VANILLA",
                    "contractSubType": null,
                    "startObservationDate": null,
                    "underlyingInsId": 54344,
                    "initialNotional": 1000000,
                    "createdDateTime": "2025-08-26 19:30:44",
                    "createdBy": "SYSTEM",
                    "updatedDateTime": "2025-08-26 19:30:44",
                    "updatedBy": "SYSTEM",
                    "direction": "CALL",
                    "strikePct": 0.8,
                    "participationRate": 1,
                    "premiumRate": 0.206,
                    "kiBarrierPct": null,
                    "koBarrierPct": null,
                    "maximumLossLevel": null,
                    "annualizedCouponRate": null,
                    "openPositionType": "TWAP",
                    "algorithmOrderVol": null,
                    "algorithmOrderStartTime": "2025-08-26 10:00:00",
                    "algorithmOrderEndTime": "2025-08-26 20:00:00",
                    "stepDown": null,
                    "cappedPricePct": null,
                    "rfqType": null,
                    "riskBarrierPct": null,
                    "insFamily": "EQUITY"
                },
                "goatsContractInfo": {
                    "keyOTCTradeId": null,
                    "keyInstrumentId": null,
                    "contractType": null,
                    "contractSubType": null,
                    "direction": null,
                    "strikePct": null,
                    "premiumRate": null,
                    "notional": null,
                    "collateralNotional": null,
                    "initialNotional": null,
                    "premium": null,
                    "annualizedCouponRate": null,
                    "coupon": null,
                    "kiBarrierPct": null,
                    "koBarrierPct": null,
                    "contrStatus": null,
                    "initialUnderlyingPrice": null,
                    "contractCode": null
                },
                "stockOrderCode": "OPTG-SZJCZJ202508260002",
                "dealNotional": null,
                "dealPrice": null,
                "tradeTime": "2025-08-26 19:30:44",
                "orderTakingTime": null,
                "orderCompletedTime": null,
                "allowWithdraw": false,
                "remark": "抱歉，当前不在接单时间",
                "rfqQuotaMode": null,
                "clientExecutedPercentage": 0
            },
            {
                "trdGoatsOptionOrder": {
                    "keyGoatsOptionOrderId": 29032,
                    "keyStockOrderId": 270978,
                    "keyOTCTradeId": 169161,
                    "tradeDate": "2025-08-26",
                    "tradeTime": "2025-08-26 17:01:01",
                    "orderTakingTime": null,
                    "orderCompletedTime": null,
                    "dealNotional": null,
                    "dealPrice": null,
                    "createdDateTime": "2025-08-26 17:01:01",
                    "createdBy": "SYSTEM",
                    "updatedDateTime": "2025-08-26 17:01:04",
                    "updatedBy": "SYSTEM",
                    "optOrderId": "792a1531fe79458d864eca6f56e383e2",
                    "keyCtptyId": 15912,
                    "ctptyName": "15912测试账户",
                    "account": 13918,
                    "gftUsername": "chenyikun",
                    "underlyingWindCode": "000021.SZ",
                    "underlyingWindName": "深科技",
                    "tradeDirection": "BUY",
                    "timeToMaturity": "1M",
                    "orderStatus": "CANCELLED",
                    "customerId": "5414",
                    "customerPhone": "13902214901",
                    "keyRFQId": null,
                    "feedbackType": "MID_END",
                    "premium": 206000,
                    "initialMargin": 0,
                    "quotationOrderType": "QUOTATION_FILE"
                },
                "trdGoatsOptionStructure": {
                    "keyTrdGoatsOptionOrderId": "792a1531fe79458d864eca6f56e383e2",
                    "initialMarginRatio": 0,
                    "estimatePremium": 206000,
                    "estimateMargin": 0,
                    "estimateCoupon": null,
                    "initialUnderlyingPrice": 1,
                    "contractType": "EUROPEAN_VANILLA",
                    "contractSubType": null,
                    "startObservationDate": null,
                    "underlyingInsId": 54344,
                    "initialNotional": 1000000,
                    "createdDateTime": "2025-08-26 17:01:01",
                    "createdBy": "SYSTEM",
                    "updatedDateTime": "2025-08-26 17:01:01",
                    "updatedBy": "SYSTEM",
                    "direction": "CALL",
                    "strikePct": 0.8,
                    "participationRate": 1,
                    "premiumRate": 0.206,
                    "kiBarrierPct": null,
                    "koBarrierPct": null,
                    "maximumLossLevel": null,
                    "annualizedCouponRate": null,
                    "openPositionType": "LIMIT_PRICE",
                    "algorithmOrderVol": null,
                    "algorithmOrderStartTime": null,
                    "algorithmOrderEndTime": null,
                    "stepDown": null,
                    "cappedPricePct": null,
                    "rfqType": null,
                    "riskBarrierPct": null,
                    "insFamily": "EQUITY"
                },
                "goatsContractInfo": {
                    "keyOTCTradeId": null,
                    "keyInstrumentId": null,
                    "contractType": null,
                    "contractSubType": null,
                    "direction": null,
                    "strikePct": null,
                    "premiumRate": null,
                    "notional": null,
                    "collateralNotional": null,
                    "initialNotional": null,
                    "premium": null,
                    "annualizedCouponRate": null,
                    "coupon": null,
                    "kiBarrierPct": null,
                    "koBarrierPct": null,
                    "contrStatus": null,
                    "initialUnderlyingPrice": null,
                    "contractCode": null
                },
                "stockOrderCode": "OPTG-SZJCZJ202508260001",
                "dealNotional": null,
                "dealPrice": null,
                "tradeTime": "2025-08-26 17:01:01",
                "orderTakingTime": null,
                "orderCompletedTime": null,
                "allowWithdraw": false,
                "remark": null,
                "rfqQuotaMode": null,
                "clientExecutedPercentage": 0
            }
        ]
    }
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| data.queryResults.trdGoatsOptionOrder.underlyingWindName | 深科技 | String | 标的名称 |
| data.queryResults.trdGoatsOptionOrder.orderTakingTime | - | Null | 接单时间 |
| data.queryResults.trdGoatsOptionOrder.orderCompletedTime | - | Null | 完成时间 |
| data.queryResults.stockOrderCode | OPTG-SZJCZJ202508260002 | String | trading订单orderCode |
| data.queryResults.dealNotional | - | Null | 成交名义本金 |
| data.queryResults.dealPrice | - | Null | 成交价格 |
| data.queryResults.tradeTime | 2025-08-26 19:30:44 | String | 下单时间 |
| data.queryResults.orderTakingTime | - | Null | 接单时间 |
| data.queryResults.orderCompletedTime | - | Null | 完成时间 |
| data.queryResults.allowWithdraw | false | Boolean | 允许撤单 |
| data.queryResults.remark | 抱歉，当前不在接单时间 | String | 备注 |
| data.queryResults.rfqQuotaMode | - | Null | 询价模式，SHAREABLE, NON_SHAREABLE |
| data.queryResults.clientExecutedPercentage | 0 | Number | 成交进度 |
| data.queryResults.trdGoatsOptionOrder.gftUsername | chenyikun | String | 广发通用户名 |
| data.queryResults.trdGoatsOptionOrder.underlyingWindCode | 000021.SZ | String | 标的代码 |
| data.queryResults.trdGoatsOptionOrder.tradeTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.trdGoatsOptionOrder.orderTakingTime | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.orderCompletedTime | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.dealNotional | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.dealPrice | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.createdDateTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.trdGoatsOptionOrder.createdBy | SYSTEM | String | - |
| data.queryResults.trdGoatsOptionOrder.updatedDateTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.trdGoatsOptionOrder.updatedBy | SYSTEM | String | - |
| data.queryResults.trdGoatsOptionOrder.optOrderId | f1171d83080845a3a8d7dac32f5be4c7 | String | - |
| data.queryResults.trdGoatsOptionOrder.keyCtptyId | 15912 | Number | - |
| data.queryResults.trdGoatsOptionOrder.ctptyName | 15912测试账户 | String | - |
| data.queryResults.trdGoatsOptionOrder.account | 13918 | Number | 账户 |
| data.queryResults.trdGoatsOptionOrder.gftUsername | chenyikun | String | - |
| data.queryResults.trdGoatsOptionOrder.underlyingWindCode | 000021.SZ | String | - |
| data.queryResults.trdGoatsOptionOrder.underlyingWindName | 深科技 | String | - |
| data.queryResults.trdGoatsOptionOrder.tradeDirection | BUY | String | 交易方向，BUY |
| data.queryResults.trdGoatsOptionOrder.timeToMaturity | 1M | String | 期限 |
| data.queryResults.trdGoatsOptionOrder.orderStatus | OTC_REJECTED | String | - |
| data.queryResults.trdGoatsOptionOrder.customerId | 5414 | String | - |
| data.queryResults.trdGoatsOptionOrder.customerPhone | 13902214901 | String | - |
| data.queryResults.trdGoatsOptionOrder.keyRFQId | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.feedbackType | MID_END | String | - |
| data.queryResults.trdGoatsOptionOrder.premium | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.initialMargin | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.quotationOrderType | QUOTATION_FILE | String | 下单方式，QUOTATION_FILE |
| data.queryResults.trdGoatsOptionStructure | - | Object | - |
| data.queryResults.trdGoatsOptionStructure.keyTrdGoatsOptionOrderId | f1171d83080845a3a8d7dac32f5be4c7 | String | - |
| data.queryResults.trdGoatsOptionStructure.initialMarginRatio | 0 | Number | - |
| data.queryResults.trdGoatsOptionStructure.estimatePremium | 206000 | Number | - |
| data.queryResults.trdGoatsOptionStructure.estimateMargin | 0 | Number | - |
| data.queryResults.trdGoatsOptionStructure.estimateCoupon | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.initialUnderlyingPrice | 21 | Number | - |
| data.queryResults.trdGoatsOptionStructure.contractType | EUROPEAN_VANILLA | String | 期权类型，EUROPEAN_VANILLA,AUTOCALL,PARTICIPATORY |
| data.queryResults.trdGoatsOptionStructure.contractSubType | - | Null | 期权子类型 |
| data.queryResults.trdGoatsOptionStructure.startObservationDate | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.underlyingInsId | 54344 | Number | - |
| data.queryResults.trdGoatsOptionStructure.initialNotional | 1000000 | Number | - |
| data.queryResults.trdGoatsOptionStructure.createdDateTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.trdGoatsOptionStructure.createdBy | SYSTEM | String | - |
| data.queryResults.trdGoatsOptionStructure.updatedDateTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.trdGoatsOptionStructure.updatedBy | SYSTEM | String | - |
| data.queryResults.trdGoatsOptionStructure.direction | CALL | String | 期权方向，CALL |
| data.queryResults.trdGoatsOptionStructure.strikePct | 0.8 | Number | 执行价格，小数 |
| data.queryResults.trdGoatsOptionStructure.participationRate | 1 | Number | - |
| data.queryResults.trdGoatsOptionStructure.premiumRate | 0.206 | Number | 期权费率 |
| data.queryResults.trdGoatsOptionStructure.kiBarrierPct | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.koBarrierPct | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.maximumLossLevel | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.annualizedCouponRate | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.openPositionType | TWAP | String | 建仓方式，LIMIT_PRICE, MARKET_PRICE, TWAP, POV |
| data.queryResults.trdGoatsOptionStructure.algorithmOrderVol | - | Null | pov比例-当建仓方式为【POV】时必填,范围：0.01-0.25 |
| data.queryResults.trdGoatsOptionStructure.algorithmOrderStartTime | 2025-08-26 10:00:00 | String | 算法起始时刻,当建仓方式为【TWAP】时必填，YYYY-MM-DD HH:mm:ss |
| data.queryResults.trdGoatsOptionStructure.algorithmOrderEndTime | 2025-08-26 20:00:00 | String | 算法终止时刻,当建仓方式为【TWAP】时必填，YYYY-MM-DD HH:mm:ss |
| data.queryResults.trdGoatsOptionStructure.stepDown | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.cappedPricePct | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.rfqType | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.riskBarrierPct | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.insFamily | EQUITY | String | - |
| data.queryResults.goatsContractInfo | - | Object | - |
| data.queryResults.goatsContractInfo.keyOTCTradeId | - | Null | - |
| data.queryResults.goatsContractInfo.keyInstrumentId | - | Null | - |
| data.queryResults.goatsContractInfo.contractType | - | Null | 期权类型，EUROPEAN_VANILLA,AUTOCALL,PARTICIPATORY |
| data.queryResults.goatsContractInfo.contractSubType | - | Null | 期权子类型 |
| data.queryResults.goatsContractInfo.direction | - | Null | 期权方向，CALL |
| data.queryResults.goatsContractInfo.strikePct | - | Null | 执行价格，小数 |
| data.queryResults.goatsContractInfo.premiumRate | - | Null | 期权费率 |
| data.queryResults.goatsContractInfo.notional | - | Null | - |
| data.queryResults.goatsContractInfo.collateralNotional | - | Null | 下单金额 |
| data.queryResults.goatsContractInfo.initialNotional | - | Null | - |
| data.queryResults.goatsContractInfo.premium | - | Null | - |
| data.queryResults.goatsContractInfo.annualizedCouponRate | - | Null | - |
| data.queryResults.goatsContractInfo.coupon | - | Null | - |
| data.queryResults.goatsContractInfo.kiBarrierPct | - | Null | - |
| data.queryResults.goatsContractInfo.koBarrierPct | - | Null | - |
| data.queryResults.goatsContractInfo.contrStatus | - | Null | - |
| data.queryResults.goatsContractInfo.initialUnderlyingPrice | - | Null | - |
| data.queryResults.goatsContractInfo.contractCode | - | Null | - |
| data.queryResults.stockOrderCode | OPTG-SZJCZJ202508260002 | String | - |
| data.queryResults.dealNotional | - | Null | - |
| data.queryResults.dealPrice | - | Null | - |
| data.queryResults.tradeTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.orderTakingTime | - | Null | - |
| data.queryResults.orderCompletedTime | - | Null | - |
| data.queryResults.allowWithdraw | false | Boolean | - |
| data.queryResults.remark | 抱歉，当前不在接单时间 | String | - |
| data.queryResults.rfqQuotaMode | - | Null | - |
| data.queryResults.clientExecutedPercentage | 0 | Number | - |

* 失败(404)

```javascript
暂无数据
```


## 场外期权撤单

**接口URL**

> /api/internal/agent/option/order/withdraw

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10942303743943955@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |
| agentsubid | 1688855554346040 | string | 是 | 智能体对客身份子ID（针对微信渠道，指用户ID） |

**请求Body参数**

```javascript
{
    "keyStockOrderId": 271473
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| keyStockOrderId | 271473 | Number | 是 | 订单id |

**响应示例**

* 成功(200)

```javascript
{
  "data": "xxx",
  "errCode": {
    "chs": "成功",
    "code": 200,
    "eng": "success"
  },
  "errMsg": "1个定价指标计算存在异常",
  "serviceId": "1234455",
  "timestamp": 0
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| data | xxx | String | 撤单编号 |
| errCode | - | Object | - |
| errCode.chs | 成功 | String | - |
| errCode.code | 200 | Number | - |
| errCode.eng | success | String | - |
| errMsg | 1个定价指标计算存在异常 | Null | - |
| serviceId | 1234455 | String | - |
| timestamp | 0 | Number | - |

* 失败(404)

```javascript
暂无数据
```


## 场外期权撤单结果查询【轮询】

**接口URL**

> /api/internal/agent/option/order/withdrawResult?stockOrderCode=OPTG-WFJJ202509030002

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> GET

**Content-Type**

> none

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10942303743943955@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |
| agentsubid | - | string | 是 | 智能体对客身份子ID（针对微信渠道，指用户ID） |

**请求Query参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| stockOrderCode | OPTG-WFJJ202509030002 | string | 是 | 撤单编号 |

**响应示例**

* 成功(200)

```javascript
{
  "data": {
    "completed": true,
    "failureMsg": "string",
    "stockOrderCode": "string",
    "withdrawResult": "SUCCESS"
  },
  "errCode": {
    "chs": "成功",
    "code": 200,
    "eng": "success"
  },
  "errMsg": "1个定价指标计算存在异常",
  "serviceId": "string",
  "timestamp": 0
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| data | - | String | - |
| data.completed | true | Boolean | 撤单审核进度，true-完成，false-未完成 |
| data.failureMsg | string | String | 失败信息 |
| data.stockOrderCode | string | String | 撤单编号 |
| data.withdrawResult | SUCCESS | String | 撤单结果，SUCCESS, FAILURE, PENDING_CANCEL |
| errCode | - | Object | - |
| errCode.chs | 成功 | String | - |
| errCode.code | 200 | Number | - |
| errCode.eng | success | String | - |
| errMsg | 1个定价指标计算存在异常 | Null | - |
| serviceId | string | String | - |
| timestamp | 0 | Number | - |

* 失败(404)

```javascript
暂无数据
```


## 【期权】可平仓合约列表查询接口

**接口URL**

> /api/internal/agent/option/position

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10821094351495088@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |

**请求Body参数**

```javascript
{
    "filter": {
        // "insFamilyList": [],
        // "contractTypeList": ["EUROPEAN_VANILLA"],
        // "contractSubTypeList": [],
        // "internalTradeIdList": [],
        // "internalTradeId": "OPT-xxxx",
        // "keyOTCTradeId": 111111,
        "allowCloseOut": true
    },
    "pageNum": 1,
    "pageSize": 0
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| filter | - | Object | 是 | - |
| filter.keyCtptyIdList | - | Array | 否 | 交易对手id列表 |
| filter.insFamilyList | - | Array | 否 | 标的类型列表，EQUITY, INDEX，FUND |
| filter.contractTypeList | - | Array | 否 | 合约类型列表，"EUROPEAN_VANILLA"、"AUTOCALL"、"PARTICIPATORY"、"AIRBAG" |
| filter.contractSubTypeList | - | Array | 否 | 合约子类型列表 |
| filter.internalTradeIdList | - | Array | 否 | 合约编号列表 |
| filter.keyInstrumentIdList | - | Array | 否 | 合约id列表 |
| filter.internalTradeId | OPT-xxxx | String | 是 | 合约编号 |
| filter.keyOTCTradeId | 111111 | Number | 是 | 合约id |
| filter.allowCloseOut | true | Boolean | 是 | 是否只查可平仓合约，true / false |
| pageNum | 1 | Number | 是 | - |
| pageSize | 0 | Number | 是 | - |

**响应示例**

* 成功(200)

```javascript
{
    "errMsg": null,
    "errCode": {
        "code": 200,
        "chs": "成功",
        "eng": "success"
    },
    "data": {
        "pageNum": 1,
        "pageSize": 15,
        "total": 1,
        "queryResults": [
            {
                "keyInstrumentId": 1097416,
                "account": null,
                "keyOtcTradeId": 141844,
                "keyCtptyId": 10068,
                "ctptyShortName": "10068测试短名(hj专用)",
                "contractType": "EUROPEAN_VANILLA",
                "contractSubType": null,
                "direction": "CALL",
                "trdOtcContrFiles": {
                    "doubleSealedFiles": null,
                    "singleSealedFiles": null
                },
                "contrStatus": "EFFECTIVE",
                "windcode": "588000.SH",
                "windname": "科创50ETF",
                "tradeDate": "2024-07-31",
                "effectiveDate": "2024-07-31",
                "maturityDate": "2026-09-30",
                "notional": 2000000,
                "initialNotional": 2000000,
                "collateralNotional": 2000000,
                "collateralNotionalCurrency": "CNY",
                "initialUnderlyingPrice": 0.778,
                "underlyingInsId": 72283,
                "privatePlacement": false,
                "releaseDate": null,
                "strikes": [
                    {
                        "seq": 0,
                        "strikePct": 0.8222,
                        "strike": 0.6397,
                        "strikeDeltaBPs": null,
                        "strikeBelongRange": null
                    }
                ],
                "premiumRate": 0.22767,
                "premium": 455340,
                "koBarrierPct": null,
                "koBarrier": null,
                "kiBarrierPct": null,
                "kiBarrier": null,
                "hasCloseRecord": false,
                "allowCloseOut": true,
                "insFamily": "FUND",
                "appliedNotional": 0,
                "availableNotional": 2000000,
                "partitionRates": [
                    {
                        "seq": 0,
                        "participationRate": 1
                    }
                ],
                "riskBarrierPct": null,
                "riskBarrier": null,
                "contractCode": "OPT-FCS20240006"
            }
        ]
    }
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| data.queryResults.contractType | EUROPEAN_VANILLA | String | 合约类型： |
| data.queryResults.contractSubType | - | Null | 合约子类型 |
| data.queryResults.direction | CALL | String | 合约方向 |
| data.queryResults.privatePlacement | false | Boolean | 是否限售 |
| data.queryResults.trdOtcContrFiles.doubleSealedFiles | - | Null | 双章文件 |
| data.queryResults.trdOtcContrFiles.singleSealedFiles | - | Null | 单章文件 |
| data.queryResults.contrStatus | EFFECTIVE | String | 合约状态 |
| data.queryResults.strikes.strikePct | 0.8222 | Number | 执行价格 |
| data.queryResults.windname | 科创50ETF | String | 标的名称 |
| data.queryResults.tradeDate | 2024-07-31 | String | 交易达成日 |
| data.queryResults.riskBarrierPct | - | Null | 风险障碍价比例 |
| data.queryResults.riskBarrier | - | Null | 风险障碍价 |
| data.queryResults.notional | 2000000 | Number | 名义本金 |
| data.queryResults.initialNotional | 2000000 | Number | 期初名义本金(CNY) |
| data.queryResults.collateralNotional | 2000000 | Number | 下单金额(CNY) |
| data.queryResults.contractType | EUROPEAN_VANILLA | String | - |
| data.queryResults.contractSubType | - | Null | - |
| data.queryResults.direction | CALL | String | - |
| data.queryResults.trdOtcContrFiles | - | Object | - |
| data.queryResults.trdOtcContrFiles.doubleSealedFiles | - | Null | - |
| data.queryResults.trdOtcContrFiles.singleSealedFiles | - | Null | - |
| data.queryResults.contrStatus | EFFECTIVE | String | - |
| data.queryResults.windcode | 588000.SH | String | - |
| data.queryResults.windname | 科创50ETF | String | - |
| data.queryResults.tradeDate | 2024-07-31 | String | - |
| data.queryResults.effectiveDate | 2024-07-31 | String | - |
| data.queryResults.maturityDate | 2026-09-30 | String | - |
| data.queryResults.notional | 2000000 | Number | - |
| data.queryResults.initialNotional | 2000000 | Number | - |
| data.queryResults.collateralNotional | 2000000 | Number | - |
| data.queryResults.collateralNotionalCurrency | CNY | String | - |
| data.queryResults.initialUnderlyingPrice | 0.778 | Number | - |
| data.queryResults.underlyingInsId | 72283 | Number | - |
| data.queryResults.privatePlacement | false | Boolean | - |
| data.queryResults.releaseDate | - | Null | - |
| data.queryResults.strikes | - | Array | - |
| data.queryResults.strikes.seq | 0 | Number | - |
| data.queryResults.strikes.strikePct | 0.8222 | Number | - |
| data.queryResults.strikes.strike | 0.6397 | Number | - |
| data.queryResults.strikes.strikeDeltaBPs | - | Null | - |
| data.queryResults.strikes.strikeBelongRange | - | Null | - |
| data.queryResults.premiumRate | 0.22767 | Number | - |
| data.queryResults.premium | 455340 | Number | - |
| data.queryResults.koBarrierPct | - | Null | - |
| data.queryResults.koBarrier | - | Null | - |
| data.queryResults.kiBarrierPct | - | Null | - |
| data.queryResults.kiBarrier | - | Null | - |
| data.queryResults.hasCloseRecord | false | Boolean | - |
| data.queryResults.allowCloseOut | true | Boolean | - |
| data.queryResults.insFamily | FUND | String | - |
| data.queryResults.appliedNotional | 0 | Number | - |
| data.queryResults.availableNotional | 2000000 | Number | - |
| data.queryResults.partitionRates | - | Array | - |
| data.queryResults.partitionRates.seq | 0 | Number | - |
| data.queryResults.partitionRates.participationRate | 1 | Number | - |
| data.queryResults.riskBarrierPct | - | Null | - |
| data.queryResults.riskBarrier | - | Null | - |
| data.queryResults.contractCode | OPT-FCS20240006 | String | - |

* 失败(404)

```javascript
暂无数据
```


## 场外期权平仓

**接口URL**

> /api/internal/agent/option/order/close

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10821094351495088@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |
| agentsubid | 1688855175747584 | string | 是 | 智能体对客身份子ID（针对微信渠道，指用户ID） |

**请求Body参数**

```javascript
{
    "notionalDelta": 10000,
    "algoType": "LIMIT",
    "price": 15.1,
    "povRatio": null,
    "algoStartTime": null,
    "algoEndTime": null,
    "contractCode": "OPTG-SZZSCF20250030"
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| notionalDelta | 10000 | Number | 是 | 平仓名义本金 |
| algoType | LIMIT | String | 是 | 平仓价格方式，LIMIT, MARKET, POV, TWAP |
| price | 15.1 | Number | 是 | 价格 |
| povRatio | - | Null | 是 | pov比例 |
| algoStartTime | - | Null | 是 | 算法开始时间 |
| algoEndTime | - | Null | 是 | 算法结束时间 |
| contractCode | OPTG-SZZSCF20250030 | String | 是 | 合约编号 |

**响应示例**

* 成功(200)

```javascript
{
    "errMsg": null,
    "errCode": {
        "code": 200,
        "chs": "成功",
        "eng": "success"
    },
    "data": {
        "keyStockOrderId": 123456,
        "hint": null
    }
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| errMsg | - | Null | - |
| errCode | - | Object | - |
| errCode.code | 200 | Number | - |
| errCode.chs | 成功 | String | - |
| errCode.eng | success | String | - |
| data | - | String | 返回数据 |
| data.keyStockOrderId | 123456 | Number | 订单编号 |
| data.hint | - | Null | 提示 |

* 失败(404)

```javascript
暂无数据
```


## 期权平仓订单查询接口

**接口URL**

> /api/internal/agent/option/order/close/query

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10821094351495088@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |

**请求Body参数**

```javascript
{
    "filter": {
        // "contractType": "EUROPEAN_VANILLA",
        "tradeDate": "2026-02-04"
    },
    "pageNum": 1,
    "pageSize": 0
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| filter | - | Object | 是 | - |
| filter.contractType | EUROPEAN_VANILLA | String | 否 | 期权类型，EUROPEAN_VANILLA,AUTOCALL,PARTICIPATORY |
| filter.tradeDate | 2026-01-28 | String | 是 | - |
| pageNum | 1 | Number | 是 | - |
| pageSize | 100 | Number | 是 | - |

**响应示例**

* 成功(200)

```javascript
{
    "errMsg": null,
    "errCode": {
        "code": 200,
        "chs": "成功",
        "eng": "success"
    },
    "data": {
        "pageNum": 1,
        "pageSize": 100,
        "total": 1,
        "queryResults": [
            {
                "tradeTime": "2026-01-28 16:58:50",
                "tradeDate": "2026-01-28",
                "keyContractInstId": 1097416,
                "contractCode": "OPT-FCS20240006",
                "underlyingInsId": 72283,
                "windCode": "588000.SH",
                "windName": "科创50ETF",
                "tradeDirection": "SELL",
                "notionalDelta": 1000000,
                "algoType": null,
                "povRatio": null,
                "algoStartTime": null,
                "algoEndTime": null,
                "closeOutType": "PARTIAL_TERMINATION",
                "contractType": "EUROPEAN_VANILLA",
                "contractSubType": null,
                "stockOrderStatus": "OTC_VERIFYING_TOAUDIT",
                "price": 1,
                "openPositionType": "LIMIT",
                "allowWithdraw": true,
                "keyCtptyId": 10068,
                "keyStockOrderId": 1147654,
                "dealNotional": null,
                "dealPrice": null,
                "orderTakingTime": null,
                "orderCompletedTime": null,
                "goatsPositionQueryDto": {
                    "keyInstrumentId": 1097416,
                    "account": null,
                    "keyOtcTradeId": 141844,
                    "keyCtptyId": 10068,
                    "ctptyShortName": null,
                    "contractType": "EUROPEAN_VANILLA",
                    "contractSubType": null,
                    "direction": "CALL",
                    "trdOtcContrFiles": {
                        "internalTradeId": null,
                        "keyOTCTradeId": 141844,
                        "complianceReportFiles": "",
                        "doubleSealedFiles": "",
                        "singleSealedFiles": "",
                        "attachments": "",
                        "createdDateTime": "2024-08-02 16:56:10",
                        "createdBy": "dongshengli",
                        "updatedDateTime": "2024-09-13 17:59:10",
                        "updatedBy": "SYSTEM",
                        "tradeConfirmationFiles": "",
                        "otherSideFiles": "",
                        "unsealedTradeConfirmationFiles": "",
                        "productManualFiles": ""
                    },
                    "contrStatus": "EFFECTIVE",
                    "windcode": "588000.SH",
                    "windname": "科创50ETF",
                    "tradeDate": "2024-07-31",
                    "effectiveDate": "2024-07-31",
                    "maturityDate": "2026-09-30",
                    "notional": 2000000,
                    "initialNotional": 2000000,
                    "collateralNotional": 2000000,
                    "collateralNotionalCurrency": "CNY",
                    "initialUnderlyingPrice": 0.778,
                    "underlyingInsId": 72283,
                    "privatePlacement": false,
                    "releaseDate": null,
                    "strikes": [
                        {
                            "seq": 0,
                            "strikePct": 0.8222,
                            "strike": 0.6397,
                            "strikeDeltaBPs": null,
                            "strikeBelongRange": null
                        }
                    ],
                    "premiumRate": 0.22767,
                    "premium": 455340,
                    "koBarrierPct": null,
                    "koBarrier": null,
                    "kiBarrierPct": null,
                    "kiBarrier": null,
                    "hasCloseRecord": false,
                    "allowCloseOut": true,
                    "insFamily": "FUND",
                    "appliedNotional": 1000000,
                    "availableNotional": 1000000,
                    "partitionRates": [
                        {
                            "seq": 0,
                            "participationRate": 1
                        }
                    ],
                    "riskBarrierPct": null,
                    "riskBarrier": null,
                    "contractCode": "OPT-FCS20240006"
                },
                "clientExecutedPercentage": 0
            }
        ]
    }
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| data.queryResults.trdGoatsOptionOrder.underlyingWindName | 深科技 | String | 标的名称 |
| data.queryResults.trdGoatsOptionOrder.orderTakingTime | - | Null | 接单时间 |
| data.queryResults.trdGoatsOptionOrder.orderCompletedTime | - | Null | 完成时间 |
| data.queryResults.stockOrderCode | OPTG-SZJCZJ202508260002 | String | trading订单orderCode |
| data.queryResults.dealNotional | - | Null | 成交名义本金 |
| data.queryResults.dealPrice | - | Null | 成交价格 |
| data.queryResults.tradeTime | 2025-08-26 19:30:44 | String | 下单时间 |
| data.queryResults.orderTakingTime | - | Null | 接单时间 |
| data.queryResults.orderCompletedTime | - | Null | 完成时间 |
| data.queryResults.allowWithdraw | false | Boolean | 允许撤单 |
| data.queryResults.remark | 抱歉，当前不在接单时间 | String | 备注 |
| data.queryResults.rfqQuotaMode | - | Null | 询价模式，SHAREABLE, NON_SHAREABLE |
| data.queryResults.clientExecutedPercentage | 0 | Number | 成交进度 |
| data.queryResults.trdGoatsOptionOrder.gftUsername | chenyikun | String | 广发通用户名 |
| data.queryResults.trdGoatsOptionOrder.underlyingWindCode | 000021.SZ | String | 标的代码 |
| data.queryResults.trdGoatsOptionOrder.tradeTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.trdGoatsOptionOrder.orderTakingTime | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.orderCompletedTime | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.dealNotional | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.dealPrice | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.createdDateTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.trdGoatsOptionOrder.createdBy | SYSTEM | String | - |
| data.queryResults.trdGoatsOptionOrder.updatedDateTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.trdGoatsOptionOrder.updatedBy | SYSTEM | String | - |
| data.queryResults.trdGoatsOptionOrder.optOrderId | f1171d83080845a3a8d7dac32f5be4c7 | String | - |
| data.queryResults.trdGoatsOptionOrder.keyCtptyId | 15912 | Number | - |
| data.queryResults.trdGoatsOptionOrder.ctptyName | 15912测试账户 | String | - |
| data.queryResults.trdGoatsOptionOrder.account | 13918 | Number | 账户 |
| data.queryResults.trdGoatsOptionOrder.gftUsername | chenyikun | String | - |
| data.queryResults.trdGoatsOptionOrder.underlyingWindCode | 000021.SZ | String | - |
| data.queryResults.trdGoatsOptionOrder.underlyingWindName | 深科技 | String | - |
| data.queryResults.trdGoatsOptionOrder.tradeDirection | BUY | String | 交易方向，BUY |
| data.queryResults.trdGoatsOptionOrder.timeToMaturity | 1M | String | 期限 |
| data.queryResults.trdGoatsOptionOrder.orderStatus | OTC_REJECTED | String | - |
| data.queryResults.trdGoatsOptionOrder.customerId | 5414 | String | - |
| data.queryResults.trdGoatsOptionOrder.customerPhone | 13902214901 | String | - |
| data.queryResults.trdGoatsOptionOrder.keyRFQId | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.feedbackType | MID_END | String | - |
| data.queryResults.trdGoatsOptionOrder.premium | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.initialMargin | - | Null | - |
| data.queryResults.trdGoatsOptionOrder.quotationOrderType | QUOTATION_FILE | String | 下单方式，QUOTATION_FILE |
| data.queryResults.trdGoatsOptionStructure | - | Object | - |
| data.queryResults.trdGoatsOptionStructure.keyTrdGoatsOptionOrderId | f1171d83080845a3a8d7dac32f5be4c7 | String | - |
| data.queryResults.trdGoatsOptionStructure.initialMarginRatio | 0 | Number | - |
| data.queryResults.trdGoatsOptionStructure.estimatePremium | 206000 | Number | - |
| data.queryResults.trdGoatsOptionStructure.estimateMargin | 0 | Number | - |
| data.queryResults.trdGoatsOptionStructure.estimateCoupon | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.initialUnderlyingPrice | 21 | Number | - |
| data.queryResults.trdGoatsOptionStructure.contractType | EUROPEAN_VANILLA | String | 期权类型，EUROPEAN_VANILLA,AUTOCALL,PARTICIPATORY |
| data.queryResults.trdGoatsOptionStructure.contractSubType | - | Null | 期权子类型 |
| data.queryResults.trdGoatsOptionStructure.startObservationDate | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.underlyingInsId | 54344 | Number | - |
| data.queryResults.trdGoatsOptionStructure.initialNotional | 1000000 | Number | - |
| data.queryResults.trdGoatsOptionStructure.createdDateTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.trdGoatsOptionStructure.createdBy | SYSTEM | String | - |
| data.queryResults.trdGoatsOptionStructure.updatedDateTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.trdGoatsOptionStructure.updatedBy | SYSTEM | String | - |
| data.queryResults.trdGoatsOptionStructure.direction | CALL | String | 期权方向，CALL |
| data.queryResults.trdGoatsOptionStructure.strikePct | 0.8 | Number | 执行价格，小数 |
| data.queryResults.trdGoatsOptionStructure.participationRate | 1 | Number | - |
| data.queryResults.trdGoatsOptionStructure.premiumRate | 0.206 | Number | 期权费率 |
| data.queryResults.trdGoatsOptionStructure.kiBarrierPct | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.koBarrierPct | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.maximumLossLevel | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.annualizedCouponRate | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.openPositionType | TWAP | String | 建仓方式，LIMIT_PRICE, MARKET_PRICE, TWAP, POV |
| data.queryResults.trdGoatsOptionStructure.algorithmOrderVol | - | Null | pov比例-当建仓方式为【POV】时必填,范围：0.01-0.25 |
| data.queryResults.trdGoatsOptionStructure.algorithmOrderStartTime | 2025-08-26 10:00:00 | String | 算法起始时刻,当建仓方式为【TWAP】时必填，YYYY-MM-DD HH:mm:ss |
| data.queryResults.trdGoatsOptionStructure.algorithmOrderEndTime | 2025-08-26 20:00:00 | String | 算法终止时刻,当建仓方式为【TWAP】时必填，YYYY-MM-DD HH:mm:ss |
| data.queryResults.trdGoatsOptionStructure.stepDown | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.cappedPricePct | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.rfqType | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.riskBarrierPct | - | Null | - |
| data.queryResults.trdGoatsOptionStructure.insFamily | EQUITY | String | - |
| data.queryResults.goatsContractInfo | - | Object | - |
| data.queryResults.goatsContractInfo.keyOTCTradeId | - | Null | - |
| data.queryResults.goatsContractInfo.keyInstrumentId | - | Null | - |
| data.queryResults.goatsContractInfo.contractType | - | Null | 期权类型，EUROPEAN_VANILLA,AUTOCALL,PARTICIPATORY |
| data.queryResults.goatsContractInfo.contractSubType | - | Null | 期权子类型 |
| data.queryResults.goatsContractInfo.direction | - | Null | 期权方向，CALL |
| data.queryResults.goatsContractInfo.strikePct | - | Null | 执行价格，小数 |
| data.queryResults.goatsContractInfo.premiumRate | - | Null | 期权费率 |
| data.queryResults.goatsContractInfo.notional | - | Null | - |
| data.queryResults.goatsContractInfo.collateralNotional | - | Null | 下单金额 |
| data.queryResults.goatsContractInfo.initialNotional | - | Null | - |
| data.queryResults.goatsContractInfo.premium | - | Null | - |
| data.queryResults.goatsContractInfo.annualizedCouponRate | - | Null | - |
| data.queryResults.goatsContractInfo.coupon | - | Null | - |
| data.queryResults.goatsContractInfo.kiBarrierPct | - | Null | - |
| data.queryResults.goatsContractInfo.koBarrierPct | - | Null | - |
| data.queryResults.goatsContractInfo.contrStatus | - | Null | - |
| data.queryResults.goatsContractInfo.initialUnderlyingPrice | - | Null | - |
| data.queryResults.goatsContractInfo.contractCode | - | Null | - |
| data.queryResults.stockOrderCode | OPTG-SZJCZJ202508260002 | String | - |
| data.queryResults.dealNotional | - | Null | - |
| data.queryResults.dealPrice | - | Null | - |
| data.queryResults.tradeTime | 2025-08-26 19:30:44 | String | - |
| data.queryResults.orderTakingTime | - | Null | - |
| data.queryResults.orderCompletedTime | - | Null | - |
| data.queryResults.allowWithdraw | false | Boolean | - |
| data.queryResults.remark | 抱歉，当前不在接单时间 | String | - |
| data.queryResults.rfqQuotaMode | - | Null | - |
| data.queryResults.clientExecutedPercentage | 0 | Number | - |

* 失败(404)

```javascript
暂无数据
```


## 场外期权平仓订单撤单

**接口URL**

> /api/internal/agent/option/order/close/withdraw

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10821094351495088@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |
| agentsubid | 1688855175747584 | string | 是 | 智能体对客身份子ID（针对微信渠道，指用户ID） |

**请求Body参数**

```javascript
{
    "keyStockOrderId": 1150076
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| keyCtptyId | 10068 | Number | 否 | - |
| keyStockOrderId | 1147654 | Number | 是 | 订单id |

**响应示例**

* 成功(200)

```javascript
{
    "errMsg": null,
    "errCode": {
        "code": 200,
        "chs": "成功",
        "eng": "success"
    },
    "data": {
        "stockOrderCode": "OPTG-FCS202601280001",
        "withdrawResult": null,
        "failureMsg": null,
        "completed": false
    }
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| data | xxx | String | 撤单编号 |
| errCode | - | Object | - |
| errCode.chs | 成功 | String | - |
| errCode.code | 200 | Number | - |
| errCode.eng | success | String | - |
| errMsg | 1个定价指标计算存在异常 | Null | - |
| serviceId | 1234455 | String | - |
| timestamp | 0 | Number | - |

* 失败(404)

```javascript
暂无数据
```


## 场外期权平仓撤单结果查询【轮询】 

**接口URL**

> /api/internal/agent/option/order/close/withdrawResult?stockOrderCode=OPTG-SZZSCF202602040001

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> GET

**Content-Type**

> none

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10821094351495088@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |
| agentsubid | - | string | 是 | 智能体对客身份子ID（针对微信渠道，指用户ID） |

**请求Query参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| stockOrderCode | OPTG-SZZSCF202602040001 | string | 是 | - |

**响应示例**

* 成功(200)

```javascript
{
    "errMsg": null,
    "errCode": {
        "code": 200,
        "chs": "成功",
        "eng": "success"
    },
    "data": {
        "stockOrderCode": "OPTG-FCS202601280001",
        "withdrawResult": null,
        "failureMsg": null,
        "completed": false
    }
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| data | - | String | - |
| data.completed | true | Boolean | 撤单审核进度，true-完成，false-未完成 |
| data.failureMsg | string | String | 失败信息 |
| data.stockOrderCode | string | String | 撤单编号 |
| data.withdrawResult | SUCCESS | String | 撤单结果，SUCCESS, FAILURE, PENDING_CANCEL |
| errCode | - | Object | - |
| errCode.chs | 成功 | String | - |
| errCode.code | 200 | Number | - |
| errCode.eng | success | String | - |
| errMsg | 1个定价指标计算存在异常 | Null | - |
| serviceId | string | String | - |
| timestamp | 0 | Number | - |

* 失败(404)

```javascript
暂无数据
```


# 收益互换


## 收益互换下单

**接口URL**

> /api/internal/agent/trs/order

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10821094351495088@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |
| agentsubid | 1688855175747584 | string | 是 | 智能体对客身份子ID（针对微信渠道，指用户ID） |

**请求Body参数**

```javascript
{
    "transactionType": "US_STOCK",
    "orderType": "BY_QTY",  // 按数量BY_QTY / 按金额BY_NOTIONAL
    "quantity": 200,
    "windCode": "TSLA.O", // 标的代码
    "price": 1,
    "priceType": "LimitOrder",
    "orderDirection": "BUY",
    "shortName": "11125测试短名（张天琪专用）",
    "premarket": true,
    "maxVol": 0.01,
    "algorithmType": "TWAP",
    "startTime": "2026-04-13 17:00:00",
    "endTime": "2026-04-14 04:00:00",
    "fixPrice": 100 // 算法单限报价格
    //"notional": 1000000,  // 下单金额
    //"notionalCurrency": "HKD", // 下单币种 CNY/HKD/USD/EUR/GBP/AUD
    //"currency": "HKD" // 标的币种 CNY/HKD/USD/EUR/GBP/AUD
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| transactionType | US_STOCK | String | 是 | - |
| orderType | BY_QTY | String | 是 | 按数量BY_QTY / 按金额BY_NOTIONAL |
| quantity | 200 | Number | 是 | - |
| windCode | TSLA.O | String | 是 | 标的代码 |
| price | 1 | Number | 否 | 价格 |
| priceType | LimitOrder | String | 是 | 价格类型，见PRICE_TYPE_TEXT |
| orderDirection | BUY | String | 是 | 委托方向，见ORDER_DIRECTION_TEXT |
| shortName | 11125测试短名（张天琪专用） | Null | 是 | 交易对手简称 |
| premarket | true | Boolean | 否 | 是否盘前交易，是-true/否-false |
| maxVol | 0.01 | Number | 否 | 最大成交量比例 (0.01-1.00)，TWAP/VWAP选传 |
| algorithmType | TWAP | String | 否 | 算法 |
| startTime | 2026-04-13 17:00:00 | String | 否 | - |
| endTime | 2026-04-14 04:00:00 | String | 否 | - |
| fixPrice | 100 | Number | 否 | 算法单限报价格 |

**响应示例**

* 成功(200)

```javascript
{
	"errMsg": null,
	"errCode": {
		"code": 200,
		"chs": "提交成功",
		"eng": "SUCCESS_SUBMIT"
	},
	"data": {
		"result": true,
		"keyOrderId": 972871,
		"errMsg": null,
		"async": false,
		"keyCtptyId": 10011,
		"transactionType": "HK_STOCK",
		"orderCode": "CSC202509190004"
	}
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| errMsg | - | Null | - |
| errCode | - | Object | - |
| errCode.code | 200 | Number | 非200表示提交 |
| errCode.chs | 成功 | String | - |
| errCode.eng | success | String | - |
| data | - | String | 返回数据 |
| data.result | true | Boolean | 下单结果，true-提交成功，false-提交失败，只轮询为true的订单 |
| data.keyOrderId | 971891 | Number | 订单id |
| data.errMsg | - | Null | 错误信息 |
| data.async | true | Boolean | 订单异步处理结果，如果不为true，则订单全部失败，不用轮询 |
| data.keyCtptyId | 11616 | Number | 交易对手 |
| data.transactionType | SZ_HK_CONNECT | String | 交易品种，见TRANSACTION_TYPE_TEXT |
| data.orderCode | - | Null | 订单编号 |

* 失败(404)

```javascript
暂无数据
```


## 收益互换下单状态查询接口【轮询】

**接口URL**

> /api/internal/agent/trs/order/status

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 50416275477@chatroom | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |

**请求Body参数**

```javascript
[
  {
    "keyOrderId": 972871,
    "transactionType": "HK_STOCK"
  }
]
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| keyOrderIdList | - | Array | 是 | 订单列表 |

**响应示例**

* 成功(200)

```javascript
{
	"errMsg": null,
	"errCode": {
		"code": 200,
		"chs": "查询成功",
		"eng": "SUCCESS_QUERY"
	},
	"data": [
		{
			"keyCtptyId": 10011,
			"success": true,
			"failureMsg": null,
			"keyStockOrderId": 972871,
			"submitResultUuid": null,
			"serialNo": null,
			"transactionType": "HK_STOCK",
			"completed": true
		}
	]
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| errMsg | - | string | - |
| errCode | - | Object | - |
| errCode.code | 200 | Number | - |
| errCode.chs | 成功 | String | - |
| errCode.eng | success | String | - |
| data | - | Object | 订单ID |
| data.success | - | boolean | 成功响应 |
| data.failureMsg | - | string | 失败信息 |
| data.keyStockOrderId | - | integer | 订单id |
| data.completed | false | Boolean | false、true，true代表审核通过，已下单 |

* 失败(404)

```javascript
暂无数据
```


## 收益互换下单/撤单结果查询接口【轮询】

**接口URL**

> /api/internal/agent/trs/order/query

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 50416275477@chatroom | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |

**请求Body参数**

```javascript
{
    // "keyOrderIdList": [
    //     972871
    // ]
    "ultraContractCode": "CSC-CST-多空组合-0004"
    // "orderCode": "TRS-CSC202509190003"
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| keyOrderIdList | - | Array | 是 | 订单id列表 |
| ultraContractCode | GFGCX-CST-多空组合-0013 | String | 是 | 大合约编号 |

**响应示例**

* 成功(200)

```javascript
{
	"errMsg": null,
	"errCode": {
		"code": 200,
		"chs": "查询成功",
		"eng": "SUCCESS_QUERY"
	},
	"data": [
		{
			"keyCapAcctId": 10011,
			"keyOrderId": 972873,
			"orderCode": "CSC202509190005",
			"orderDate": "2025-09-19",
			"entrustDate": null,
			"entrustTime": "2025-09-19 10:25:37",
			"keyCtptyId": 10011,
			"ctptyShortName": "10011测试短名",
			"ctptyLongName": "10011测试长名",
			"nameAbbreviation": "CSC",
			"windCode": "0700.HK",
			"insShtDesc": "腾讯控股",
			"keyInstrumentId": 81825,
			"price": 19,
			"fixPrice": null,
			"quantity": 2300,
			"orderDirection": "BUY",
			"priceType": "LimitOrder",
			"algorithmType": "STRAIGHT_LIMIT_ORDER",
			"povPercent": 0.1,
			"maxVol": null,
			"startTime": "2025-09-19 11:00:00",
			"endTime": "2025-09-19 14:00:00",
			"orderStatus": "CANCELED",
			"filledQty": 1100,
			"avgPrice": 19.3,
			"execAmount": 21230,
			"entrustAmount": 43700,
			"displayQty": null,
			"displayQtyUnit": null,
			"displayQtyVariance": null,
			"frequency": null,
			"currency": "HKD",
			"keyOtcspAuthUserId": "25984984046215440@openim",
			"authUserName": "陶艳红",
			"phoneNo": "00000000000",
			"tradeChannel": "GOATS",
			"tradingModel": "LOW_TOUCH",
			"businessRemark": null,
			"remark": "改单: 原委托#CSC202509190004#已撤单，生成新委托",
			"uniqueId": "5b3b586a-c692-4018-9354-e34cfc68fac3",
			"canWithdraw": false,
			"updatedDateTime": null,
			"fixPriceType": "BidPrice_5",
			"serialNo": null,
			"createdDateTime": "2025-09-19 10:25:37",
			"withdrawQty": 1200,
			"exchangeMarket": "HKEX",
			"transactionType": "HK_STOCK",
			"eqRecallType": null,
			"keyPlanId": 12040,
			"ultraContractCode": "CSC-CST-多空组合-0004",
			"planCode": "GFZQ-CSC-MARGINCB-0004",
			"premarket": null,
			"priceLimitType": null,
			"canReplace": false,
			"orderType": "BY_QTY",
			"notional": null,
			"notionalCurrency": null,
			"emsxSequenceNo": null,
			"cumulateUnmatchedQty": null,
			"enableLimitPrice": null,
			"subOrderQty": null,
			"priceDiffInTick": null,
			"triggerTimeIntervalSeconds": null,
			"cancelTimeIntervalSeconds": null,
			"maxCancelOrderTimes": null
		},
		{
			"keyCapAcctId": 10011,
			"keyOrderId": 972871,
			"orderCode": "CSC202509190004",
			"orderDate": "2025-09-19",
			"entrustDate": null,
			"entrustTime": "2025-09-19 10:21:23",
			"keyCtptyId": 10011,
			"ctptyShortName": "10011测试短名",
			"ctptyLongName": "10011测试长名",
			"nameAbbreviation": "CSC",
			"windCode": "0700.HK",
			"insShtDesc": "腾讯控股",
			"keyInstrumentId": 81825,
			"price": 18,
			"fixPrice": null,
			"quantity": 3100,
			"orderDirection": "BUY",
			"priceType": "LimitOrder",
			"algorithmType": "POV",
			"povPercent": 0.1,
			"maxVol": null,
			"startTime": "2025-09-19 10:50:00",
			"endTime": "2025-09-19 14:00:00",
			"orderStatus": "CANCELED",
			"filledQty": 0,
			"avgPrice": 0,
			"execAmount": 0,
			"entrustAmount": 55800,
			"displayQty": null,
			"displayQtyUnit": null,
			"displayQtyVariance": null,
			"frequency": null,
			"currency": "HKD",
			"keyOtcspAuthUserId": "25984984046215440@openim",
			"authUserName": "陶艳红",
			"phoneNo": "00000000000",
			"tradeChannel": "GOATS",
			"tradingModel": "LOW_TOUCH",
			"businessRemark": null,
			"remark": "改单: 撤单成功，生成新委托#CSC202509190005#",
			"uniqueId": "349252-64236b53-c652-4b42-a515-dd42dcf7b6b0",
			"canWithdraw": false,
			"updatedDateTime": null,
			"fixPriceType": null,
			"serialNo": null,
			"createdDateTime": "2025-09-19 10:21:23",
			"withdrawQty": 3100,
			"exchangeMarket": "HKEX",
			"transactionType": "HK_STOCK",
			"eqRecallType": null,
			"keyPlanId": 12040,
			"ultraContractCode": "CSC-CST-多空组合-0004",
			"planCode": "GFZQ-CSC-MARGINCB-0004",
			"premarket": null,
			"priceLimitType": null,
			"canReplace": false,
			"orderType": "BY_QTY",
			"notional": null,
			"notionalCurrency": null,
			"emsxSequenceNo": null,
			"cumulateUnmatchedQty": null,
			"enableLimitPrice": null,
			"subOrderQty": null,
			"priceDiffInTick": null,
			"triggerTimeIntervalSeconds": null,
			"cancelTimeIntervalSeconds": null,
			"maxCancelOrderTimes": null
		},
		{
			"keyCapAcctId": 10011,
			"keyOrderId": 972866,
			"orderCode": "CSC202509190003",
			"orderDate": "2025-09-19",
			"entrustDate": null,
			"entrustTime": "2025-09-19 10:09:59",
			"keyCtptyId": 10011,
			"ctptyShortName": "10011测试短名",
			"ctptyLongName": "10011测试长名",
			"nameAbbreviation": "CSC",
			"windCode": "0700.HK",
			"insShtDesc": "腾讯控股",
			"keyInstrumentId": 81825,
			"price": 88,
			"fixPrice": null,
			"quantity": 300,
			"orderDirection": "BUY",
			"priceType": "LimitOrder",
			"algorithmType": "POV",
			"povPercent": 0.1,
			"maxVol": null,
			"startTime": "2025-09-19 10:50:00",
			"endTime": "2025-09-19 14:00:00",
			"orderStatus": "FILLED",
			"filledQty": 300,
			"avgPrice": 86.38,
			"execAmount": 25914,
			"entrustAmount": 26400,
			"displayQty": null,
			"displayQtyUnit": null,
			"displayQtyVariance": null,
			"frequency": null,
			"currency": "HKD",
			"keyOtcspAuthUserId": "25984984046215440@openim",
			"authUserName": "陶艳红",
			"phoneNo": "00000000000",
			"tradeChannel": "GOATS",
			"tradingModel": "LOW_TOUCH",
			"businessRemark": null,
			"remark": null,
			"uniqueId": "349248-17fe643f-8fa9-4eaa-95c5-82263457bf51",
			"canWithdraw": false,
			"updatedDateTime": null,
			"fixPriceType": null,
			"serialNo": null,
			"createdDateTime": "2025-09-19 10:09:59",
			"withdrawQty": 0,
			"exchangeMarket": "HKEX",
			"transactionType": "HK_STOCK",
			"eqRecallType": null,
			"keyPlanId": 12040,
			"ultraContractCode": "CSC-CST-多空组合-0004",
			"planCode": "GFZQ-CSC-MARGINCB-0004",
			"premarket": null,
			"priceLimitType": null,
			"canReplace": false,
			"orderType": "BY_QTY",
			"notional": null,
			"notionalCurrency": null,
			"emsxSequenceNo": null,
			"cumulateUnmatchedQty": null,
			"enableLimitPrice": null,
			"subOrderQty": null,
			"priceDiffInTick": null,
			"triggerTimeIntervalSeconds": null,
			"cancelTimeIntervalSeconds": null,
			"maxCancelOrderTimes": null
		},
		{
			"keyCapAcctId": 10011,
			"keyOrderId": 972854,
			"orderCode": "CSC202509190002",
			"orderDate": "2025-09-19",
			"entrustDate": null,
			"entrustTime": "2025-09-19 09:56:16",
			"keyCtptyId": 10011,
			"ctptyShortName": "10011测试短名",
			"ctptyLongName": "10011测试长名",
			"nameAbbreviation": "CSC",
			"windCode": "0700.HK",
			"insShtDesc": "腾讯控股",
			"keyInstrumentId": 81825,
			"price": 4,
			"fixPrice": null,
			"quantity": 500,
			"orderDirection": "BUY",
			"priceType": "LimitOrder",
			"algorithmType": "STRAIGHT_LIMIT_ORDER",
			"povPercent": null,
			"maxVol": 0,
			"startTime": "2025-09-19 09:55:59",
			"endTime": "2025-09-19 16:00:00",
			"orderStatus": "FILLED",
			"filledQty": 500,
			"avgPrice": 3.98,
			"execAmount": 1990,
			"entrustAmount": 2000,
			"displayQty": null,
			"displayQtyUnit": null,
			"displayQtyVariance": null,
			"frequency": null,
			"currency": "HKD",
			"keyOtcspAuthUserId": "10002",
			"authUserName": "董胜利",
			"phoneNo": "00000000000",
			"tradeChannel": "TITANS",
			"tradingModel": "LOW_TOUCH",
			"businessRemark": null,
			"remark": "改单: 原委托#CSC202509190001#已撤单，生成新委托",
			"uniqueId": "8fad7336-93b1-4ca1-a8c1-88e5c8f1f742",
			"canWithdraw": false,
			"updatedDateTime": null,
			"fixPriceType": null,
			"serialNo": null,
			"createdDateTime": "2025-09-19 09:56:16",
			"withdrawQty": 0,
			"exchangeMarket": "HKEX",
			"transactionType": "HK_STOCK",
			"eqRecallType": null,
			"keyPlanId": 12040,
			"ultraContractCode": "CSC-CST-多空组合-0004",
			"planCode": "GFZQ-CSC-MARGINCB-0004",
			"premarket": null,
			"priceLimitType": null,
			"canReplace": false,
			"orderType": "BY_QTY",
			"notional": null,
			"notionalCurrency": null,
			"emsxSequenceNo": null,
			"cumulateUnmatchedQty": null,
			"enableLimitPrice": null,
			"subOrderQty": null,
			"priceDiffInTick": null,
			"triggerTimeIntervalSeconds": null,
			"cancelTimeIntervalSeconds": null,
			"maxCancelOrderTimes": null
		},
		{
			"keyCapAcctId": 10011,
			"keyOrderId": 972852,
			"orderCode": "CSC202509190001",
			"orderDate": "2025-09-19",
			"entrustDate": null,
			"entrustTime": "2025-09-19 09:55:33",
			"keyCtptyId": 10011,
			"ctptyShortName": "10011测试短名",
			"ctptyLongName": "10011测试长名",
			"nameAbbreviation": "CSC",
			"windCode": "0700.HK",
			"insShtDesc": "腾讯控股",
			"keyInstrumentId": 81825,
			"price": 4,
			"fixPrice": null,
			"quantity": 1100,
			"orderDirection": "BUY",
			"priceType": "LimitOrder",
			"algorithmType": "STRAIGHT_LIMIT_ORDER",
			"povPercent": null,
			"maxVol": null,
			"startTime": null,
			"endTime": null,
			"orderStatus": "CANCELED",
			"filledQty": 600,
			"avgPrice": 3.98,
			"execAmount": 2388,
			"entrustAmount": 4400,
			"displayQty": null,
			"displayQtyUnit": null,
			"displayQtyVariance": null,
			"frequency": null,
			"currency": "HKD",
			"keyOtcspAuthUserId": "10002",
			"authUserName": "董胜利",
			"phoneNo": "00000000000",
			"tradeChannel": "TITANS",
			"tradingModel": "LOW_TOUCH",
			"businessRemark": null,
			"remark": "改单: 撤单成功，生成新委托#CSC202509190002#",
			"uniqueId": "TITANS_c8e0cba3-1835-42a5-a337-0107fc167343",
			"canWithdraw": false,
			"updatedDateTime": null,
			"fixPriceType": null,
			"serialNo": null,
			"createdDateTime": "2025-09-19 09:55:33",
			"withdrawQty": 500,
			"exchangeMarket": "HKEX",
			"transactionType": "HK_STOCK",
			"eqRecallType": null,
			"keyPlanId": 12040,
			"ultraContractCode": "CSC-CST-多空组合-0004",
			"planCode": "GFZQ-CSC-MARGINCB-0004",
			"premarket": null,
			"priceLimitType": null,
			"canReplace": false,
			"orderType": "BY_QTY",
			"notional": null,
			"notionalCurrency": null,
			"emsxSequenceNo": null,
			"cumulateUnmatchedQty": null,
			"enableLimitPrice": null,
			"subOrderQty": null,
			"priceDiffInTick": null,
			"triggerTimeIntervalSeconds": null,
			"cancelTimeIntervalSeconds": null,
			"maxCancelOrderTimes": null
		}
	]
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| data.priceLimitType | NO_LIMIT | String | 限价类型 |
| data.canReplace | true | Boolean | 是否可改单 |
| data.canWithdraw | true | Boolean | 是否可撤销 |
| data.notional | - | Null | 名义本金 |
| data.notionalCurrency | - | Null | 名义本金币种 |
| data.emsxSequenceNo | - | Null | emsx订单号 |
| data.cumulateUnmatchedQty | - | Null | 未成交数量是否累计到下一轮 |
| data.enableLimitPrice | - | Null | 是否启用限价 |
| data.subOrderQty | - | Null | 单笔委托数量 |
| data.priceDiffInTick | - | Null | 价格差异(跳数) |
| data.triggerTimeIntervalSeconds | - | Null | 触发时间间隔(秒) |
| data.cancelTimeIntervalSeconds | - | Null | 撤单时间间隔(秒) |
| data.maxCancelOrderTimes | - | Null | 撤单上限 |
| data.marketType | HK | String | 市场类型 |
| data.premarket | - | Null | 是否盘前交易 |
| data.nameAbbreviation | GFGCX | String | - |
| data.windCode | 0700.HK | String | 标的代码 |
| data.insShtDesc | 腾讯控股 | String | - |
| data.keyInstrumentId | 81825 | Number | - |
| data.price | - | Null | 委托价格，可选 |
| data.fixPrice | - | Null | - |
| data.quantity | 100 | Number | 委托数量，单位：股 |
| data.orderDirection | BUY | String | 委托方向，见ORDER_DIRECTION_TEXT |
| data.priceType | LimitOrder | String | 价格类型，见PRICE_TYPE_TEXT |
| data.algorithmType | TWAP | String | 算法类型，可选，见ALGO_TYPE_TEXT |
| data.povPercent | - | Null | POV算法单必传，委托比例，小数，0.0001-1 |
| data.maxVol | - | Null | - |
| data.startTime | 2025-09-15 15:23:09 | String | 算法单开始时间 |
| data.endTime | 2025-09-15 16:00:00 | String | 算法单结束时间 |
| data.orderStatus | OTC_VERIFYING | String | - |
| data.filledQty | 0 | Number | - |
| data.avgPrice | - | Null | - |
| data.execAmount | 0 | Number | - |
| data.entrustAmount | - | Null | - |
| data.displayQty | - | Null | 可委托数量，ICEBERG算法必传 |
| data.displayQtyUnit | - | Null | - |
| data.displayQtyVariance | - | Null | - |
| data.frequency | - | Null | - |
| data.currency | HKD | String | - |
| data.keyOtcspAuthUserId | - | Null | - |
| data.authUserName | - | Null | - |
| data.phoneNo | - | Null | - |
| data.tradeChannel | GOATS | String | - |
| data.tradingModel | - | Null | - |
| data.businessRemark | - | Null | - |
| data.remark | - | Null | - |
| data.uniqueId | - | Null | - |
| data.canWithdraw | true | Boolean | - |
| data.updatedDateTime | - | Null | - |
| data.fixPriceType | LastPrice | String | - |
| data.serialNo | - | Null | - |
| data.createdDateTime | 2025-09-15 17:23:35 | String | - |
| data.withdrawQty | 100 | Number | - |
| data.exchangeMarket | HKEX | String | - |
| data.transactionType | SZ_HK_CONNECT | String | 交易品种，见TRANSACTION_TYPE_TEXT |
| data.eqRecallType | - | Null | - |
| data.keyPlanId | 10725 | Number | 履保id，// Todo |
| data.ultraContractCode | GFZQ-GFGCX-SWAP-ShortNORMAL-0001 | String | 大合约编号 |
| data.planCode | - | Null | - |
| data.premarket | - | Null | - |
| data.priceLimitType | NO_LIMIT | String | - |
| data.canReplace | true | Boolean | - |
| data.orderType | BY_QTY | String | 订单类型，默认BY_QTY |
| data.notional | - | Null | - |
| data.notionalCurrency | - | Null | - |
| data.emsxSequenceNo | - | Null | - |
| data.cumulateUnmatchedQty | - | Null | - |
| data.enableLimitPrice | - | Null | - |
| data.subOrderQty | - | Null | - |
| data.priceDiffInTick | - | Null | - |
| data.triggerTimeIntervalSeconds | - | Null | - |
| data.cancelTimeIntervalSeconds | - | Null | - |
| data.maxCancelOrderTimes | - | Null | - |
| data.marketType | HK | String | - |

* 失败(404)

```javascript
暂无数据
```


## 收益互换撤单

**接口URL**

> /api/internal/agent/trs/order/withdraw

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 50416275477@chatroom | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |
| agentsubid | 25984984046215440@openim | string | 是 | 智能体对客身份子ID（针对微信渠道，指用户ID） |

**请求Body参数**

```javascript
{
    "orderList": [972873]
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| keyStockOrderId | 271473 | Number | 是 | 订单id |

**响应示例**

* 成功(200)

```javascript
{
	"errMsg": null,
	"errCode": {
		"code": 200,
		"chs": "提交成功",
		"eng": "SUCCESS_SUBMIT"
	},
	"data": [
		{
			"keyOrderId": 972873,
			"result": true,
			"msg": "已提交撤单"
		},
		{
			"keyOrderId": 972779,
			"result": true,
			"msg": "已提交撤单"
		},
		{
			"keyOrderId": 972773,
			"result": true,
			"msg": "已提交撤单"
		}
	]
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| data | xxx | String | 撤单编号 |
| errCode | - | Object | - |
| errCode.chs | 成功 | String | - |
| errCode.code | 200 | Number | - |
| errCode.eng | success | String | - |
| errMsg | 1个定价指标计算存在异常 | Null | - |
| serviceId | 1234455 | String | - |
| timestamp | 0 | Number | - |

* 失败(404)

```javascript
暂无数据
```


## 收益互换改单

**接口URL**

> /api/internal/agent/trs/order/replace

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 50416275477@chatroom | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |
| agentsubid | 25984984046215440@openim | string | 是 | 智能体对客身份子ID（针对微信渠道，指用户ID） |

**请求Body参数**

```javascript
{
    "orderList": [
        {
            "keyOrderId": 972871,
            "priceType": "LimitOrder",
            "quantity": 2300,
            "price": 19,
            "algorithmType": "TWAP",
            "startTime": "2025-09-19 11:00:00",
            "endTime": "2025-09-19 14:00:00"
            // "povPercent": 0.1,
            // "displayQty": 100
        }
    ]
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| orderList | - | Array | 是 | - |
| orderList.keyOrderId | 972871 | Number | 是 | - |
| orderList.priceType | LimitOrder | String | 是 | - |
| orderList.quantity | 2300 | Number | 是 | - |
| orderList.price | 19 | Number | 是 | 价格 |
| orderList.algorithmType | TWAP | String | 是 | - |
| orderList.fixPriceType | BidPrice_5 | String | 否 | - |
| orderList.startTime | 2025-09-19 11:00:00 | String | 是 | - |
| orderList.endTime | 2025-09-19 14:00:00 | String | 是 | - |

**响应示例**

* 成功(200)

```javascript
{
	"errMsg": null,
	"errCode": {
		"code": 200,
		"chs": "提交成功",
		"eng": "SUCCESS_SUBMIT"
	},
	"data": [
		{
			"keyOrderId": 972871,
			"submitResult": true,
			"keyInstrumentId": 81825,
			"transactionType": "HK_STOCK",
			"orderDirection": "BUY"
		}
	]
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| data | xxx | String | 撤单编号 |
| errCode | - | Object | - |
| errCode.chs | 成功 | String | - |
| errCode.code | 200 | Number | - |
| errCode.eng | success | String | - |
| errMsg | 1个定价指标计算存在异常 | Null | - |
| serviceId | 1234455 | String | - |
| timestamp | 0 | Number | - |

* 失败(404)

```javascript
暂无数据
```


## 收益互换改单状态查询接口【轮询】 

**接口URL**

> /api/internal/agent/trs/order/replaceResults

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10942303743943955@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |

**请求Body参数**

```javascript
{
    "orderList": [973746]
}
```

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| 0 | - | Object | 是 | - |
| 0.keyOrderId | 971891 | Number | 是 | 订单id |
| 0.transactionType | SZ_HK_CONNECT | String | 是 | 交易品种，见TRANSACTION_TYPE_TEXT |

**响应示例**

* 成功(200)

```javascript
{
	"errMsg": null,
	"errCode": {
		"code": 200,
		"chs": "提交成功",
		"eng": "SUCCESS_SUBMIT"
	},
	"data": [
		{
			"keyOrderId": 972871,
			"withdrawResult": null,
			"replaceResult": "SUCCESS",
			"failureMsg": null,
			"keyInstrumentId": 81825,
			"transactionType": "HK_STOCK",
			"orderDirection": "BUY",
			"completed": true
		}
	]
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| errMsg | - | string | - |
| errCode | - | Object | - |
| errCode.code | 200 | Number | - |
| errCode.chs | 成功 | String | - |
| errCode.eng | success | String | - |
| data | - | Object | 订单ID |
| data.success | - | boolean | 成功响应 |
| data.failureMsg | - | string | 失败信息 |
| data.keyStockOrderId | - | integer | 订单id |
| data.completed | false | Boolean | false、true，true代表审核通过，已下单 |

* 失败(404)

```javascript
暂无数据
```


# 交易对手


## 企微群绑定交易对手查询

**接口URL**

> /api/internal/agent/getCtptyListByChatRoomId?type=TRS

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> GET

**Content-Type**

> none

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |
| agentid | 10821094351495088@tl | string | 是 | 智能体对客身份ID（针对微信渠道，指群ID） |

**请求Query参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| type | TRS | string | 是 | 业务类型，TRS-互换，OPTION-期权 |

**响应示例**

* 成功(200)

```javascript
{
	"errMsg": null,
	"errCode": {
		"code": 200,
		"chs": "查询成功",
		"eng": "SUCCESS_QUERY"
	},
	"data": [
		{
			"ctptyId": 10049,
			"shortName": "临沂阿凡提",
			"longName": "上海猎鲸志投资管理有限公司",
			"groupFlag": "N",
			"transactionTypeList": [
				"HK_STOCK",
				"US_STOCK",
				"JP_STOCK",
				"KR_STOCK",
				"CROSS_OTHER",
				"CROSS_FUTURE",
				"A_SHARE"
			]
		},
		{
			"ctptyId": 10833,
			"shortName": "10833测试短名(yxd专用)",
			"longName": "10833测试产品",
			"groupFlag": "N",
			"transactionTypeList": [
				"HK_STOCK",
				"US_STOCK",
				"JP_STOCK",
				"KR_STOCK",
				"CROSS_OTHER",
				"CROSS_FUTURE",
				"A_SHARE"
			]
		},
		{
			"ctptyId": 11125,
			"shortName": "11125测试短名（张天琪专用）",
			"longName": "吕测试企业-Ukey",
			"groupFlag": "N",
			"transactionTypeList": [
				"HK_STOCK",
				"US_STOCK",
				"JP_STOCK",
				"KR_STOCK",
				"CROSS_OTHER",
				"CROSS_FUTURE",
				"A_SHARE"
			]
		},
		{
			"ctptyId": 15576,
			"shortName": "测试111",
			"longName": "生命二号zk22",
			"groupFlag": "N",
			"transactionTypeList": [
				"HK_STOCK",
				"US_STOCK",
				"JP_STOCK",
				"KR_STOCK",
				"CROSS_OTHER",
				"CROSS_FUTURE",
				"A_SHARE"
			]
		},
		{
			"ctptyId": 16502,
			"shortName": "23",
			"longName": "323",
			"groupFlag": "Y",
			"transactionTypeList": [
				"HK_STOCK",
				"US_STOCK",
				"JP_STOCK",
				"KR_STOCK",
				"CROSS_OTHER"
			]
		},
		{
			"ctptyId": 16508,
			"shortName": "10011账户组测试短名",
			"longName": "10011账户组测试长名",
			"groupFlag": "Y",
			"transactionTypeList": [
				"HK_STOCK",
				"US_STOCK",
				"JP_STOCK",
				"KR_STOCK",
				"CROSS_OTHER"
			]
		}
	]
}
```

| 参数名 | 示例值 | 参数类型 | 参数描述 |
| --- | --- | ---- | ---- |
| errMsg | - | string | - |
| errCode | - | Object | - |
| errCode.code | 200 | Number | - |
| errCode.chs | 提交成功 | String | - |
| errCode.eng | SUCCESS_SUBMIT | String | - |
| data | - | Object | - |
| data.ctptyId | 11125 | Number | 交易对手ID |
| data.shortName | 11125测试短名（张天琪专用） | String | 交易对手简称 |
| data.longName | 招商证券 | String | 交易对手全称 |
| data.groupFlag | N | String | 是否账户组，Y-是，N- |

* 失败(404)

```javascript
{
	"errMsg": "参数业务类型不合法！",
	"errCode": {
		"code": 400,
		"chs": "请求失败",
		"eng": "FAIL_REQUEST"
	},
	"data": null
}
```


# 投管系统

## 互换交易时间配置查询

**接口URL**

> /api/uniweb/rpa/trs/tradingHoursConfig

| 环境  | URL |
| --- | --- |
| tst | http://tstgoats.gf.com.cn |

**请求方式**

> GET

**Content-Type**

> none

**请求Header参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| agenttype | WECHAT | string | 是 | 智能体对客类型 |

**响应示例**

* 成功(200)

```javascript
{
  "errMsg": null,
  "errCode": {
    "code": 200,
    "chs": "成功",
    "eng": "success"
  },
  "data": [
    {
      "transactionType": "SZ_HK_CONNECT",
      "tradingHoursStart": "2026-04-30 08:30:00",
      "tradingHoursEnd": "2026-04-30 20:10:00",
      "region": null,
      "exchangeList": null
    },
    {
      "transactionType": "SH_HK_CONNECT",
      "tradingHoursStart": "2026-04-30 08:30:00",
      "tradingHoursEnd": "2026-04-30 20:10:00",
      "region": null,
      "exchangeList": null
    },
    {
      "transactionType": "A_SHARE",
      "tradingHoursStart": "2026-04-30 08:30:00",
      "tradingHoursEnd": "2026-04-30 20:00:00",
      "region": null,
      "exchangeList": null
    },
    {
      "transactionType": "HK_STOCK",
      "tradingHoursStart": "2026-04-30 08:30:00",
      "tradingHoursEnd": "2026-04-30 20:10:00",
      "region": null,
      "exchangeList": null
    },
    {
      "transactionType": "US_STOCK",
      "tradingHoursStart": "2026-04-30 09:00:00",
      "tradingHoursEnd": "2026-05-01 05:00:00",
      "region": null,
      "exchangeList": null,
      "premarketTradingHoursStart": "2026-04-30 21:30:00"
    },
    {
      "transactionType": "CROSS_FUTURE",
      "tradingHoursStart": "2026-04-30 09:00:00",
      "tradingHoursEnd": "2026-04-30 22:30:00",
      "region": "ASIA_PACIFIC",
      "exchangeList": ["HKEX", "SGX", "OSE"]
    },
    {
      "transactionType": "CROSS_FUTURE",
      "tradingHoursStart": "2026-04-30 09:00:00",
      "tradingHoursEnd": "2026-05-01 05:00:00",
      "region": "EUROPE",
      "exchangeList": ["ICE_EU", "LME", "EUREX"]
    },
    {
      "transactionType": "CROSS_FUTURE",
      "tradingHoursStart": "2026-04-30 09:00:00",
      "tradingHoursEnd": "2026-05-01 05:00:00",
      "region": "AMERICA",
      "exchangeList": ["CBOT", "CME", "COMEX", "NYMEX", "ICE", "NYBOT"]
    },
    {
      "transactionType": "JP_STOCK",
      "tradingHoursStart": "2026-04-30 08:30:00",
      "tradingHoursEnd": "2026-04-30 20:10:00",
      "region": null,
      "exchangeList": null
    },
    {
      "transactionType": "KR_STOCK",
      "tradingHoursStart": "2026-04-30 08:30:00",
      "tradingHoursEnd": "2026-04-30 20:10:00",
      "region": null,
      "exchangeList": null
    },
    {
      "transactionType": "CROSS_OTHER",
      "tradingHoursStart": "2026-04-30 08:30:00",
      "tradingHoursEnd": "2026-04-30 20:10:00",
      "region": null,
      "exchangeList": null
    }
  ]
}
```

* 失败(4xx)

```javascript
{
  "errMsg": null,
  "errCode": {
    "code": 400,
    "chs": "请求失败",
    "eng": "FAIL_REQUEST"
  },
  "data": null
}
```

# DIFY

## 大模型rerank标的列表

**接口URL**

> /v1/workflows/run

| 环境  | URL |
| --- | --- |
| dev | http://agent.smart-zone-dev.gf.com.cn |

**请求方式**

> POST

**Content-Type**

> json

**请求Body参数**

| 参数名 | 示例值 | 参数类型 | 是否必填 | 参数描述 |
| --- | --- | ---- | ---- | ---- |
| inputs.list | [{"windCode":"0200.HK",...}] | String | 是 | JSON序列化的标的列表 |
| inputs.keyword | 0200.hk | String | 是 | 搜索关键词 |
| user | ai-trading-assistant | String | 是 | 调用方标识 |
| response_mode | blocking | String | 是 | 响应模式，blocking-同步 |

```javascript
{
  "inputs": {
    "list": "[{\"windCode\":\"0200.HK\",\"insShtDesc\":\"新濠国际发展\",\"insLngDesc\":\"新濠国际发展\",\"insFamily\":\"EQUITY\",\"currency\":\"HKD\",\"exchange\":\"HKEX\"}]",
    "keyword": "0200.hk"
  },
  "user": "ai-trading-assistant",
  "response_mode": "blocking"
}
```

**响应示例**

* 成功(200)

```javascript
{
  "task_id": "556a6022-7a4d-4e43-be8c-f12136e769b9",
  "workflow_run_id": "f44f69db-ad29-431b-a985-e8983c9e2ea8",
  "data": {
    "id": "f44f69db-ad29-431b-a985-e8983c9e2ea8",
    "workflow_id": "9acd5dee-a1a8-4b7d-8eb4-2d69fea19e2e",
    "status": "succeeded",
    "outputs": {
      "result": [
        "0200.HK"
      ]
    },
    "error": null,
    "elapsed_time": 2.783889,
    "total_tokens": 1999,
    "total_steps": 6,
    "created_at": 1777535594,
    "finished_at": 1777535597
  }
}
```
