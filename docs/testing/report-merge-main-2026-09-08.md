# HXL-langgraph 合并 main 验证记录

合并前本地提交：`bf0a83b`；目标主干：`7e51dce`。对应 PR：GZTL-AI/aigc-langgraph#182。
本地比 PR 的远端来源分支多一个会话续接提交，因此实际处理 37 个冲突路径。

## 合并结果

- 保留 DSL v2 路由、拆分后的期权节点、平仓专用后端及标的解析管线，删除已被主干替代的旧节点和测试。
- API 同时保留会话 ID 解析、输入别名冲突校验、DSL v2 新入参及递归上限。
- 保留业务子图后的意图写回和回复后的历史记录，避免子图回传旧历史导致重复累加。
- 快速询价和存量查询沿用主干的前置分支，直接进入 persist，不向消息后端写入未经分类的意图。
- 保留期权后端上下文与空响应校验，并合入 DSL v2 的 operate 映射和参数清洗。
- 将询价补参约束迁入新提示词和模型；原 Q- 单号与本轮 tenor 一同传给 Java，缺省参数由 Java 合并。
- 回归测试同步迁移节点名、模型名、路由标签和外部服务 mock，保留原有测试意图。

## 验证

Windows PowerShell 环境：

```powershell
$env:ENABLE_LANGFUSE = 'false'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
.venv/Scripts/python.exe -m pytest tests/ -q --tb=short
```

- 全套：1304 passed，15 skipped。
- 最后调整前置分支接线后，重跑主图入口、意图持久化和询价续接：29 passed；对应前置分支约束已先验证失败再修复。
- 告警阈值一致性、ADR 引用检查、相对 upstream/main 的补丁空白检查：通过。相对原本地分支的完整合并检查仍会报告主干原有的提示词/API 文档行尾空格。
- mypy：132 项错误；与两个合并前提交比较，未新增错误消息。主干基线为 134 项，本地分支基线为 154 项。
- Ruff：146 项既有风格检查问题；应用代码没有超出两个合并前提交的新诊断。
- fixture 一致性检查无法通过：缺少 unified_golden.jsonl、option_golden.jsonl、golden_business_seeds_2026-05.jsonl；这些文件也未包含在目标主干中。

未执行真实客户后端或真实 LLM 验收，测试通过不代表交易业务验收完成。
