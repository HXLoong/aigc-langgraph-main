"""标的识别子图：基于 ReAct Agent。

**这是阶段 2 的最高 ROI 产出**，对应 Tao 原规划中的 Track 2。

替换掉 Dify 里的 24 + 7 = 31 个节点，收敛为一个 ReAct 循环 + 8 个工具。

执行约束（通过 system prompt 写入）：
1. 最终输出的每一个 ticker 必须经 search_goats 或 search_securities_instrument 验证（from_goats=True）
2. regex_validate 成功且 search_goats 命中 → 跳过 web_search
3. search_goats 空 → 先调 search_securities_instrument；两者均空 → 调 web_search_bocha / web_search_tavily
4. 候选数 ≥ 2 → 必须调 llm_rank_candidates
5. 结束前必须调 assert_from_goats
"""
from __future__ import annotations

import logging

from langgraph.prebuilt import create_react_agent

from app.llm.clients import get_qwen_thinking
from app.subgraphs.ticker_tools import (
    assert_from_goats,
    llm_rank_candidates,
    regex_validate,
    search_goats,
    search_securities_instrument,
    tokenize_tickers,
    web_search_bocha,
    web_search_tavily,
)

logger = logging.getLogger(__name__)


def build_ticker_agent():
    """构建标的识别 ReAct Agent。

    使用 Dify 原始提示词，三段拼接：
    1. `ticker/tokenize.md`     - 字面提取规则
    2. `ticker/completeness.md` - 完整性判断规则
    3. `ticker/rank.md`         - 相关性排序规则
    再加上硬编码的 Agent 工作流约束。
    """
    from app.prompts import load_prompt

    try:
        tokenize_rules = load_prompt("ticker", "tokenize").system
        completeness_rules = load_prompt("ticker", "completeness").system
        rank_rules = load_prompt("ticker", "rank").system
        infer_rules = load_prompt("ticker", "infer_code").system
    except FileNotFoundError:
        logger.warning("标的识别提示词文件缺失，使用内置简化版")
        tokenize_rules = completeness_rules = rank_rules = infer_rules = ""

    agent_workflow_rules = """
## 你是一个 ReAct Agent，要调用下列工具完成任务：
- tokenize_tickers(raw_text) → 字面提取关键词（规则见下方 TOKENIZE 段）
- regex_validate(keyword)   → 判断是否为完整标的代码
- search_goats(keyword)     → 在 goats 库搜索（终点之一）
- search_securities_instrument(keyword_items) → 批量查询标的库（终点之一，goats 不可用时优先调用）
- web_search_bocha(keyword) → 中文搜索
- web_search_tavily(keyword) → 英文搜索
- llm_rank_candidates(keyword, candidates) → 排序过滤（规则见下方 RANK 段）
- assert_from_goats(tickers) → 终端断言

## 绝对约束
1. 最终输出的每一个 ticker 必须 from_goats=True
2. 标准调用顺序：tokenize → regex → search_goats
3. search_goats 返回空或失败 → 调 search_securities_instrument，传入 keyword_items 列表，每项为 {"isFull": bool, "keyword": str}
4. 两个标的库均返回空 → 才能调 web_search_bocha / web_search_tavily
5. 候选 ≥ 2 必须调 llm_rank_candidates
6. 结束前必须调 assert_from_goats
7. 总工具调用次数上限：15 次
"""

    system_prompt = (
        agent_workflow_rules
        + "\n\n## TOKENIZE 分词规则\n" + tokenize_rules[:3000]
        + "\n\n## COMPLETENESS 完整性规则\n" + completeness_rules[:2000]
        + "\n\n## RANK 排序规则\n" + rank_rules[:2000]
        + "\n\n## INFER_CODE 推断规则\n" + infer_rules[:1500]
    )

    tools = [
        tokenize_tickers,
        regex_validate,
        search_goats,
        search_securities_instrument,
        web_search_bocha,
        web_search_tavily,
        llm_rank_candidates,
        assert_from_goats,
    ]

    agent = create_react_agent(
        model=get_qwen_thinking(),
        tools=tools,
        prompt=system_prompt,
    )
    logger.info(
        "标的识别 Agent 已构建（%d 个工具，prompt=%d 字符）",
        len(tools), len(system_prompt),
    )
    return agent
