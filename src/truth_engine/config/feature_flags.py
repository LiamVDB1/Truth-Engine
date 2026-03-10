from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FeatureFlags(BaseModel):
    model_config = ConfigDict(frozen=True)

    enable_g2_scraping: bool = False
    enable_embedding_dedup: bool = False
    enable_live_outreach: bool = False
