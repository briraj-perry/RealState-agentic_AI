# Estate AI — agent workspace

A single-dealer WhatsApp text assistant using **Gemma 4 31B Cloud through local Ollama**, FastAPI,
LangGraph, Pydantic and SQLAlchemy. The local dashboard is at `/`; API documentation is at `/docs`.

Implemented:

- A bounded LangGraph model/tool loop with six schema-validated, server-scoped tools.
- Inventory search and details, nonfinancial preference memory, budget/offer confirmation,
  site-visit requests and human handoff.
- Conversational recommendations: normally three matching options with verified features, a useful
  comparison and a relevant follow-up. Asking for more uses buyer-scoped recent search history to
  retrieve different matches. Searches support city, locality, BHK, INR budget and a bounded result limit.
  Empty results never silently relax the buyer's criteria; the agent asks which preference to change.
  The agent can use a stated budget provisionally while its explicit confirmation is pending.
- Buyer budgets, property offers and listing asking prices remain distinct. Confirmation requires
  the buyer's exact `CONFIRM <proposal_id>` message; source and confirmation messages are retained.
- Persistent conversation history, inbox/outbox, duplicate inbound-event protection,
  bounded agent retries, WhatsApp signature verification and delivery-status callbacks.
- Immediate STOP handling, human takeover, service-window checks and dealer alerts through the API.
- Local real-model chat and an authenticated API simulator. Simulation NEVER sends WhatsApp messages.
- A responsive five-page dashboard: Overview, Properties, Conversations, Test Your Agent and Settings.
  Saved test conversations exercise the same real agent and tool services as WhatsApp.
- Property photo uploads with previews, private persistent storage, cover photos and photo cards in
  the test chat. JPEG/PNG/WebP uploads are validated, resized and saved without EXIF metadata.
- Excel inventory imports with worksheet/header selection, automatic column suggestions, editable
  mapping, row validation, INR/lakh/crore conversion and explicit create/update review.

**Not connected or implemented yet:** Google Calendar booking/OAuth, lead-platform ingestion,
outbound templates/campaigns, voice notes/calls, WhatsApp photo/media sending, dealer outbound chat,
multi-tenant authorization, database migrations and automated follow-ups.
Site visits are **requests pending dealer approval**, never confirmed bookings.
Dealer alerts are stored for retrieval via `/api/alerts`; they are not push notifications.

## Quick start (PowerShell)

Python 3.11+ is required. Python 3.12 is a suitable deployment baseline.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env`: set a random `ADMIN_API_KEY` and keep `WHATSAPP_MODE=simulate`.
The default model connection uses your installed, signed-in Ollama:

```dotenv
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:31b-cloud
OLLAMA_API_KEY=
```

Keep the Ollama application running. Sign in with `ollama signin` if needed and check the model:

```powershell
ollama run gemma4:31b-cloud
```

Inference runs in the cloud; local Ollama handles authentication. No separate API key is needed
for localhost. `/api/status` reports configuration only, not whether Ollama is reachable or signed in.

For direct cloud access on deployment, set `OLLAMA_BASE_URL=https://ollama.com`,
`OLLAMA_MODEL=gemma4:31b`, and `OLLAMA_API_KEY` from https://ollama.com/settings/keys.
Model and endpoint remain configurable. Switching to a provider with a different API requires
a new client adapter. Do not paste secrets into chat.

