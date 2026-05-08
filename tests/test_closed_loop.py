"""V1 闭环 CI 测试：跑 demo_closed_loop 脚本，断言全部 golden case 通过。

这是"V1 可发布"的最低门槛检查：在零外部依赖的 in-process 环境下，
30 条 golden case 的 product_type + intent 必须 100% 正确。

注意：
- 本测试**不验证 LLM 准确率**（那是 eval_golden.py + 真实 LLM 的职责）
- 本测试只验证图拓扑、State 流转、节点串联、子图分发是否正确
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("langgraph.graph")


@pytest.mark.asyncio
async def test_v1_closed_loop_all_golden_cases_pass():
    """30 条 golden case 必须全部通过。"""
    import sys
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root))

    from scripts import demo_closed_loop

    sample = repo_root / "tests" / "fixtures" / "golden.jsonl"
    assert sample.exists(), f"缺少 golden 样本: {sample}"

    # 直接调 main()，传一个 args namespace
    class Args:
        pass

    args = Args()
    args.sample = sample
    args.max_cases = 0
    args.verbose = False

    exit_code = await demo_closed_loop.main(args)
    assert exit_code == 0, "V1 闭环验证失败：有 case 未通过，详见上方输出"
