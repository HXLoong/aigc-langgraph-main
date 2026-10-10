"""Harness — 评测台（ADR 0001 + ADR 0014）。

与 app/ 解耦：主链路经 HTTP 调本地 `/v1/workflows/run`；仅 case_generator /
langfuse_client 少量 import app 的 LLM 工厂与配置。
"""
