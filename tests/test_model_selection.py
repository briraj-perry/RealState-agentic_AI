import json
import stat

import httpx
import pytest
from fastapi.testclient import TestClient

from estate_ai import model_providers
from estate_ai.db import Message, Property
from estate_ai.main import create_app
from estate_ai.model_providers import ModelSelection, read_selection, save_selection
from estate_ai.workflows import Worker, enqueue


@pytest.fixture
def selection_file(tmp_path, monkeypatch):
    path = tmp_path / ".env.model"
    monkeypatch.setattr(model_providers, "MODEL_FILE", path)
    return path


def intercept(monkeypatch, handler):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handler)),
    )


def test_validate_and_save_model_without_returning_key(settings, selection_file, monkeypatch):
    def respond(request):
        assert request.headers["x-goog-api-key"] in {"example-key", "invalid-key"}
        body = json.loads(request.content)
        assert body["contents"][0]["parts"] == [{"text": "Reply with OK without calling a tool."}]
        if request.headers["x-goog-api-key"] == "invalid-key":
            return httpx.Response(403, json={"error": "invalid-key"})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})

    intercept(monkeypatch, respond)
    client = TestClient(create_app(settings))
    route = "/api/settings/model"
    payload = {"provider": "gemini", "model": "models/gemini-example", "api_key": " example-key "}
    assert client.put(route, json=payload).status_code == 401
    headers = {"X-API-Key": settings.admin_api_key.get_secret_value()}
    result = client.put(route, headers=headers, json=payload)
    assert result.json() == {"provider": "gemini", "model": "gemini-example", "model_key_configured": True}
    assert stat.S_IMODE(selection_file.stat().st_mode) == 0o600
    assert read_selection().api_key.get_secret_value() == "example-key"
    result = client.put(route, headers=headers, json=payload | {"api_key": "invalid-key"})
    assert result.status_code == 502 and "invalid-key" not in result.text
    result = client.put(route, headers=headers, json=payload | {"model": "gemini-other", "api_key": ""})
    assert result.json()["model"] == "gemini-other"
    assert read_selection().api_key.get_secret_value() == "example-key"
    assert client.delete(route, headers=headers).json()["provider"] == "ollama"
    assert not selection_file.exists()


@pytest.mark.parametrize(
    ("provider", "host", "header", "key"),
    [
        ("gemini", "generativelanguage.googleapis.com", "x-goog-api-key", "test-key"),
        ("anthropic", "api.anthropic.com", "x-api-key", "test-key"),
        ("openai", "api.openai.com", "authorization", "Bearer test-key"),
    ],
)
async def test_active_model_runs_the_existing_tool_loop(
    provider, host, header, key, factory, settings, selection_file, monkeypatch
):
    phone = "919000000001"
    name = "get_property_details"
    args = {"property_id": "p1"}
    function = {"name": name, "arguments": json.dumps(args)}
    tool_id = "call_test"
    gemini_call = {"functionCall": {"name": name, "args": args, "id": tool_id}, "thoughtSignature": "opaque"}
    anthropic_call = {"type": "tool_use", "id": tool_id, "name": name, "input": args}
    openai_call = {"type": "function", "id": tool_id, "function": function}
    first = {
        "gemini": {"candidates": [{"content": {"parts": [gemini_call]}}]},
        "anthropic": {"content": [anthropic_call]},
        "openai": {"choices": [{"message": {"tool_calls": [openai_call], "content": None}}]},
    }
    reply = "The apartment is available."
    last = {
        "gemini": {
            "candidates": [{"content": {"parts": [{"text": "hidden", "thought": True}, {"text": reply}]}}]
        },
        "anthropic": {"content": [{"type": "text", "text": reply}]},
        "openai": {"choices": [{"message": {"content": reply}}]},
    }
    requests = []

    def respond(request):
        assert request.url.host == host and request.headers[header] == key
        body = json.loads(request.content)
        requests.append(body)
        assert "tools" in body
        if len(requests) == 1:
            return httpx.Response(200, json=first[provider])
        if provider == "gemini":
            assert body["contents"][-2]["parts"] == [gemini_call]
            result = body["contents"][-1]["parts"][0]["functionResponse"]
            assert result["id"] == tool_id
            assert "Apartment" in json.dumps(result["response"])
        elif provider == "anthropic":
            assert body["messages"][-2]["content"] == [anthropic_call]
            result = body["messages"][-1]["content"][0]
            assert result["tool_use_id"] == tool_id and "Apartment" in result["content"]
        else:
            assert body["messages"][-2]["tool_calls"] == [openai_call]
            result = body["messages"][-1]
            assert result["tool_call_id"] == tool_id and "Apartment" in result["content"]
        return httpx.Response(200, json=last[provider])

    intercept(monkeypatch, respond)
    worker = Worker(factory, settings)
    save_selection(ModelSelection(provider=provider, model=f"{provider}-example", api_key="test-key"))
    with factory() as session:
        session.add(Property(id="p1", title="Apartment", city="Mohali", bedrooms=3, asking_price=8500000))
        session.commit()
    assert enqueue(factory, "provider-message", phone, "Tell me about p1", "simulate")
    await worker.tick()
    with factory() as session:
        assert session.get(Message, "reply:provider-message").content == reply
    assert len(requests) == 2
