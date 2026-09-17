# GOATS API 接口测试

测试 GOATS 对客机器人全部 20 个后端接口，覆盖期权、互换、交易对手。

## 一键运行

```bash
python tests/api/run_all.py
```

## 单个接口

```bash
python tests/api/test_01_option_rfq.py       # 期权询价
python tests/api/test_12_trs_order.py         # 互换下单
python tests/api/test_15_trs_withdraw.py      # 互换撤单（链式：下单→撤单）
```

## 接口列表

| # | 文件 | 接口 | 链式调用 |
|---|------|------|----------|
| 01 | test_01_option_rfq.py | 期权询价查询 | - |
| 02 | test_02_option_order.py | 期权下单 | - |
| 03 | test_03_option_order_status.py | 期权下单状态查询 | 下单 → 查状态 |
| 04 | test_04_option_order_query.py | 期权下单结果查询 | - |
| 05 | test_05_option_withdraw.py | 期权撤单 | 下单 → 查状态 → 撤单 |
| 06 | test_06_option_withdraw_result.py | 期权撤单结果查询 | - |
| 07 | test_07_option_position.py | 可平仓合约列表 | - |
| 08 | test_08_option_close.py | 期权平仓 | - |
| 09 | test_09_option_close_query.py | 期权平仓订单查询 | - |
| 10 | test_10_option_close_withdraw.py | 期权平仓撤单 | 平仓 → 撤单 |
| 11 | test_11_option_close_withdraw_result.py | 期权平仓撤单结果查询 | 平仓 → 撤单 → 查结果 |
| 12 | test_12_trs_order.py | 互换下单 | - |
| 13 | test_13_trs_order_status.py | 互换下单状态查询 | 下单 → 查状态 |
| 14 | test_14_trs_order_query.py | 互换结果查询 | 下单 → 查结果 |
| 15 | test_15_trs_withdraw.py | 互换撤单 | 下单 → 撤单 |
| 16 | test_16_trs_replace.py | 互换改单 | 下单 → 改单 |
| 17 | test_17_trs_replace_results.py | 互换改单状态查询 | 下单 → 改单 → 查状态 |
| 18 | test_18_ctpty_list.py | 交易对手查询 | - |
| 19 | test_19_trading_hours.py | 交易时间配置查询 | - |

## 文件结构

```
tests/api/
├── _utils.py          # 共享模块（签名、请求、校验）
├── run_all.py         # 一键运行入口
├── README.md
├── test_01_option_rfq.py
├── ...
```

## 依赖

- Python 3.11+
- `requests`（标准库之外唯一依赖）

## 说明

- 链式接口（撤单、改单、状态查询）内部已包含前置步骤，直接运行即可
- 接口 05（期权撤单）在测试环境无可撤订单时返回 50003，属正常行为
