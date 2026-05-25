from pathlib import Path
from typing import Literal

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).parent.parent
_CONFIG_DIR = _ROOT / "config"


def _load_yaml(filename: str) -> dict:
    with open(_CONFIG_DIR / filename) as f:
        return yaml.safe_load(f)


_cfg = _load_yaml("config.yaml")
_prompts = _load_yaml("prompt_templates.yaml")
_goals = _load_yaml("agent_goals.yaml")

app_config: dict = _cfg["app"]
api_config: dict = _cfg["api"]
llm_config: dict = _cfg["llm"]
planning_config: dict = _cfg.get("planning", {"enabled": False})
storage_config: dict = _cfg.get("storage", {})
prompt_templates: dict = _prompts
agent_goals: dict = _goals

DEFAULT_USER_ID = "omkar"

LLMProvider = Literal["openai", "anthropic"]
llm_provider: LLMProvider = llm_config["provider"]


class Settings(BaseSettings):
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    aws_profile: str = "personal-dev"
    aws_region: str = "ap-south-1"
    dynamodb_table: str = "My-health-DB"
    chat_media_bucket: str = storage_config.get("chat_media_bucket", "my-health-chat-media")
    presigned_url_ttl_seconds: int = storage_config.get("presigned_url_ttl_seconds", 900)
    session_list_page_size: int = storage_config.get("session_list_page_size", 50)
    google_search_api_key: str = ""
    google_search_engine_id: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def chat_model(self) -> str:
        return llm_config[llm_provider]["chat_model"]

    @property
    def vision_model(self) -> str:
        return llm_config[llm_provider]["vision_model"]


settings = Settings()
