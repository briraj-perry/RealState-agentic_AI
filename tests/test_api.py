import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from estate_ai.config import Settings
from estate_ai.db import Job
from estate_ai.main import create_app

HEADERS = {"X-API-Key": "test-admin-secret"}


def test_auth_simulator_and_takeover(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        assert client.get("/api/status").status_code == 401
        status = client.get("/api/status", headers=HEADERS).json()
        assert status["database"] == "MongoDB"
        assert "mongodb_uri" not in status
        assert status["model"] == "gemma4:31b-cloud"
        assert status["ollama_base_url"] == "http://localhost:11434"
        assert status["ollama_configured"]
        assert not status["ollama_api_key_required"]
        data = {"phone": "+91 98765 43210", "text": "Hello", "event_id": "test1"}
        assert client.post("/api/simulator/messages", json=data, headers=HEADERS).json()["accepted"]
        assert not client.post("/api/simulator/messages", json=data, headers=HEADERS).json()["accepted"]
        assert client.post("/api/conversations/919876543210/takeover", headers=HEADERS).json()["paused"]
        assert client.post("/api/conversations/919876543210/resume", headers=HEADERS).status_code == 200
        assert client.get("/api/conversations/919876543210", headers=HEADERS).json()["messages"]


def test_verify_webhook_and_validate_signature(factory, settings):
    settings.whatsapp_verify_token = type(settings.whatsapp_verify_token)("verify-secret")
    settings.whatsapp_app_secret = type(settings.whatsapp_app_secret)("app-secret")
    settings.whatsapp_phone_number_id = "phone-id"
    settings.whatsapp_mode = "live"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "phone-id"},
                            "messages": [
                                {
                                    "id": "wamid.ABC==",
                                    "from": "919876543210",
                                    "timestamp": "1793200000",
                                    "type": "text",
                                    "text": {"body": "Hello"},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    with TestClient(create_app(settings, factory)) as client:
        assert (
            client.get(
                "/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "verify-secret",
                    "hub.challenge": "12345",
                },
            ).text
            == "12345"
        )
        assert client.get("/webhooks/whatsapp").status_code == 403
        assert client.post("/webhooks/whatsapp", content=body).status_code == 403
        headers = {"X-Hub-Signature-256": signature}
        assert client.post("/webhooks/whatsapp", content=body, headers=headers).status_code == 200
        assert client.post("/webhooks/whatsapp", content=body, headers=headers).status_code == 200
        with factory() as session:
            assert session.get(Job, "wa:wamid.ABC==") is not None


def test_live_configuration_fails_closed():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, whatsapp_mode="live")


def test_opt_out_cannot_be_overridden_by_resume(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        client.post(
            "/api/simulator/messages",
            headers=HEADERS,
            json={"phone": "919876543210", "text": "STOP", "event_id": "stop1"},
        )
        assert client.post("/api/conversations/919876543210/resume", headers=HEADERS).status_code == 409
