/**
 * harness/evaluators/*.js 的回归测试。
 *
 * 这里的评测器是上传到 Langfuse 的单文件源码，必须是裸 `function evaluate`——
 * 加上 `export` 会让 Langfuse 静默不执行（不出分、无报错）。所以测试用 Function
 * 构造从源码里取出 evaluate，而不是 require 原文件。
 */
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");

const loaded = new Map();

function loadEvaluator(name) {
  if (loaded.has(name)) return loaded.get(name);

  const source = readFileSync(join(__dirname, `${name}.js`), "utf8");
  assert.ok(source.includes("function evaluate("), `${name}.js 找不到裸 function evaluate`);

  const evaluate = new Function(`${source}\nreturn evaluate;`)();
  loaded.set(name, evaluate);
  return evaluate;
}

function score(evaluator, expectedOutput, output) {
  const evaluate = loadEvaluator(evaluator);
  const result = evaluate({
    observation: { output },
    experiment: { itemExpectedOutput: expectedOutput },
  });
  assert.equal(result.scores.length, 1, `${evaluator} 应只产出一个 Score`);
  return result.scores[0];
}

// ---------------------------------------------------------------- 必含文本

test("response_contains：每轮都含必含文本才通过", async (t) => {
  await t.test("全部命中", () => {
    const s = score(
      "response_contains",
      { response_contains: ["订单号", "确认"] },
      { reply_text: "订单号 Q-20260101-1 确认" },
    );
    assert.equal(s.value, true);
    assert.equal(s.metadata.assertion_count, 2);
    assert.equal(s.metadata.missing_count, 0);
  });

  await t.test("缺一条时报出缺哪条", () => {
    const s = score(
      "response_contains",
      { response_contains: ["订单号", "确认"] },
      { reply_text: "订单号 Q-20260101-1" },
    );
    assert.equal(s.value, false);
    assert.match(s.comment, /确认/);
  });

  await t.test("单号归一后可比（fixture 写死 vs 运行时不同单号）", () => {
    const s = score(
      "response_contains",
      { response_contains: ["Q-20260101-1234"] },
      { reply_text: "已提交 Q-20261231-9999 成功" },
    );
    assert.equal(s.value, true);
  });

  await t.test("多轮中某一轮缺失即失败", () => {
    const s = score(
      "response_contains",
      { response_contains: ["A"], sub_scenes: [{ response_contains: ["B"] }, { response_contains: ["C"] }] },
      { turns: [{ reply_text: "A" }, { reply_text: "X" }, { reply_text: "C" }] },
    );
    assert.equal(s.value, false);
    assert.match(s.comment, /第 2 轮/);
  });

  await t.test("实际轮次不足（早停）按缺失计", () => {
    const s = score(
      "response_contains",
      { response_contains: ["A"], sub_scenes: [{ response_contains: ["B"] }] },
      { turns: [{ reply_text: "A" }] },
    );
    assert.equal(s.value, false);
  });

  await t.test("未声明断言时不产出失败", () => {
    const s = score("response_contains", { response_contains: [] }, { reply_text: "任意" });
    assert.equal(s.value, true);
    assert.equal(s.metadata.assertion_count, 0);
  });
});

// ------------------------------------------------------------ 任一候选文本

test("response_contains_any：每轮命中任一候选即通过", async (t) => {
  await t.test("命中之一", () => {
    const s = score(
      "response_contains_any",
      { response_contains_any: ["已提交", "已受理"] },
      { reply_text: "您的指令已受理" },
    );
    assert.equal(s.value, true);
    assert.equal(s.metadata.assertion_count, 1);
  });

  await t.test("全不命中时报出候选集", () => {
    const s = score(
      "response_contains_any",
      { response_contains_any: ["已提交", "已受理"] },
      { reply_text: "处理中" },
    );
    assert.equal(s.value, false);
    assert.match(s.comment, /已提交/);
  });

  await t.test("未声明该字段的轮次不参与评分", () => {
    const s = score("response_contains_any", {}, { reply_text: "任意" });
    assert.equal(s.value, true);
    assert.equal(s.metadata.assertion_count, 0);
  });
});

// ---------------------------------------------------------------- 禁止文本

test("response_not_contains：出现任一禁止文本即失败", async (t) => {
  await t.test("命中禁止文本", () => {
    const s = score(
      "response_not_contains",
      { response_not_contains: ["正在处理，请勿重复提交"] },
      { reply_text: "正在处理，请勿重复提交" },
    );
    assert.equal(s.value, false);
    assert.equal(s.metadata.violation_count, 1);
  });

  await t.test("保持字面匹配，不做单号归一", () => {
    const s = score(
      "response_not_contains",
      { response_not_contains: ["Q-20260101-1234"] },
      { reply_text: "已提交 Q-20261231-9999" },
    );
    assert.equal(s.value, true);
  });

  await t.test("干净回复通过", () => {
    const s = score("response_not_contains", { response_not_contains: ["失败"] }, { reply_text: "成功" });
    assert.equal(s.value, true);
  });
});

// ------------------------------------------------------------ 路由与意图

const intentExpected = { expected: { product_type: "swap", intent: "place_order_request" } };

