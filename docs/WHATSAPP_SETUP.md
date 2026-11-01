# Connect the first WhatsApp test conversation

The buyer's output appears in WhatsApp once Meta routes the buyer message to this backend and
the backend replies through the Cloud API. The existing WhatsApp Business app history and property
platform notifications are not automatically imported.

1. Create/sign in to Meta for Developers and create an app with the WhatsApp business messaging
   use case. Follow the setup shown in your current Meta dashboard; labels can change.
2. In WhatsApp API setup, obtain a **test sender number**, its **Phone Number ID**, and an
   **access token**. Add and verify your own WhatsApp number as an allowed test recipient where required.
   The Phone Number ID is not the visible telephone number or WhatsApp Business Account ID.
3. Find the app's **App Secret**. Generate a separate random **webhook verification token**.
   Do not use the access token or App Secret as the verification token.
4. Set the following in your local `.env` (never source control or chat):

   ```dotenv
   ADMIN_API_KEY=<random-long-secret>
   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_MODEL=gemma4:31b-cloud
   OLLAMA_API_KEY=
   WHATSAPP_MODE=live
   ALLOW_DEMO_DATA=false
   WHATSAPP_ACCESS_TOKEN=<meta-token>
   WHATSAPP_PHONE_NUMBER_ID=<phone-number-id>
   WHATSAPP_APP_SECRET=<app-secret>
   WHATSAPP_VERIFY_TOKEN=<your-random-verification-token>
   WHATSAPP_GRAPH_VERSION=<supported-version-from-meta-dashboard>
   ```

5. Keep local Ollama running and signed in (`ollama signin`); verify `ollama run gemma4:31b-cloud`
   works. Localhost needs no separate Ollama API key, including with live WhatsApp.
   Load actual dealer-verified inventory through the authenticated property API. Do not promote
   demonstration examples into real listings. Restart the backend after configuration changes.
6. Make port 8000 reachable through a trusted HTTPS development tunnel or HTTPS deployment.
   Bind locally for a development tunnel. Expose the webhook without exposing admin credentials;
   restrict admin routes at your proxy when deploying. No tunnel or deployment is created automatically.
7. Set Meta's callback URL to `https://<your-host>/webhooks/whatsapp`. Enter the verification token
   from step 4. The backend returns Meta's challenge only for a matching token.
8. Subscribe the app to WhatsApp **messages** webhook events for the intended account. Ensure
   the app/account subscription is active; saving a callback URL alone may not enable delivery.
9. From the verified test recipient, send **Hi** to the Meta test sender. If your Meta setup presents
   a prescribed test-message flow, complete that first. The backend handles inbound text and sends
   freeform responses only while the inbound messaging window is open.
10. Inspect `GET /api/status`, `/api/jobs`, `/api/conversations/<international-digits>` and `/api/alerts`
    with your admin key. Check the actual WhatsApp reply and delivery-status callbacks.

Test the following before letting real buyers use it:

- Ask for a listing that exists; then ask for an unavailable one.
- Say `My budget is 90 lakh`; check the proposed INR amount and reply with its exact `CONFIRM` code.
- Offer a lower amount; verify it is recorded as an offer requiring dealer approval.
- Request tomorrow's visit; check the absolute time and that the response says **request**, not booked.
- Send `human`; verify new automated responses stop and a dealer alert appears.
- In a separate test contact/session, send `STOP`; verify further automation is suppressed.
- Replay a signed inbound event; verify it does not produce a second response.

Troubleshooting:

- **No webhook:** check the public HTTPS URL, callback verification, event subscriptions and phone ID.
- **403:** verify App Secret/signature or verification token. Do not bypass signature validation.
- **Agent job failed:** verify local Ollama is running, signed in and able to use the configured model.
  Direct cloud endpoints additionally require an Ollama API key. Error bodies are
  deliberately not copied into general logs because they can include sensitive data.
- **No outbound reply:** check token expiry, test-recipient verification, opt-out/pause state and inbound window.
- **`delivery_unknown`:** check Meta and customer history before manually sending anything. Timeout does
  not establish that Meta failed to send. There is intentionally no automatic resend endpoint yet.

Use a suitable business token lifecycle and business onboarding before moving beyond the test number.
Check current WhatsApp policies and account eligibility before production or proactive outreach.
Calendar OAuth, templates, lead-source APIs and Business App coexistence are separate follow-up work.

Official starting points: [Meta WhatsApp docs](https://developers.facebook.com/docs/whatsapp/cloud-api/),
[WhatsApp developer hub](https://business.whatsapp.com/developers/developer-hub),
[Ollama cloud authentication](https://docs.ollama.com/cloud).
