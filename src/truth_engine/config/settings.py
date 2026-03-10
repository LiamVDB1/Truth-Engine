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
    prompt_version: str = "v0"
    tier1_model: str = "openai/gpt-4.1-mini"
    tier2_model: str = "openai/gpt-4.1"
    tier3_model: str = "openai/gpt-4.1"
    agent_model_overrides: dict[str, str] = Field(default_factory=dict)
    litellm_api_key: SecretStr | None = Field(default=None)
    litellm_api_base: str | None = None
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_max_retries: int = Field(default=2, ge=0)
    agent_max_tool_rounds: int = Field(default=6, ge=1, le=20)
    tool_result_char_limit: int = Field(default=4000, ge=500, le=20000)
    page_content_char_limit: int = Field(default=12000, ge=1000, le=50000)
    openai_api_key: SecretStr | None = Field(default=None)
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
