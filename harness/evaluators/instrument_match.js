/**
 * 标的识别逐轮比对：LLM 提取的标的原文与交易品种。
 *
 * 权威识别由 Java 完成，这里只评"送给后端的表达对不对"。
 * expected.instruments[i].expression 是可接受表达的任一候选，transaction_type 同理；
 * 按订单无序多重集匹配，缺单、多单、品种不符都算失败。
 */

function asObject(value) {
  if (value && typeof value === "object") return value;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

/** 候选文本：字符串视为单元素，数组去掉空项。 */
function candidates(value) {
  if (typeof value === "string") return value.trim() === "" ? [] : [value];
  if (!Array.isArray(value)) return [];
  return value.filter((item) => typeof item === "string" && item.trim() !== "");
}

/** 忽略全部空白（含全角空格）并统一小写。 */
function normalize(text) {
  return text.replace(/[\s　]+/g, "").toLowerCase();
}

/** 依次取第一个非 null/undefined 的键，兼容 alias 与 snake_case。 */
function first(source, ...keys) {
  const obj = asObject(source);
  for (const key of keys) {
    if (obj[key] != null) return obj[key];
  }
  return undefined;
}

function actualOrders(turn) {
  const orders = first(first(turn, "place_params"), "orderList", "order_list");
  if (!Array.isArray(orders)) return [];

  const result = [];
  for (const order of orders) {
    const code = first(order, "placeOrderWindCode", "place_order_wind_code");
    if (code == null) continue;
    const market = first(order, "placeOrderTransactionType", "place_order_transaction_type");
    result.push({ code: String(code), market: market == null ? "" : String(market) });
  }
  return result;
}

function evaluate(ctx) {
  const expectedOutput = asObject(ctx.experiment?.itemExpectedOutput);
  const output = asObject(ctx.observation.output);

  const subScenes = Array.isArray(expectedOutput.sub_scenes) ? expectedOutput.sub_scenes : [];
  const expectedTurns = [expectedOutput, ...subScenes];
  const actualTurns = Array.isArray(output.turns) ? output.turns : [output];

  const mismatches = [];
  let assertions = 0;

  expectedTurns.forEach((want, index) => {
    const instruments = asObject(asObject(want).expected).instruments;
    const wanted = Array.isArray(instruments)
      ? instruments.filter((item) => item && typeof item === "object")
      : [];
    if (wanted.length === 0) return;

    assertions += wanted.length;
    const turnNo = index + 1;

    if (index >= actualTurns.length) {
      mismatches.push(`第 ${turnNo} 轮无实际输出（早停或未执行），期望 ${wanted.length} 个标的`);
      return;
    }

    const remaining = actualOrders(actualTurns[index]);
    const allCodes = remaining.map((order) => order.code).join("、") || "(空)";
    let missing = false;

    for (const instrument of wanted) {
      const expressions = candidates(instrument.expression);
      const label = expressions[0] ?? "(未标注表达)";
      const accepted = new Set(expressions.map(normalize));

      const matchedAt = remaining.findIndex((order) => accepted.has(normalize(order.code)));
      if (matchedAt < 0) {
        missing = true;
        mismatches.push(`第 ${turnNo} 轮未提取到标的：${label}（实际 ${allCodes}）`);
        continue;
      }

      const [matched] = remaining.splice(matchedAt, 1);
      const markets = candidates(instrument.transaction_type);
      if (markets.length > 0 && !markets.includes(matched.market)) {
        mismatches.push(
          `第 ${turnNo} 轮 ${label} 交易品种不符：期望 ${markets.join("/")}，实际 ${matched.market || "(空)"}`,
        );
      }
    }

    // 已报漏提取时，剩余订单多半是同一单的错误表达，不再重复计为"多出"
    if (remaining.length > 0 && !missing) {
      mismatches.push(`第 ${turnNo} 轮多出标的：${remaining.map((order) => order.code).join("、")}`);
    }
  });

  const noAssertions = assertions === 0;
  const passed = !noAssertions && mismatches.length === 0;
  return {
    scores: [
      {
        name: "det_instrument_match_pass",
        value: passed,
        dataType: "BOOLEAN",
        comment: noAssertions
          ? "没有可比对的 expected.instruments；标的识别用例必须逐轮标注"
          : passed
            ? "全部轮次标的表达与交易品种均匹配"
            : mismatches.join("；"),
        metadata: { assertion_count: assertions, mismatch_count: mismatches.length },
      },
    ],
  };
}
