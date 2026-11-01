"""Local real-model chat; uses the same persisted worker and controlled tools as WhatsApp."""

import asyncio
from uuid import uuid4

from estate_ai.config import get_settings
from estate_ai.db import Job, Outbox, connect
from estate_ai.workflows import Worker, enqueue


async def main():
    settings = get_settings()
    if settings.whatsapp_mode == "live":
        raise SystemExit("Use simulation mode for the local chat command")
    if settings.ollama_requires_api_key and not settings.ollama_api_key.get_secret_value():
        raise SystemExit("Set OLLAMA_API_KEY for a remote endpoint, or use local Ollama on port 11434")
    factory = connect(settings.mongodb_uri.get_secret_value(), settings.mongodb_database)
    worker = Worker(factory, settings)
    worker.recover()
    phone = "919000000001"  # Synthetic identity; no external WhatsApp messages are sent.
    print("Estate AI local chat — Gemma cloud, synthetic buyer. Type /quit to exit.")
    while True:
        text = input("You: ").strip()
        if text == "/quit":
            return
        if not text:
            continue
        event_id = "cli:" + uuid4().hex
        enqueue(factory, event_id, phone, text, "simulate")
        for _ in range(480):
            await worker.tick()
            with factory() as session:
                job = session.get(Job, event_id)
                outgoing = session.get(Outbox, event_id)
                if outgoing:
                    print("Assistant:", outgoing.body)
                    break
                if job.state in {"failed", "suppressed"}:
                    print(
                        "Conversation paused, opted out, or processing failed. Inspect /api/jobs and /api/alerts."
                    )
                    break
            await asyncio.sleep(0.5)
        else:
            print("Still pending. Inspect /api/jobs before sending more messages.")


if __name__ == "__main__":
    asyncio.run(main())
