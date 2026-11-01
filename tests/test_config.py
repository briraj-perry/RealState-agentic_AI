import pytest
from pydantic import ValidationError

from estate_ai.config import Settings


def live_settings(**overrides):
    values = {
        "_env_file": None,
        "whatsapp_mode": "live",
        "admin_api_key": "real-admin-secret",
        "whatsapp_access_token": "test-token",
        "whatsapp_phone_number_id": "test-id",
        "whatsapp_app_secret": "test-secret",
        "whatsapp_verify_token": "test-verify",
        "whatsapp_graph_version": "v26.0",
    }
    return Settings(**(values | overrides))


@pytest.mark.parametrize(
    "endpoint", ["http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"]
)
def test_live_whatsapp_allows_local_ollama_without_key(endpoint):
    settings = live_settings(ollama_base_url=endpoint)
    assert not settings.ollama_requires_api_key


def test_live_remote_ollama_requires_key():
    with pytest.raises(ValidationError, match="OLLAMA_API_KEY"):
        live_settings(ollama_base_url="https://ollama.com")
    assert live_settings(
        ollama_base_url="https://ollama.com", ollama_api_key="test-key"
    ).ollama_requires_api_key


def test_localhost_lookalike_is_remote():
    assert Settings(_env_file=None, ollama_base_url="https://localhost.example.com").ollama_requires_api_key


@pytest.mark.parametrize(
    "endpoint", ["ftp://localhost", "http://", "https://localhost@evil.example", "http://localhost?token=x"]
)
def test_ollama_endpoint_rejects_invalid_urls(endpoint):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ollama_base_url=endpoint)
