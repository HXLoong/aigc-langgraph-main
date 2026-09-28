/**
 * 每轮回复至少命中候选文本中的一个。
 *
 * 用例只在"多种合理表述均可接受"时声明该断言；未声明该字段的轮次不参与评分。
 */

const ORDER_ID = /(?<![A-Za-z0-9])Q-\d{4,}(?:-[A-Za-z0-9]+)?/g;
const GENERIC_ID = /(?<![A-Za-z0-9])[A-Z]{1,4}-\d{6,}(?:-[A-Za-z0-9]+)?/g;

function normalize(text) {
  return text.replace(ORDER_ID, "Q-{id}").replace(GENERIC_ID, "{id}");
}

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

function asLines(value) {
  const raw = typeof value === "string" ? value.split("\n") : Array.isArray(value) ? value : [];
  return raw.filter((line) => typeof line === "string" && line.trim() !== "");
}

function turnPairs(expectedOutput, output) {
  const subScenes = Array.isArray(expectedOutput.sub_scenes) ? expectedOutput.sub_scenes : [];
  const expectedTurns = [expectedOutput, ...subScenes];
  const actualTurns = Array.isArray(output.turns) ? output.turns : [output];
  return expectedTurns.map((want, index) => [want, actualTurns[index]]);
}

function replyOf(turn) {
  if (turn && typeof turn === "object") return String(turn.reply_text ?? "");
  return turn == null ? "" : String(turn);
}

function evaluate(ctx) {
  const expectedOutput = asObject(ctx.experiment?.itemExpectedOutput);
  const output = asObject(ctx.observation.output);

  const failures = [];
  let assertions = 0;

  turnPairs(expectedOutput, output).forEach(([want, actual], index) => {
    const candidates = asLines(asObject(want).response_contains_any);
    if (candidates.length === 0) return;

    assertions += 1;
    const reply = normalize(replyOf(actual));
    if (!candidates.some((candidate) => reply.includes(normalize(candidate)))) {
      failures.push(`第 ${index + 1} 轮未命中任一候选文本：${candidates.join("、")}`);
    }
  });

  const passed = failures.length === 0;
  return {
    scores: [
      {
        name: "det_required_any_text_pass",
        value: passed,
        dataType: "BOOLEAN",
        comment: passed ? "每轮均命中至少一个候选文本" : failures.join("；"),
        metadata: { assertion_count: assertions, failure_count: failures.length },
      },
    ],
  };
}
