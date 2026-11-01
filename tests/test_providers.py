import httpx
import pytest

from estate_ai.agent import OllamaClient
from estate_ai.messaging import WhatsAppClient


@pytest.mark.asyncio
async def test_ollama_cloud_payload_and_thinking_is_not_exposed(settings, monkeypatch):
    settings.ollama_base_url = "https://ollama.com"
    settings.ollama_model = "gemma4:31b"
    settings.ollama_api_key = type(settings.ollama_api_key)("fake-key")

    def handler(request):
        assert str(request.url) == "https://ollama.com/api/chat"
        assert request.headers["Authorization"] == "Bearer fake-key"
        import json

        body = json.loads(request.content)
        assert body["model"] == "gemma4:31b"
        assert body["stream"] is False
        assert body["tools"] == [{"type": "function"}]
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "Hello", "thinking": "private reasoning"}}
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    result = await OllamaClient(settings).chat([{"role": "user", "content": "Hi"}], [{"type": "function"}])
    assert result == {"role": "assistant", "content": "Hello"}


@pytest.mark.asyncio
async def test_local_ollama_uses_cloud_tag_without_api_key(settings, monkeypatch):
    def handler(request):
        import json

        assert str(request.url) == "http://localhost:11434/api/chat"
        assert "Authorization" not in request.headers
        body = json.loads(request.content)
        assert body["model"] == "gemma4:31b-cloud"
        assert body["tools"] == [{"type": "function"}]
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Hello"}})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    result = await OllamaClient(settings).chat([{"role": "user", "content": "Hi"}], [{"type": "function"}])
    assert result["content"] == "Hello"


@pytest.mark.asyncio
async def test_remote_ollama_still_requires_key(settings):
    settings.ollama_base_url = "https://ollama.com"
    with pytest.raises(RuntimeError, match="API_KEY"):
        await OllamaClient(settings).chat([], [])


@pytest.mark.asyncio
async def test_whatsapp_adapter_sends_text_to_configured_sender(settings, monkeypatch):
    settings.whatsapp_access_token = type(settings.whatsapp_access_token)("fake-meta-token")
    settings.whatsapp_graph_version = "v26.0"
    settings.whatsapp_phone_number_id = "sender-id"

    def handler(request):
        assert str(request.url) == "https://graph.facebook.com/v26.0/sender-id/messages"
        assert request.headers["Authorization"] == "Bearer fake-meta-token"
        import json

        body = json.loads(request.content)
        assert body["to"] == "919876543210"
        assert body["text"]["body"] == "Hello buyer"
        return httpx.Response(200, json={"messages": [{"id": "wamid.response"}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    assert await WhatsAppClient(settings).send("919876543210", "Hello buyer") == "wamid.response"
