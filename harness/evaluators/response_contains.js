/**
 * 每轮回复必须包含用例声明的全部必含文本。
 *
 * 单号等动态值先归一化再比对，避免 fixture 写死运行时生成的编号。
 * 上传到 Langfuse 的是单文件源码，必须是裸 `function evaluate`（带 export 会静默不执行）。
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

/** 期望文本：字符串按行拆，数组去掉空项。 */
function asLines(value) {
  const raw = typeof value === "string" ? value.split("\n") : Array.isArray(value) ? value : [];
  return raw.filter((line) => typeof line === "string" && line.trim() !== "");
}

/** 期望轮与实际轮按序配对；实际缺轮时为 undefined，由各断言自行处理。 */
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

  const missing = [];
  let assertions = 0;

  turnPairs(expectedOutput, output).forEach(([want, actual], index) => {
    const reply = normalize(replyOf(actual));
    for (const required of asLines(asObject(want).response_contains)) {
      assertions += 1;
      if (!reply.includes(normalize(required))) {
        missing.push(`第 ${index + 1} 轮缺少必含文本：${required}`);
      }
    }
  });

  const passed = missing.length === 0;
  return {
    scores: [
      {
        name: "det_required_text_pass",
        value: passed,
        dataType: "BOOLEAN",
        comment: passed ? "全部必含文本均已出现" : missing.join("；"),
        metadata: { assertion_count: assertions, missing_count: missing.length },
      },
    ],
  };
}
