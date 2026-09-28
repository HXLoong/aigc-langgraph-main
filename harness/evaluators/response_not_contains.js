/**
 * 每轮回复都不得出现用例声明的禁止文本。
 *
 * 与必含文本不同，这里保持字面匹配，不做单号归一化——禁止文本通常是固定错误文案。
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

  const violations = [];

  turnPairs(expectedOutput, output).forEach(([want, actual], index) => {
    const reply = replyOf(actual);
    for (const forbidden of asLines(asObject(want).response_not_contains)) {
      if (reply.includes(forbidden)) {
        violations.push(`第 ${index + 1} 轮命中禁止文本：${forbidden}`);
      }
    }
  });

  const passed = violations.length === 0;
  return {
    scores: [
      {
        name: "det_forbidden_text_pass",
        value: passed,
        dataType: "BOOLEAN",
        comment: passed ? "未命中禁止文本。" : violations.join("；"),
        metadata: { violation_count: violations.length },
      },
    ],
  };
}
