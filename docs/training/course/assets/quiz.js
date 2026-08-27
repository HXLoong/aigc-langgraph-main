/* 课程小测组件 · 图灵科技
 *
 * 用法（课件 HTML 内）：
 *   <section class="quiz">
 *     <div class="quiz-q" data-answer="b">
 *       <p class="quiz-stem">题干……</p>
 *       <label><input type="radio" name="q1" value="a"> 选项 A</label>
 *       <label><input type="radio" name="q1" value="b"> 选项 B</label>
 *       <p class="quiz-explain" hidden>答案解析……</p>
 *     </div>
 *     <button class="quiz-check">核对答案</button>
 *     <p class="quiz-score"></p>
 *   </section>
 *   <script src="../assets/quiz.js"></script>
 */
(function () {
  "use strict";

  function gradeQuiz(quiz) {
    var questions = quiz.querySelectorAll(".quiz-q");
    var correct = 0;

    questions.forEach(function (q) {
      var answer = q.getAttribute("data-answer");
      var labels = q.querySelectorAll("label");
      var picked = null;

      q.classList.add("graded");

      labels.forEach(function (label) {
        var input = label.querySelector("input[type=radio]");
        if (!input) return;
        label.classList.remove("correct", "wrong");
        if (input.checked) picked = input.value;
        if (input.value === answer) label.classList.add("correct");
      });

      if (picked === answer) {
        correct += 1;
      } else if (picked !== null) {
        labels.forEach(function (label) {
          var input = label.querySelector("input[type=radio]");
          if (input && input.checked && input.value !== answer) {
            label.classList.add("wrong");
          }
        });
      }

      var explain = q.querySelector(".quiz-explain");
      if (explain) explain.hidden = false;
    });

    var score = quiz.querySelector(".quiz-score");
    if (score) {
      var total = questions.length;
      var pass = correct === total;
      score.textContent = pass
        ? "全对（" + correct + "/" + total + "）——可以进入下一课。"
        : correct + "/" + total + " —— 回看标绿的正确项和解析，改选后可再次核对。";
      score.classList.toggle("pass", pass);
      score.classList.toggle("fail", !pass);
    }
  }

  document.querySelectorAll(".quiz").forEach(function (quiz) {
    var btn = quiz.querySelector(".quiz-check");
    if (btn) {
      btn.addEventListener("click", function () {
        gradeQuiz(quiz);
      });
    }
  });
})();
