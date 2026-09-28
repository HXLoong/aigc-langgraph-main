/**
 * 意图集逐轮比对路由与意图：expected.product_type / expected.intent。
 *
 * 只比对 expected 里出现的键（反案例可以只标 product_type），但一轮都没标注时判失败，
 * 避免标注缺失被当成通过。
 */

const INTENT_KEYS = ["product_type", "intent"];

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

/** 一轮 expected 里非空的 product_type / intent。 */
function expectedIntent(turn) {
  const expected = asObject(asObject(turn).expected);
  const wanted = {};
  for (const key of INTENT_KEYS) {
    const value = expected[key];
    if (typeof value === "string" && value.trim() !== "") wanted[key] = value.trim();
  }
  return wanted;
}

function actualValue(turn, key) {
  const value = asObject(turn)[key];
  return value == null ? "" : String(value);
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
    const wanted = expectedIntent(want);
    if (Object.keys(wanted).length === 0) return;

    assertions += Object.keys(wanted).length;
    const turnNo = index + 1;

    if (index >= actualTurns.length) {
      mismatches.push(`第 ${turnNo} 轮无实际输出（早停或未执行），期望 ${JSON.stringify(wanted)}`);
      return;
    }
    for (const [key, expected] of Object.entries(wanted)) {
      const actual = actualValue(actualTurns[index], key);
      if (actual !== expected) {
        mismatches.push(`第 ${turnNo} 轮 ${key} 不符：期望 ${expected}，实际 ${actual || "(空)"}`);
      }
    }
  });

  const noAssertions = assertions === 0;
  const passed = !noAssertions && mismatches.length === 0;
  return {
    scores: [
      {
        name: "det_intent_match_pass",
        value: passed,
        dataType: "BOOLEAN",
        comment: noAssertions
          ? "没有可比对的 expected.product_type / intent；意图集用例必须逐轮标注"
          : passed
            ? "全部轮次路由与意图均匹配"
            : mismatches.join("；"),
        metadata: { assertion_count: assertions, mismatch_count: mismatches.length },
      },
    ],
  };
}