```powershell
.venv\Scripts\python.exe -m uvicorn estate_ai.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 to use the dashboard. Unlock it with `ADMIN_API_KEY` from `.env`.
The key is stored only in this browser tab's session storage; use **Lock workspace** to clear it.
There is no JavaScript build step or separate frontend server. FastAPI serves the UI and APIs together.
The interface uses HTML/CSS/JavaScript to keep this local milestone dependency-free on the frontend.
Fonts have system-font fallbacks if Google Fonts is unavailable.
Open http://127.0.0.1:8000/docs for the API explorer. Supply `X-API-Key` on protected requests.
Use one process: **do not use multiple Uvicorn workers or run CLI chat alongside the API**.
The embedded worker is intentionally serial. It is suitable for a prototype, not a scaled production queue.

You can also stop the API and run:

```powershell
.venv\Scripts\python.exe -m estate_ai.chat
```

This uses real cloud inference and a synthetic buyer identity. Without inventory the assistant
must report no verified matches. It should not invent listings.

## Dashboard workflow

1. **Settings:** inspect the model (`gemma4:31b-cloud`), endpoint, authentication, worker and integration
   configuration. Click **Check connection** to query Ollama's model list. A successful check means
   reachable/listed, not authenticated cloud inference. Credentials are never returned in the settings API.
   Settings are read-only: edit `.env` and restart to change configuration.
2. **Properties:** add or edit dealer-verified inventory. Prices use INR, not lakh units. Set a property
   unavailable to remove it from the agent's recommendations. Search and availability filters are included.
   **Browse templates** offers eight fictional 1–4 BHK examples across Mohali, Chandigarh, Panchkula,
   Zirakpur and Dera Bassi. **Use template** opens an editable draft with a new ID; it stays labelled
   as demo data. **Add sample properties** adds the eight fixtures once without overwriting existing
   listings or resetting edited sample prices. Demo creation/editing requires `ALLOW_DEMO_DATA=true`
   and simulation mode. Demo/real classification cannot be changed after creation.
   In **Add property**, **Edit details** or **Use template**, select photos before saving. Up to 10
   JPEG, PNG or WebP images are accepted per property (8 MB each, maximum 20 megapixels).
   Photos persist in PostgreSQL/SQLite and load only through authenticated API requests. The first
   photo is the cover; remove photos from the editor if needed. Photo upload errors retain the
   property and successful uploads so the remaining images can be retried.
3. **Test Your Agent:** create/select a saved synthetic buyer session and send a message. The backend
   queues it, the real Gemma agent runs its tools, and the page polls for the response. Buyer requirements,
   proposal confirmations and actual tool/handoff activity appear alongside the chat. Confirming a card
   sends the exact `CONFIRM <id>` message through the same backend confirmation flow.
   Every retrieved listing is also shown as a property card with price, locality, BHK and any uploaded
   cover photo. **Show more matches** runs the search tool directly with the most recent filters,
   excludes previously retrieved listings and queues a durable reply; it does not depend on the model
   choosing to run a tool. **Browse all inventory** explicitly starts a new, unrestricted inventory
   search across locations and budgets, without changing saved buyer preferences. Neither action
   sends anything to WhatsApp. Exhausted exact searches are labelled instead of silently widened.
4. **Conversations:** review messages, buyer details, source evidence, offers and visit requests. Use
   **Take over** to pause automation or **Resume AI** to allow future replies. Opt-outs remain blocked.
5. **Overview:** view real counts, saved requirements, visits and pending human follow-ups. Test
   conversations count toward the totals and are labelled. The page refreshes every five seconds.
   Agent-created visits appear immediately after the tool result is saved, including those awaiting
   buyer confirmation. The total counts both awaiting-buyer and awaiting-dealer requests. Visit cards
   show the buyer, property title/reference, location, date/time in IST and confirmation stage, with
   a link to the correct conversation. These remain requests, not calendar bookings.

Test messages never go to WhatsApp. Test session identities and names are kept in a separate table.
Starting a new test creates a fresh buyer context without deleting older sessions. No fake statistics
are generated. Inventory is seeded only on an explicit sample-data action, never at startup.
Browser QA uses an isolated database instead.

## Add inventory and exercise the API

### Import BIBA's inventory sheet

On **Properties**, click **Import Excel**. Upload an `.xlsx` workbook or UTF-8 `.csv`, select a worksheet
and header row, then check the proposed column mapping. The file is parsed locally by the backend;
it is not sent to the model. Nothing is added to inventory until **Import reviewed rows** is clicked.

- Required mappings: City, Bedrooms/BHK and Asking price. Map a Property ID column to update listings
  reliably. If no ID is supplied, an ID is generated from this exact file, worksheet and row; it can change
  when the file changes. Blank titles are derived from the supplied BHK and location.
- Plain numeric prices use the selected INR/lakh/crore unit. Explicit values such as `85 lakh`,
  `₹85,00,000` or `1.2 crore` are normalized to whole INR. Check the rupee values in the preview.
- Existing IDs are rejected unless **Update existing property IDs** is enabled. Updates retain photos
  and existing unmapped core fields. Demo/real classification cannot be changed by import.
- Map optional property details: property type, bathrooms, area/unit, furnishing, amenities, parking,
  floor, address and possession. These fields are returned by inventory tools and shown in the editor.
  Unmapped columns and the original source values are retained separately under **Original sheet
  details · internal only**, not included in buyer-facing tool results. Do not map private owner contacts
  or private notes to public descriptions or amenities.
- Sold/unavailable rows are retained as unavailable and excluded from recommendations. Review the
  default-availability checkbox if the sheet does not provide a status column.
- Rows with errors block import unless **Import valid rows only** is explicitly selected. The preview
  shows the first 100 rows/errors; all rows are validated. Conflicting edits after preview require another
  validation. Repeating a successful commit returns its saved result without importing twice.
- Limits: 8 MB uploaded, 2,000 data rows per worksheet, 80 columns, 100,000 cells and 20 worksheets.
  The importer bounds decompressed `.xlsx` content. Legacy `.xls` files must be saved as `.xlsx` first.
- Formulas must be replaced with their calculated values before import. Macros, embedded pictures
  and external image URLs are not executed/fetched/imported. Add photos through the property editor.
- **Download column template** provides an Excel-compatible CSV header template. Fill it in and save
  as `.xlsx` or UTF-8 CSV. Import previews expire after 24 hours; stored source data remains in the local
  database for provenance and should be included in deployment retention/deletion policies.

After commit, the agent's property tools search the imported inventory immediately. Restart the backend
once after installing this feature so its new routes and tables are loaded. Existing property tables
are preserved; the feature adds import and property-metadata tables.

### Individual property API

```powershell
$headers = @{ "X-API-Key" = "your-admin-key-from-env" }
$property = @{
  id = "MOH-001"; title = "Your verified listing"; city = "Mohali"
  locality = "Sector 70"; bedrooms = 3; asking_price = 8500000
  available = $true; description = "Replace with actual dealer-verified facts"
} | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri http://127.0.0.1:8000/api/properties/MOH-001 -Headers $headers -ContentType application/json -Body $property

