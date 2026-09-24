# 部署 · 客户环境调研、私有化部署与上线前对照

本目录回答"怎么把系统部署到客户环境、上线前怎么验证"。上线后的值班与排障见 [../operations/](../operations/README.md)。

按执行顺序：

| # | 文档 | 用途 |
|---|---|---|
| 1 | [customer-env-assessment.md](./customer-env-assessment.md) | 客户环境调研模板：联调前一次性收集网络、账号、配置约束 |
| 2 | [customer-private.md](./customer-private.md) | 客户现场私有化部署手册（推荐配合 `scripts/deploy-customer.sh`） |
| 3 | [shadow-compare-guide.md](./shadow-compare-guide.md) | LangGraph 与 Dify 双跑对照（可选参考，不进任何门） |

LangFuse 自托管部署见 [../langfuse/self-hosted-deployment.md](../langfuse/self-hosted-deployment.md)。
