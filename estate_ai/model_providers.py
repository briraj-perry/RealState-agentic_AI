"""Tool-capable model connections and the local workspace's active selection."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

import httpx
from pydantic import BaseModel, Field, SecretStr, field_validator

PROVIDERS = {
    "ollama": "Ollama",
    "gemini": "Google Gemini",
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI",
}
MODEL_FILE = Path(".env.model")


class ModelSelection(BaseModel):
    provider: Literal["gemini", "anthropic", "openai"]
    model: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    api_key: SecretStr = SecretStr("")

    @field_validator("model", mode="before")
    @classmethod
    def strip_model(cls, value):
        return value.strip().removeprefix("models/") if isinstance(value, str) else value

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        if not isinstance(value, str):
            return value
        value = value.strip()
        if len(value) > 4096 or any(not 33 <= ord(char) <= 126 for char in value):
            raise ValueError("Enter a valid API key")
        return value


def read_selection() -> ModelSelection | None:
    try:
        return ModelSelection.model_validate_json(MODEL_FILE.read_bytes())
    except FileNotFoundError:
        deployed = os.environ.get("ESTATE_HOSTED_MODEL")
        return ModelSelection.model_validate_json(deployed) if deployed else None


def save_selection(selection: ModelSelection) -> None:
    # Replace the credential file atomically. NamedTemporaryFile creates it with user-only permissions.
    with NamedTemporaryFile(dir=MODEL_FILE.parent, prefix=".env.model.", delete=False) as stream:
        temp = Path(stream.name)
    try:
        data = selection.model_dump(exclude={"api_key"})
        data["api_key"] = selection.api_key.get_secret_value()
        temp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temp, MODEL_FILE)
    finally:
        temp.unlink(missing_ok=True)


def model_status(settings):
    selection = read_selection()
    if selection:
        return {"provider": selection.provider, "model": selection.model, "model_key_configured": True}
    return {
        "provider": "ollama",
        "model": settings.ollama_model,
        "model_key_configured": bool(settings.ollama_api_key.get_secret_value()),
    }


def _messages_and_system(messages):
    system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
    return [message for message in messages if message["role"] != "system"], system


def _tool_calls_as_blocks(messages, *, gemini):
    """Replay provider content and combine parallel tool results into one user turn."""
    conversation = []
    results = []
    block_key = "parts" if gemini else "content"
    for message in messages:
        role = message["role"]
        if role == "tool":
            if gemini:
                response = {"name": message["tool_name"], "response": json.loads(message["content"])}
                if message.get("tool_call_id"):
                    response["id"] = message["tool_call_id"]
                results.append({"functionResponse": response})
            else:
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": message["tool_call_id"],
                        "content": message["content"],
                    }
                )
            continue
        if results:
            conversation.append({"role": "user", block_key: results})
            results = []
        blocks = message.get("provider_content")
        if blocks is None:
            blocks = [{"text": message["content"]}]
            if not gemini:
                blocks[0]["type"] = "text"
        if gemini and role == "assistant":
            role = "model"
        conversation.append({"role": role, block_key: blocks})
    if results:
        conversation.append({"role": "user", block_key: results})
    if conversation and conversation[0]["role"] != "user":
        text = {"text": "The following is the recent conversation history."}
        if not gemini:
            text["type"] = "text"
        conversation.insert(0, {"role": "user", block_key: [text]})
    return conversation


class HostedModel:
    def __init__(self, selection: ModelSelection):
        self.selection = selection

    async def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            if self.selection.provider == "gemini":
                return await self._gemini(client, messages, tools)
            if self.selection.provider == "anthropic":
                return await self._anthropic(client, messages, tools)
            return await self._openai(client, messages, tools)

    async def _openai(self, client, messages, tools):
        turns = []
        for message in messages:
            turn = {
                key: message[key]
                for key in ("role", "content", "tool_calls", "tool_call_id")
                if key in message
            }
            turns.append(turn)
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.selection.api_key.get_secret_value()}"},
            json={"model": self.selection.model, "messages": turns, **({"tools": tools} if tools else {})},
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        return {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls") or [],
        }

    async def _anthropic(self, client, messages, tools):
        messages, system = _messages_and_system(messages)
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.selection.api_key.get_secret_value(),
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": self.selection.model,
                "max_tokens": 4096,
                "system": system,
                "messages": _tool_calls_as_blocks(messages, gemini=False),
                "tools": [
                    {
                        "name": function["name"],
                        "description": function["description"],
                        "input_schema": function["parameters"],
                    }
                    for function in (tool["function"] for tool in tools)
                ],
            },
        )
        response.raise_for_status()
        blocks = response.json()["content"]
        return {
            "role": "assistant",
            "content": "".join(block["text"] for block in blocks if block["type"] == "text"),
            "tool_calls": [
                {"id": block["id"], "function": {"name": block["name"], "arguments": block["input"]}}
                for block in blocks
                if block["type"] == "tool_use"
            ],
            "provider_content": blocks,
        }

    async def _gemini(self, client, messages, tools):
        messages, system = _messages_and_system(messages)
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.selection.model}:generateContent",
            headers={"x-goog-api-key": self.selection.api_key.get_secret_value()},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": _tool_calls_as_blocks(messages, gemini=True),
                **(
                    {
                        "tools": [
                            {
                                "functionDeclarations": [
                                    {
                                        "name": function["name"],
                                        "description": function["description"],
                                        "parametersJsonSchema": function["parameters"],
                                    }
                                    for function in (tool["function"] for tool in tools)
                                ]
                            }
                        ]
                    }
                    if tools
                    else {}
                ),
            },
        )
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        return {
            "role": "assistant",
            "content": "".join(part.get("text", "") for part in parts if not part.get("thought")),
            "tool_calls": [
                {
                    "id": call.get("id"),
                    "function": {"name": call["name"], "arguments": call.get("args", {})},
                }
                for call in (part["functionCall"] for part in parts if "functionCall" in part)
            ],
            # Gemini requires its original parts, including opaque thought signatures, on follow-up.
            "provider_content": parts,
        }
