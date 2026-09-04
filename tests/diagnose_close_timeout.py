"""诊断 close_place_close 超时：直接调 LLM，测延迟。"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm.clients import get_qwen_standard, get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.models import ClosePlaceParams

TEST_INPUT = "帮我平仓 CO-20250515-A1B2C3D4，市价单，全部平掉"


async def test_model(name, llm_factory, model_name):
    print(f"\n{'='*50}")
    print(f"测试 {name} (model={model_name})")
    print(f"{'='*50}")
    prompt = load_prompt("option_close", "place_close")
    llm = llm_factory().with_structured_output(ClosePlaceParams)

    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(
            llm.ainvoke([("system", prompt.system), ("user", TEST_INPUT)]),
            timeout=120,
        )
        elapsed = time.monotonic() - t0
        print(f"OK latency={elapsed:.1f}s")
        print(f"  orders={len(result.closeOrderList)}")
        for o in result.closeOrderList[:2]:
            print(f"  - orderId={o.orderId}, type={o.closeOrderType}, amt={o.closeOrderNotionalDelta}")
    except TimeoutError:
        elapsed = time.monotonic() - t0
        print(f"TIMEOUT after {elapsed:.1f}s (>120s)")
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"ERROR latency={elapsed:.1f}s: {type(e).__name__}: {e}")


async def main():
    print("prompt 大小: system=69KB, user=test input")
    print("模型配置来自 .env (QWEN_MODEL_STANDARD / QWEN_MODEL_THINKING)")

    settings = __import__("app.config", fromlist=[""]).get_settings()
    print(f"  standard: {settings.qwen_model_standard}")
    print(f"  thinking: {settings.qwen_model_thinking}")
    print(f"  api_base: {settings.qwen_api_base}")

    # 额外测试 qwen3.5-35b-a3b
    from langchain_openai import ChatOpenAI
    model_35b = "qwen3.5-35b-a3b"
    def make_35b():
        return ChatOpenAI(
            model=model_35b,
            base_url=settings.qwen_api_base,
            api_key=settings.qwen_api_key,
            temperature=0.0,
            timeout=90,
            max_retries=2,
            extra_body={"enable_thinking": True},
        )

    await test_model("qwen-plus (standard)", get_qwen_standard, settings.qwen_model_standard)
    await test_model("qwen-max (thinking)", get_qwen_thinking, settings.qwen_model_thinking)
    await test_model("qwen3.5-35b-a3b", make_35b, model_35b)


if __name__ == "__main__":
    asyncio.run(main())
