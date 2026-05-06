from pathlib import Path

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


class Settings(BaseSettings):
    openai_api_key: str
    openai_chat_model: str = llm_config["chat_model"]
    openai_vision_model: str = llm_config["vision_model"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
