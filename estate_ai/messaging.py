import httpx


class WhatsAppClient:
    def __init__(self, settings):
        self.settings = settings

    async def send(self, phone: str, text: str) -> str:
        return await self._send(phone, "text", {"preview_url": False, "body": text})

    async def send_template(self, phone: str, template: dict) -> str:
        return await self._send(phone, "template", template)

    async def _send(self, phone: str, message_type: str, content: dict) -> str:
        s = self.settings
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://graph.facebook.com/{s.whatsapp_graph_version}/{s.whatsapp_phone_number_id}/messages",
                headers={"Authorization": f"Bearer {s.whatsapp_access_token.get_secret_value()}"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": phone,
                    "type": message_type,
                    message_type: content,
                },
            )
            response.raise_for_status()
            return response.json()["messages"][0]["id"]
