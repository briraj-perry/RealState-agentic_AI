from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_api_key: SecretStr = SecretStr("")
    mongodb_uri: SecretStr = SecretStr("mongodb://127.0.0.1:27017/?replicaSet=rs0")
    mongodb_database: str = Field(default="estate_ai", pattern=r"^[a-zA-Z0-9_-]{1,63}$")
    business_name: str = "Estate AI Realty"
    allow_demo_data: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: SecretStr = SecretStr("")
    ollama_model: str = "gemma4:31b-cloud"
    whatsapp_mode: Literal["simulate", "live"] = "simulate"
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_phone_number_id: str = ""
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_graph_version: str = Field(default="", pattern=r"^(v\d+\.\d+)?$")
    worker_enabled: bool = True

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
        ):
            raise ValueError("OLLAMA_BASE_URL must be an HTTP(S) URL without credentials, query or fragment")
        return value.rstrip("/")

    @property
    def ollama_requires_api_key(self) -> bool:
        return urlsplit(self.ollama_base_url).hostname not in {"localhost", "127.0.0.1", "::1"}

    @model_validator(mode="after")
    def validate_secrets(self):
        if self.whatsapp_mode == "live":
            required = [
                self.admin_api_key.get_secret_value(),
                self.whatsapp_access_token.get_secret_value(),
                self.whatsapp_phone_number_id,
                self.whatsapp_app_secret.get_secret_value(),
                self.whatsapp_verify_token.get_secret_value(),
                self.whatsapp_graph_version,
            ]
            if not all(required) or self.admin_api_key.get_secret_value().startswith("replace-"):
                raise ValueError("Live mode requires admin and all WhatsApp credentials/version")
            if self.ollama_requires_api_key and not self.ollama_api_key.get_secret_value():
                raise ValueError("Remote Ollama requires OLLAMA_API_KEY; localhost uses Ollama's sign-in")
            if self.allow_demo_data:
                raise ValueError("Demo inventory is forbidden in live WhatsApp mode")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
