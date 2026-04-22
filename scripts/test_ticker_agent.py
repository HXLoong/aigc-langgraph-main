"""search_securities_instrument 接口直连测试脚本。

直接调用工具函数，不走 Agent/LLM，只验证新接口的连通性和返回格式。

用法：
    python scripts/test_ticker_agent.py
    python scripts/test_ticker_agent.py TME 腾讯音乐
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
)
logger = logging.getLogger("test_securities_instrument")

# 默认测试用例：每条为一个 keyword_items 列表，直接对应接口入参格式
SAMPLE_CASES: list[list[dict]] = [
    [{"isFull": False, "keyword": "TME"}],                                          # 英文代码，模糊
    [{"isFull": False, "keyword": "腾讯音乐"}],                                     # 中文名称，模糊
    [{"isFull": False, "keyword": "TME"}, {"isFull": False, "keyword": "腾讯音乐"}], # 批量混合
    [{"isFull": False, "keyword": "AAPL"}],                                         # 苹果
    [{"isFull": False, "keyword": "600519"}],                                       # A 股代码，模糊
    [{"isFull": True,  "keyword": "600519.SH"}],                                    # A 股代码，精确
]


async def run_case(keyword_items: list[dict]) -> None:
    from app.subgraphs.ticker_tools import search_securities_instrument

    print(f"\n{'='*60}")
    print(f"[TEST]  keywordItems={keyword_items}")

    result = await search_securities_instrument.ainvoke(
        {"keyword_items": keyword_items}
    )

    if not result:
        print("[RESULT] 空（接口无数据或不可达）")
    else:
        print(f"[RESULT] 返回 {len(result)} 条：")
        for item in result:
            wc = item.get("windCode") or item.get("wind_code", "N/A")
            name = item.get("insShtDesc") or item.get("ins_sht_desc", "")
            verified = item.get("from_goats", False)
            print(f"  windCode={wc}  name={name}  from_goats={verified}")

    print("=" * 60)


async def main(cli_args: list[str]) -> None:
    if cli_args:
        # 命令行传入时，每个参数作为一个模糊查询条件
        cases = [[{"isFull": False, "keyword": kw} for kw in cli_args]]
    else:
        cases = SAMPLE_CASES

    for keyword_items in cases:
        await run_case(keyword_items)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
