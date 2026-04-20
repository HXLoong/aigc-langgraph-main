---
name: shadow-test
description: 执行 LangGraph vs Dify 的 shadow 双跑对比，定位差异。使用场景：发布前的差异验证、灰度切换期间的差异监控、某条具体指令的对齐问题排查。
argument-hint: [--sample path] [--n count]
allowed-tools: Read, Bash, Grep
---

# Shadow 双跑对比

## 参数
- `--sample` 可选，golden set 路径（默认 `tests/fixtures/golden.jsonl`）
- `--n` 可选，采样数量（默认全跑）

## 执行流程

### Step 1：前置检查
```bash
# 确认两个端点都通
curl -sf http://localhost:8000/health || echo "LangGraph 端点 down"
curl -sf http://localhost:5000/health || echo "Dify 端点 down"
```

若任一不通，**立即停下**告诉用户该启哪个服务。

### Step 2：跑 shadow_compare
```bash
python scripts/shadow_compare.py \
    --langgraph http://localhost:8000/v1/message \
    --dify http://localhost:5000/v1/workflows/run \
    --sample ${1:-tests/fixtures/golden.jsonl}
```

### Step 3：从 MySQL 读结果
```bash
docker compose exec mysql mysql -u otc_agent -ppassword otc_agent_business -e "
SELECT message_id, is_equal, diff_detail
FROM shadow_compare
WHERE created_at >= NOW() - INTERVAL 10 MINUTE
ORDER BY created_at DESC;
"
```

### Step 4：分析差异
对每个 `is_equal=0` 的记录：
1. 读 `diff_detail` JSON
2. 归类差异：
   - `product_type` 不一致 → 路由规则差异，检查 `app/nodes/route.py`
   - `intent` 不一致 → 意图识别提示词差异，检查对应 `classify_*_intent` 节点
   - `api_code` 不一致 → 参数提取差异，可能提示词或 Pydantic 模型问题
3. 为每个差异归类生成一份简报

### Step 5：给出报告

```markdown
# Shadow 双跑结果

样本数：N
一致率：X/N (Y%)

## 差异分类
- 路由差异：K 条（message_id 列表）
- 意图差异：K 条
- 参数差异：K 条
- API 码差异：K 条

## Top 3 差异案例
1. <message_id>：<raw_content 摘要>
   - LangGraph: product=..., intent=...
   - Dify:      product=..., intent=...
   - 怀疑原因：<初步分析>
   - 建议：<查看哪个文件，跑哪个测试>

## 建议动作
- [ ] 若一致率 ≥ 99%：可以进入 5% 金丝雀
- [ ] 若 95% ≤ X < 99%：用 dify-reviewer agent 做深度对齐分析
- [ ] 若 X < 95%：暂停灰度计划，回 feature branch 修复
```

## 注意

- **不要自动修改代码**：shadow-test 是诊断工具，不是修复工具
- **跑之前确认 `USE_LANGGRAPH=true`**：否则 LangGraph 端口实际走 Dify，白跑
- **大样本跑之前警告用户**：N > 100 会产生大量 LLM 调用费用
