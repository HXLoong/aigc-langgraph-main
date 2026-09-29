"""全局配置：从环境变量加载，pydantic 校验。"""
import os
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["deepseek", "qwen", "openai_compatible"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    # === MySQL：与 Java 共库，checkpoint、审计与幂等共用一个连接配置 ===
    # 格式 mysql+aiomysql://user:password@host:port/database，表名以 langgraph_ 隔离。
    mysql_uri: str = Field(..., description="Java 共库连接，保存 langgraph_ checkpoint、审计与幂等表")

    # === LLM ===
    llm_api_base: str
    llm_api_key: str
    llm_provider: LLMProvider = Field(description="显式选择接口适配，不根据模型名称推断厂商")
    llm_trust_env: bool = Field(
        default=True,
        description="LLM HTTP 客户端是否读取环境/系统代理和证书配置；内网直连设为 false",
    )
    # 三角色独立选择模型，共用连接和适配；THINKING 名称不自动开启思考。
    # DeepSeek Pro 是当前基线，切换模型后重启并重新验收（ADR 0020）。
    llm_model_standard: str = "deepseek-v4-pro"
    llm_model_thinking: str = "deepseek-v4-pro"
    llm_model_complex: str = "deepseek-v4-pro"

    # === 后端业务 API ===
    otc_api_base_url: str
    otc_api_secret: str

    # 初始 20/5/60 秒预算；最终配置根据本地真实回归与压测校准。
    llm_timeout_seconds: float = Field(default=20.0, gt=0)
    llm_output_max_tokens: int = Field(default=8192, ge=64, le=65536)
    llm_input_max_bytes: int = Field(default=65536, ge=1024)
    request_timeout_seconds: float = Field(default=60.0, gt=0, le=80)
    response_reserve_seconds: float = Field(default=5.0, gt=0)
    # ADR 0031：仅后端只读查询挂 RetryPolicy；LLM 与写类节点均不重试
    node_retry_max_attempts: int = Field(default=2, ge=1, le=3)
    node_retry_initial_interval_seconds: float = Field(default=0.5, ge=0)
    backend_timeout_seconds: float = Field(default=5.0, gt=0)
    persist_timeout_seconds: float = 5.0     # node_trace 写库连接（app/storage/node_trace.py）
    multimodal_fetch_timeout_seconds: float = Field(default=5.0, gt=0)  # Excel 附件下载；图片在入口拒绝
    goats_agent_rfq_timeout_seconds: float = Field(default=5.0, gt=0)        # GOATS agent：快速询价参数解析
    goats_agent_instruction_timeout_seconds: float = Field(default=5.0, gt=0)  # GOATS agent：存量兼容指令查询

    # === goats ===
    goats_base_url: str = ""
    goats_client_id: str = ""
    goats_client_secret: str = ""
    goats_extapp_salt: str = ""
    #: 期权业务 GOATS agent 标识（option_rfq_instrument_parser 等内部 endpoint 需要）
    goats_opt_agent_id: str = ""
    goats_opt_agent_sub_id: str = ""
    #: 互换 / 通用业务 GOATS agent 标识（scripts/probe_goats 探针用；生产路径不读）
    goats_com_agent_id: str = ""
    goats_com_agent_sub_id: str = ""

    # === 真实环境测试账号（D2.* probe / 阶段 2 联调用，不进生产路径）===
    eval_room_id: str = ""
    eval_user_id: str = ""
    eval_guid: str = ""

    # === 可观测性 ===
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # ADR 0024 D5：结构化日志格式；auto = development 彩色控制台、其余 JSON（每条带 trace_id）
    log_format: Literal["auto", "json", "console"] = "auto"
    telemetry_masking_enabled: bool = Field(
        default=False,
        description="是否对 Langfuse 和结构化日志启用字段脱敏；默认关闭，所有环境一致",
    )
    telemetry_masking_fields: str = Field(
        default="password,secret,api_key,token,authorization",
        description="脱敏字段名，逗号分隔；仅在开关开启时生效，空列表不隐藏任何字段",
    )
    environment: Literal["development", "staging", "production"] = "development"
    enable_langfuse: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "http://127.0.0.1:3000"
    # Langfuse Remote Experiment webhook：Langfuse UI 点 Run 触发本机数据集实验。
    # 默认关闭（评测入口不随业务上线）；开启但 secret 为空时端点返回 503
    enable_langfuse_webhook: bool = False
    langfuse_webhook_secret: str = ""
    # 联合解析输入较大，导出采用小批次和独立超时；不增加业务模型重试。
    langfuse_timeout_seconds: int = Field(default=15, ge=1)
    langfuse_flush_at: int = Field(default=32, ge=1)
    # 是否信任入站 W3C traceparent（把请求挂到调用方父 Trace）。仅可信网络（测试工作台）开启；
    # 与 environment 解耦（ADR 0024 D5）
    trust_inbound_traceparent: bool = False

    # === Checkpointer（ADR 0009/0021）===
    # 生产必须 true（多轮状态持久化）；开发/CI 默认 false 避免 MySQL 依赖与脏 checkpoint
    use_mysql_checkpointer: bool = False
    # checkpoint 连接池（ADR 0024 D4）：from_conn_string 单连接无重连，生产禁用；
    # pool_recycle 必须小于 MySQL / TDSQL proxy 的 wait_timeout（默认 8h），30 分钟保守
    checkpoint_pool_minsize: int = Field(default=1, ge=1)
    checkpoint_pool_maxsize: int = Field(default=10, ge=1)
    checkpoint_pool_recycle_seconds: int = Field(default=1800, ge=1)

    # === 影子对照 ===
    # shadow 对照用：拦截 *.operate / close_order_* 等"写类"客户端调用，
    # 返回 fake CommonResult，避免 LangGraph 替代客户真下单/真撤单。
    # read 类（query / get / list）正常调真后端。
    # 详见 docs/deploy/shadow-compare-guide.md
    dry_run_backend: bool = False

    # === 兜底回复（DSL v2 env.default_reply,fallback/answer 节点统一文案）===
    default_reply: str = (
        "抱歉，我们目前无法识别您的意图。您可以按照下方格式发送指令：\n"
        "1.期权询价：@机器人欧式看涨，标的代码（或标的名称），执行价，期限\n"
        "示例：@机器人欧式看涨，000155.SZ，80，1M/2M\n"
        "2.期权平仓：@机器人合约编号，平仓名义本金，平仓价格方式\n"
        "示例：@机器人OPTG-SZZSCF20260009，200w，市价下单\n"
        "3.查可平持仓：@机器人查可平持仓\n"
        "4.互换下单：@机器人标的代码（或标的名称），方向，数量，价格类型，交易对手（簿记产品）\n"
        "示例：@机器人600007.SH，买入，1657股，限价6，广发1号或总单"
    )

    # 从 Langfuse 拉提示词（需同时 enable_langfuse=true）
    use_langfuse_prompts: bool = False

    # === 会话记忆窗口（ADR 0024 D4）===
    # history_messages 只保留最近 N 条（user + assistant 各算 1 条；40 ≈ 20 轮）。
    # 企微群 thread 长期存在，无界累加会撑大 prompt / checkpoint；N 由现场 eval 校准
    history_window_messages: int = Field(default=40, ge=2)
    conversation_idle_timeout_seconds: int = Field(default=1800, ge=60)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_model_settings(cls, data: Any) -> Any:
        """拒绝旧环境、dotenv 和构造参数键，只报告名称而不输出配置值。"""
        # dotenv 未识别键仍进入校验输入；进程环境的未知键需另外检查。
        keys = set(os.environ) | (set(data) if isinstance(data, dict) else set())
        legacy = sorted({str(key).upper() for key in keys if str(key).upper().startswith("QWEN_")})
        if legacy:
            raise ValueError("旧模型配置已停用，请迁移为 LLM_* 并配置 LLM_PROVIDER：" + ", ".join(legacy))
        return data

    @model_validator(mode="after")
    def validate_deadline_reserve(self) -> "Settings":
        """保证总体请求期限为回执处理保留时间。"""
        if self.response_reserve_seconds >= self.request_timeout_seconds:
            raise ValueError("response reserve must be shorter than request deadline")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """全局单例，避免重复加载。"""
    return Settings()