test("intent_match：逐轮比对 product_type / intent", async (t) => {
  await t.test("首轮与子场景全中", () => {
    const s = score(
      "intent_match",
      { ...intentExpected, sub_scenes: [{ expected: { intent: "place_order_confirm" } }] },
      {
        turns: [
          { product_type: "swap", intent: "place_order_request" },
          { product_type: "swap", intent: "place_order_confirm" },
        ],
      },
    );
    assert.equal(s.value, true);
    assert.equal(s.metadata.assertion_count, 3);
  });

  await t.test("只标注 product_type 时意图不参与比对", () => {
    const s = score(
      "intent_match",
      { expected: { product_type: "swap" } },
      { turns: [{ product_type: "swap", intent: "任意" }] },
    );
    assert.equal(s.value, true);
    assert.equal(s.metadata.assertion_count, 1);
  });

  await t.test("不符时报出期望与实际", () => {
    const s = score("intent_match", intentExpected, {
      turns: [{ product_type: "option", intent: "new_inquiry" }],
    });
    assert.equal(s.value, false);
    assert.match(s.comment, /product_type/);
    assert.match(s.comment, /option/);
  });

  await t.test("实际缺轮（早停或未执行）判失败", () => {
    const s = score(
      "intent_match",
      { expected: { product_type: "swap" }, sub_scenes: [{ expected: { intent: "place_order_confirm" } }] },
      { turns: [{ product_type: "swap" }] },
    );
    assert.equal(s.value, false);
    assert.match(s.comment, /无实际输出/);
  });

  await t.test("一个标注都没有时判失败，避免标注缺失被当作通过", () => {
    const s = score("intent_match", { send_text: "x" }, { turns: [{ product_type: "swap" }] });
    assert.equal(s.value, false);
    assert.equal(s.metadata.assertion_count, 0);
    assert.match(s.comment, /必须逐轮标注/);
  });

  await t.test("expectedOutput 是 JSON 字符串时同样可比", () => {
    const s = score("intent_match", JSON.stringify(intentExpected), {
      turns: [{ product_type: "swap", intent: "place_order_request" }],
    });
    assert.equal(s.value, true);
  });
});

// ---------------------------------------------------------------- 标的识别

const order = (code, market) =>
  market ? { placeOrderWindCode: code, placeOrderTransactionType: market } : { placeOrderWindCode: code };

const orders = (...list) => ({ turns: [{ place_params: { orderList: list } }] });

test("instrument_match：按订单多重集比对标的表达与交易品种", async (t) => {
  await t.test("任一候选表达命中即可（含大小写与空格归一）", () => {
    const s = score(
      "instrument_match",
      { expected: { instruments: [{ expression: ["贵州茅台 600519.SH", "600519.SH"], transaction_type: ["A_SHARE"] }] } },
      orders(order("600519.sh", "A_SHARE")),
    );
    assert.equal(s.value, true);
    assert.equal(s.metadata.assertion_count, 1);
  });

  await t.test("未提取到标的", () => {
    const s = score(
      "instrument_match",
      { expected: { instruments: [{ expression: ["腾讯控股 0700.HK"] }] } },
      orders(),
    );
    assert.equal(s.value, false);
    assert.match(s.comment, /未提取到标的/);
  });

  await t.test("多出一单", () => {
    const s = score(
      "instrument_match",
      { expected: { instruments: [{ expression: ["600519.SH"] }] } },
      orders(order("600519.SH"), order("0700.HK")),
    );
    assert.equal(s.value, false);
    assert.match(s.comment, /多出标的/);
  });

  await t.test("交易品种不符", () => {
    const s = score(
      "instrument_match",
      { expected: { instruments: [{ expression: ["600519.SH"], transaction_type: ["A_SHARE"] }] } },
      orders(order("600519.SH", "HK_STOCK")),
    );
    assert.equal(s.value, false);
    assert.match(s.comment, /交易品种不符/);
  });

  await t.test("已报漏提取时不再重复计为多出", () => {
    const s = score(
      "instrument_match",
      { expected: { instruments: [{ expression: ["600519.SH"] }] } },
      orders(order("000001.SZ")),
    );
    assert.equal(s.value, false);
    assert.doesNotMatch(s.comment, /多出标的/);
  });

  await t.test("兼容 snake_case 别名", () => {
    const s = score(
      "instrument_match",
      { expected: { instruments: [{ expression: ["600519.SH"] }] } },
      { turns: [{ place_params: { order_list: [{ place_order_wind_code: "600519.SH" }] } }] },
    );
    assert.equal(s.value, true);
  });

  await t.test("未标注时判失败", () => {
    const s = score("instrument_match", { expected: {} }, { turns: [{}] });
    assert.equal(s.value, false);
    assert.equal(s.metadata.assertion_count, 0);
    assert.match(s.comment, /必须逐轮标注/);
  });
});

// ---------------------------------------------------------------- 拒绝验收

const rejectionTurn = (extra = {}) => ({
  turns: [
    {
      error: { node: "swap_normalize", type: "NonPositiveQuantityError" },
      trace: "ingest → swap_normalize[error]",
      reply_text: "数量必须为正数",
      ...extra,
    },
  ],
});

test("rejection_match：拒绝原因正确且确实未提交后端", async (t) => {
  await t.test("干净拒绝通过", () => {
    const s = score("rejection_match", { expected: { rejection: "non_positive_quantity" } }, rejectionTurn());
    assert.equal(s.value, true);
    assert.equal(s.metadata.assertion_count, 1);
  });

  await t.test("拒了但仍打了后端则失败", () => {
    const s = score(
      "rejection_match",
      { expected: { rejection: "non_positive_quantity" } },
      rejectionTurn({ trace: "ingest → swap_normalize[error] → swap_place_order_submit", api_code: "500" }),
    );
    assert.equal(s.value, false);
  });

  await t.test("错误节点或类型不符则失败", () => {
    const s = score("rejection_match", { expected: { rejection: "ambiguous_action" } }, rejectionTurn());
    assert.equal(s.value, false);
  });

  await t.test("未声明 rejection 时判失败", () => {
    const s = score("rejection_match", {}, { turns: [{}] });
    assert.equal(s.value, false);
    assert.equal(s.metadata.assertion_count, 0);
  });
});