$message = @{ phone = "919000000001"; text = "I need a 3 BHK in Mohali, budget 90 lakh"; event_id = "demo-1" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/simulator/messages -Headers $headers -ContentType application/json -Body $message
Start-Sleep -Seconds 5
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/conversations/919000000001 -Headers $headers
```

The example property is an input example, **not verified real inventory**. Replace it before live use.
For explicitly fictional inventory, set `ALLOW_DEMO_DATA=true` and call `POST /api/demo/seed`
or use **Add sample properties** on the Properties page. This creates up to eight sample listings.
Demo listings are flagged and hidden from tools unless allowed. Live mode rejects demo-data permission.

API routes:

| Route | Purpose |
|---|---|
| `GET /api/status` | Model/integration configuration status |
| `POST /api/simulator/messages` | Queue a simulated buyer message (202, async) |
| `GET /api/jobs` | Recent job status and sanitized errors |
| `GET /api/conversations/{phone}` | Recent messages and outbound delivery status |
| `POST /api/conversations/{phone}/takeover` | Pause automation and suppress queued work |
| `POST /api/conversations/{phone}/resume` | Resume future automation unless opted out |
| `GET /api/properties` | Inventory |
| `PUT /api/properties/{id}` | Dealer-provided inventory and verification timestamp |
| `GET /api/proposals` | Buyer budgets, offers and visit requests with evidence |
| `GET /api/alerts` | Dealer handoffs and operational alerts |
| `POST /api/properties/{id}/photos` | Upload a raw JPEG/PNG/WebP body (authenticated) |
| `GET /api/property-photos/{id}` | Read a private property photo |
| `DELETE /api/properties/{id}/photos/{photo_id}` | Remove a photo from that property |
| `GET /api/conversations/{phone}/recommendations` | Actual search-result cards grouped by source message |
| `POST /api/test-sessions/{phone}/more-properties` | Queue more matches using the previous search filters |
| `POST /api/test-sessions/{phone}/browse-properties` | Queue an explicit browse across all inventory |
| `GET, POST /webhooks/whatsapp` | Verification and signed Meta webhook delivery |

## WhatsApp

Follow [the setup guide](docs/WHATSAPP_SETUP.md). A public HTTPS webhook, Meta app/test number,
Meta token/secret and Ollama API key are required. No live account or public endpoint was supplied
with this project, so WhatsApp delivery needs a credentialed smoke test.
Local model access uses your Ollama sign-in; direct cloud access uses an API key.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp
.venv\Scripts\ruff.exe check estate_ai tests
```

Tests use fake model/transport implementations, real LangGraph execution and temporary SQL databases.
They do not establish real Gemma response quality or Meta delivery. Evaluate English, Hindi, Hinglish
and Punjabi conversations with the real model before a buyer pilot.

## Operational boundaries

- SQLite is the local default. PostgreSQL is supported via a SQLAlchemy URL such as
  `postgresql+psycopg://user:password@localhost:5432/estate`. PostgreSQL still needs integration testing.
- Schema creation uses `create_all` for this first milestone. Add Alembic migrations before evolving
  a live database; `create_all` does not migrate existing tables.
- This is a single-dealer service with one admin API key, not a multi-agency production system.
- Only customer-initiated text conversations are handled. No lead number is automatically contacted.
  Freeform sends require a recent inbound message and no opt-out. Templates and consent acquisition
  for proactive outreach are intentionally deferred.
- `accepted` means Meta accepted a message. `delivered`/`read` require signed status callbacks.
  An ambiguous send is marked `delivery_unknown` and requires review, avoiding blind retries.
- Repeated model failures pause the conversation. Check `/api/jobs` and `/api/alerts`.
- STOP, UNSUBSCRIBE and listed Hindi/Punjabi stop commands opt out immediately. The model is also
  instructed to hand off broader natural-language requests. Expand and evaluate multilingual opt-out
  detection before production. Opted-out contacts cannot be resumed through the pause endpoint.
- A send already accepted by Meta cannot be recalled by a takeover. SQLite write transactions can
  delay a concurrent administrative update while tool actions are being processed.
- Conversation and evidence records contain personal data. Use TLS, restricted database access,
  encrypted storage/backups and retention/deletion procedures for deployment. No claim of production
  privacy compliance is made by this prototype.
- No cross-customer lookup tool or raw SQL tool is exposed. Tool schemas and backend checks constrain
  actions; prompting alone cannot guarantee that every generated sentence is accurate. Pilot evaluation
  and further response-grounding checks remain necessary.

Provider references: [Ollama cloud](https://docs.ollama.com/cloud),
[Ollama chat API](https://docs.ollama.com/api/chat),
[LangGraph](https://docs.langchain.com/oss/python/langgraph/quickstart),
[WhatsApp developer hub](https://business.whatsapp.com/developers/developer-hub).
