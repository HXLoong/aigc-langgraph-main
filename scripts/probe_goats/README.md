# GOATS API 接口探针（手工脚本）

探测 GOATS 对客机器人全部 19 个后端接口，覆盖期权、互换、交易对手。

- **不是 pytest 用例**：需要真实 GOATS 测试环境 + VPN，不进 CI；此前放在 `tests/api/` 靠 `--ignore` 掩盖，2026-09-22 迁到这里
- **凭据只从 `.env` 读**（`GOATS_BASE_URL` / `GOATS_CLIENT_ID` / `GOATS_CLIENT_SECRET` / `GOATS_EXTAPP_SALT` / `GOATS_OPT_AGENT_ID(_SUB_ID)` / `GOATS_COM_AGENT_ID(_SUB_ID)`），代码里禁止明文
- **写类接口默认拒绝**（下单 / 撤单 / 平仓 / 改单会在测试环境真实成交）：确认后加 `--confirm-write` 或 `PROBE_CONFIRM_WRITE=1`

## 一键运行

```bash
python scripts/probe_goats/run_all.py            # 只跑读类；加 --confirm-write 才跑写类
```

## 单个接口

```bash
python scripts/probe_goats/probe_01_option_rfq.py                    # 期权询价（读）
python scripts/probe_goats/probe_12_trs_order.py --confirm-write     # 互换下单（写）
python scripts/probe_goats/probe_15_trs_withdraw.py --confirm-write  # 互换撤单（链式：下单→撤单）
```

## 接口列表

| # | 文件 | 接口 | 链式调用 |
|---|------|------|----------|
| 01 | probe_01_option_rfq.py | 期权询价查询 | - |
| 02 | probe_02_option_order.py | 期权下单 | - |
| 03 | probe_03_option_order_status.py | 期权下单状态查询 | 下单 → 查状态 |
| 04 | probe_04_option_order_query.py | 期权下单结果查询 | - |
| 05 | probe_05_option_withdraw.py | 期权撤单 | 下单 → 查状态 → 撤单 |
| 06 | probe_06_option_withdraw_result.py | 期权撤单结果查询 | - |
| 07 | probe_07_option_position.py | 可平仓合约列表 | - |
| 08 | probe_08_option_close.py | 期权平仓 | - |
| 09 | probe_09_option_close_query.py | 期权平仓订单查询 | - |
| 10 | probe_10_option_close_withdraw.py | 期权平仓撤单 | 平仓 → 撤单 |
| 11 | probe_11_option_close_withdraw_result.py | 期权平仓撤单结果查询 | 平仓 → 撤单 → 查结果 |
| 12 | probe_12_trs_order.py | 互换下单 | - |
| 13 | probe_13_trs_order_status.py | 互换下单状态查询 | 下单 → 查状态 |
| 14 | probe_14_trs_order_query.py | 互换结果查询 | 下单 → 查结果 |
| 15 | probe_15_trs_withdraw.py | 互换撤单 | 下单 → 撤单 |
| 16 | probe_16_trs_replace.py | 互换改单 | 下单 → 改单 |
| 17 | probe_17_trs_replace_results.py | 互换改单状态查询 | 下单 → 改单 → 查状态 |
| 18 | probe_18_ctpty_list.py | 交易对手查询 | - |
| 19 | probe_19_trading_hours.py | 交易时间配置查询 | - |

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
