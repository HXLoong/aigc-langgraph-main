/**
 * 拒绝验收：明确拒绝原因，且确实没有提交后端。
 *
 * 只认已登记的拒绝原因；命中后还要确认没有后端调用痕迹——这是"该拒的拒了"
 * 和"拒了但仍打了后端"的分界。
 */

/** 拒绝原因 → [报错节点, 错误类型]。 */
const REJECTIONS = {
  ambiguous_action: ["swap_extract_candidates", "AmbiguousActionError"],
  non_positive_quantity: ["swap_normalize", "NonPositiveQuantityError"],
};

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

/** 一轮是否满足"拒绝且未提交"。 */
function isCleanRejection(actual, wanted) {
  const turn = asObject(actual);
  const error = asObject(turn.error);
  const trace = typeof turn.trace === "string" ? turn.trace : "";

  return (
    error.node === wanted[0] &&
    error.type === wanted[1] &&
    turn.api_code == null &&
    turn.api_result == null &&
    turn.place_params == null &&
    trace.includes(`${wanted[0]}[error]`) &&
    !trace.includes("swap_place_order_submit") &&
    Boolean(turn.reply_text)
  );
}

function evaluate(ctx) {
  const expected = asObject(ctx.experiment?.itemExpectedOutput);
  const output = asObject(ctx.observation.output);

  const subScenes = Array.isArray(expected.sub_scenes) ? expected.sub_scenes : [];
  const expectedTurns = [expected, ...subScenes];
  const actualTurns = Array.isArray(output.turns) ? output.turns : [output];

  const failures = [];
  let assertions = 0;

  expectedTurns.forEach((want, index) => {
    const kind = asObject(asObject(want).expected).rejection;
    if (kind == null) return;

    assertions += 1;
    const wanted = typeof kind === "string" ? REJECTIONS[kind] : undefined;
    if (!wanted || !isCleanRejection(actualTurns[index], wanted)) {
      failures.push(`第 ${index + 1} 轮未满足 ${kind} 拒绝与无提交验收`);
    }
  });

  const passed = assertions > 0 && failures.length === 0;
  return {
    scores: [
      {
        name: "det_rejection_match_pass",
        value: passed,
        dataType: "BOOLEAN",
        comment: passed
          ? "全部拒绝原因匹配，未提交后端"
          : failures.join("；") || "没有明确的 expected.rejection",
        metadata: { assertion_count: assertions, mismatch_count: failures.length },
      },
    ],
  };
}
