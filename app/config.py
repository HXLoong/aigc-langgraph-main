"""全局配置：从环境变量加载，pydantic 校验。"""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # === MySQL ===
    # checkpoint：给 AIOMySQLSaver 用，需要 mysql://user:pass@host:port/db 格式
    checkpoint_mysql_uri: str = Field(..., description="LangGraph checkpoint 库")
    # 业务：给 SQLAlchemy 用，需要 mysql+aiomysql://user:pass@host:port/db 格式
    business_mysql_uri: str = Field(..., description="业务数据库")

    # === LLM ===
    qwen_api_base: str
    qwen_api_key: str
    qwen_model_standard: str = "qwen3.5-32b"
    qwen_model_thinking: str = "qwen3.5-32b"
    qwen_model_vl: str = "qwen-vl-max-latest"

    anthropic_api_key: str | None = None

    # === 后端业务 API ===
    otc_api_base_url: str
    otc_api_secret: str

    # === goats ===
    goats_base_url: str = ""
    goats_client_id: str = ""
    goats_client_secret: str = ""
    goats_extapp_salt: str = ""

    # === securities-instrument 标的查询 ===
    securities_instrument_url: str = ""
    securities_instrument_key: str = ""

    # 标的池 MySQL（直连查询）
    ticker_mysql_host: str = "172.16.8.27"
    ticker_mysql_port: int = 3306
    ticker_mysql_user: str = "dev-user"
    ticker_mysql_password: str = "xyWss45^772"
    ticker_mysql_db: str = "aigc-test"

    # === 外部搜索 ===
    bocha_api_key: str = ""
    tavily_api_key: str = ""

    # === 可观测性 ===
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    environment: Literal["development", "staging", "production"] = "development"
    enable_langfuse: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_project: str = "otc-agent"

    # === 灰度切换 ===
    use_langgraph: bool = True
    langgraph_traffic_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    shadow_mode: bool = False

    # === Prompt 版本 ===
    # v1：Dify 原始 md 直接加载（兼容/回滚）
    # v2：裁剪版，compose_prompt 把 _base + 意图片段拼接，字符数少 ~20%
    swap_prompt_version: Literal["v1", "v2"] = "v1"

    # 从 Langfuse 拉提示词（需同时 enable_langfuse=true）
    use_langfuse_prompts: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """全局单例，避免重复加载。"""
    return Settings()
