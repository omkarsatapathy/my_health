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

app_config: dict = _cfg["app"]
api_config: dict = _cfg["api"]
llm_config: dict = _cfg["llm"]
prompt_templates: dict = _prompts

LLMProvider = Literal["openai", "anthropic"]
llm_provider: LLMProvider = llm_config["provider"]


class Settings(BaseSettings):
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def chat_model(self) -> str:
        return llm_config[llm_provider]["chat_model"]

    @property
    def vision_model(self) -> str:
        return llm_config[llm_provider]["vision_model"]


settings = Settings()
