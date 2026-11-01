import httpx


class WhatsAppClient:
    def __init__(self, settings):
        self.settings = settings

    async def send(self, phone: str, text: str) -> str:
        s = self.settings
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://graph.facebook.com/{s.whatsapp_graph_version}/{s.whatsapp_phone_number_id}/messages",
                headers={"Authorization": f"Bearer {s.whatsapp_access_token.get_secret_value()}"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": phone,
                    "type": "text",
                    "text": {"preview_url": False, "body": text},
                },
            )
            response.raise_for_status()
            return response.json()["messages"][0]["id"]
