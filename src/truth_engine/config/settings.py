from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from truth_engine.config.feature_flags import FeatureFlags


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRUTH_ENGINE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql://truth_engine:truth_engine@localhost:5432/truth_engine"
    temporal_host: str = "localhost:7233"
    prompt_version: str = "live-v1"
    tier1_model: str = "minimax-m2.5"
    tier2_model: str = "kimi-k2.5"
    tier3_model: str = "gpt-5.4"
    agent_model_overrides: dict[str, str] = Field(default_factory=dict)
    litellm_api_key: SecretStr | None = Field(default=None)
    litellm_api_base: str | None = None
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_max_retries: int = Field(default=2, ge=0)
    agent_max_tool_rounds: int = Field(default=100, ge=1, le=200)
    required_tool_reminder_interval: int = Field(default=10, ge=1, le=50)
    enable_response_schema: bool = True
    tool_result_char_limit: int = Field(default=4000, ge=500, le=20000)
    page_content_char_limit: int = Field(default=12000, ge=1000, le=50000)
    serper_api_key: SecretStr | None = Field(default=None)
    reddit_client_id: SecretStr | None = Field(default=None)
    reddit_client_secret: SecretStr | None = Field(default=None)
    reddit_user_agent: str = "truth-engine/0.1"
    enable_g2_scraping: bool = False
    enable_embedding_dedup: bool = False
    enable_live_outreach: bool = False

    def feature_flags(self) -> FeatureFlags:
        return FeatureFlags(
            enable_g2_scraping=self.enable_g2_scraping,
            enable_embedding_dedup=self.enable_embedding_dedup,
            enable_live_outreach=self.enable_live_outreach,
        )

    def has_serper_search(self) -> bool:
        return self.serper_api_key is not None

    def has_reddit_tools(self) -> bool:
        return self.reddit_client_id is not None and self.reddit_client_secret is not None
