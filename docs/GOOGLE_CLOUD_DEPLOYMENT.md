# Cloud Run hosting + MongoDB Atlas

Project: **AILearning**, ID `gen-lang-client-0081910278`, Mumbai `asia-south1`.
Repository: `briraj-perry/RealState-agentic_AI`.

## Services and resource limits

| Component | Location/purpose |
| --- | --- |
| Cloud Run | One app container, 1 vCPU, 512 MiB, maximum 1 instance, concurrency 2 |
| Artifact Registry | The container image needed for deployment; built on GitHub runners |
| IAM / Workload Identity Federation | Keyless GitHub authentication and the app's runtime identity |
| MongoDB Atlas | All inventory, photos, conversations, proposals, jobs, imports and audit records |
| GitHub Actions secrets | Runtime credentials injected into the Cloud Run revision |
| Ollama Cloud | External LLM endpoint; no model runs on Google Cloud |

The pipeline does **not** provision or use Cloud SQL, Firestore, Google Secret Manager,
Cloud Storage buckets, Redis, Pub/Sub, Cloud Tasks, Cloud Scheduler, Cloud Build, VPC
connectors or Cloud NAT. Cloud Run's platform networking and standard runtime logging
still exist; a literal zero-dependency Cloud Run service is not possible. No Google
database is used. Atlas can be hosted on AWS if you want the database outside GCP entirely.

The existing background worker needs continuously allocated CPU and minimum **one**
instance. This is a small, single-instance configuration, **not scale-to-zero/free
hosting**. Scaling to zero safely requires a different request/job execution design.
Both Cloud Run and image storage can incur charges. Model and Atlas limits are separate.
Choose billing alerts before leaving the app running. See [Cloud Run pricing](https://cloud.google.com/run/pricing).

## 1. MongoDB Atlas setup

1. Sign in at [MongoDB Atlas](https://cloud.mongodb.com/). Check whether an existing
   organization/project already contains a cluster before creating another.
2. For initial testing, select the **Free** cluster option if available in the chosen
   region. Choose AWS as the provider to keep database hosting outside Google Cloud.
   Review the current cluster summary before creation; do not accidentally select a paid tier.
3. Create a database user restricted to `readWrite` on the `estate_ai` database.
   Set a strong unique password yourself. This is distinct from your Atlas website login.
4. Under **Connect → Drivers → Python**, copy the `mongodb+srv://...` connection string
   privately, replace the password placeholder with its URL-encoded value, and retain
   `retryWrites=true&w=majority`. Never paste credentials into this chat or the repository.
5. Configure **Network Access** so the app can reach Atlas. Cloud Run's default outbound
   addresses are dynamic. A strict fixed-IP allowlist needs additional networking services,
   which this minimal deployment intentionally does not create. Allowing all IPs in Atlas
   is an explicit security tradeoff: TLS, a strong restricted database user, credential
   rotation and monitoring remain necessary. Do not broaden an existing production
   cluster's allowlist without reviewing that effect; use a separate test cluster instead.

Use Atlas or a MongoDB replica set: the app requires multi-document transactions.
It refuses a standalone server. Photos are stored in MongoDB itself, so monitor your
cluster's storage limits. A large spreadsheet that exceeds MongoDB's per-document
limit returns HTTP 413; split it into smaller files. No cloud photo storage is created.

References: [Atlas free cluster setup](https://www.mongodb.com/docs/atlas/tutorial/deploy-free-tier-cluster/),
[free cluster limits](https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/),
[PyMongo transactions](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/transactions/).

## 2. Create the hosting identities/registry

Billing must already be enabled for AILearning. In **Google Cloud Shell (Bash)**,
review and run the repository's `scripts/setup-google-cloud-identity.sh`.

It creates `estate-ai-deploy`, `estate-ai-runtime`, the Mumbai `estate-ai` image
repository, and the `estate-ai-github` Workload Identity pool/provider. It gives:

- Deploy identity: Cloud Run admin in this project, image writer only on the Estate AI
  registry, and permission to act as the runtime identity.
- Runtime identity: no Cloud SQL, Secret Manager or other project-level data roles.
- GitHub trust: only repository ID `1441703959`, owner ID `304775270`, main branch,
  and the production environment. No downloadable service-account keys are created.

The script is idempotent for its own named resources. It refuses to silently change
the condition on a preexisting provider. It does not delete other project resources,
create a database, change database credentials, or copy local `.env` values.

APIs enabled earlier in setup do not imply resources were created. The prior Cloud SQL
plan was cancelled before provisioning. The revised setup no longer enables SQL or
Secret Manager APIs, and this pipeline never calls them. Existing unrelated Firebase
resources in AILearning are left alone.

## 3. GitHub production configuration

Repository → **Settings → Environments → production**. Restrict deployment branches
to main; optionally enable required reviewers. Set these environment variables:

| Variable | Value |
| --- | --- |
| `GCP_PROJECT_ID` | `gen-lang-client-0081910278` |
| `GCP_REGION` | `asia-south1` |
| `WIF_PROVIDER` | `projects/879940632641/locations/global/workloadIdentityPools/estate-ai-github/providers/github` |
| `DEPLOY_SERVICE_ACCOUNT` | `estate-ai-deploy@gen-lang-client-0081910278.iam.gserviceaccount.com` |
| `RUNTIME_SERVICE_ACCOUNT` | `estate-ai-runtime@gen-lang-client-0081910278.iam.gserviceaccount.com` |
| `ARTIFACT_REPOSITORY` | `estate-ai` (default) |
| `CLOUD_RUN_SERVICE` | `estate-ai` (default) |
| `MONGODB_DATABASE` | `estate_ai` (default) |
| `OLLAMA_BASE_URL` | `https://ollama.com` (default) |
| `OLLAMA_MODEL` | `gemma4:31b` (default) |
| `WHATSAPP_MODE` | `simulate` initially |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta's numeric Phone Number ID, when connecting WhatsApp |
| `WHATSAPP_GRAPH_VERSION` | Supported version shown in your Meta dashboard |

Add **production environment secrets**, privately through GitHub:

| Secret | Purpose |
| --- | --- |
| `MONGODB_URI` | Atlas connection string with the restricted database user's credentials |
| `ADMIN_API_KEY` | Long random dashboard key |
| `OLLAMA_API_KEY` | Remote Ollama Cloud API key |
| `WHATSAPP_ACCESS_TOKEN` | Meta token, required in live mode |
| `WHATSAPP_APP_SECRET` | Meta app secret, required in live mode |
| `WHATSAPP_VERIFY_TOKEN` | Your random webhook verification secret, needed for Meta callback verification |

WhatsApp secrets may be omitted during simulation. Live mode requires every WhatsApp
credential plus phone ID and Graph version. Use a suitable long-lived Meta token before
production use; the initial test token expires.

Secrets are passed to a private temporary JSON file on the runner, then to Cloud Run
environment variables. The temporary file is removed in an `always()` cleanup step and
is never an artifact or Docker build input. **This deliberately avoids Secret Manager:**
people with sufficient Cloud Run configuration access can view environment values.
Restrict deploy/admin permissions and rotate credentials after accidental exposure.

Cloud Run cannot reach Ollama on your PC's `localhost`. The cloud defaults use
[native Ollama Cloud](https://docs.ollama.com/cloud), requiring its API key. Model
and endpoint remain configurable; another API protocol needs a client adapter.

## 4. Deploy and connect WhatsApp

Push to main, or Actions → **Deploy Google Cloud Run → Run workflow**. CI starts a
disposable MongoDB replica set on the GitHub runner and runs the real application
suite, concurrency/transaction tests, and a Docker HTTP smoke test. It creates no
test resources on Google Cloud. Pull requests run CI without deployment credentials.

The deploy job runs only after CI succeeds. It builds the image on the GitHub runner,
pushes the commit-SHA image to Artifact Registry, and deploys Cloud Run. Missing config
fails explicitly. The job summary prints the dashboard and webhook URLs after health
verification. The service starts only when MongoDB is reachable.

Open the dashboard and unlock it using `ADMIN_API_KEY`. Its status page reports
**MongoDB**; it never displays the connection string. Demo inventory is disabled in
the cloud deployment. Populate real inventory or import BIBA's sheet.

Set Meta's callback to `https://YOUR_SERVICE_URL/webhooks/whatsapp` and use your
`WHATSAPP_VERIFY_TOKEN` value. GET verification works during simulation; actual inbound
POSTs/replies require live mode, valid Meta signatures, and Meta's publishing rules.

Public Cloud Run access allows Meta to reach the webhook. Admin APIs still require
the dashboard key. Keep the database user/URI out of client-side JavaScript.

## Local development and old data

Run `docker compose up -d --wait` for local loopback-only MongoDB, then configure:

```dotenv
MONGODB_URI=mongodb://127.0.0.1:27017/?replicaSet=rs0
MONGODB_DATABASE=estate_ai
```

An Atlas URI also works locally. Existing SQLite `.db` files remain untouched and are
not automatically copied to Atlas. To preserve an earlier workspace, stop the app,
configure the destination MongoDB, back up the source, and run:

```powershell
.venv\Scripts\python.exe -m estate_ai.migrate_sqlite --source estate.db
```

The migration reads SQLite in read-only mode, commits batches atomically to MongoDB,
keeps existing destination records, and can resume after interruption. It includes
inventory, photos, chats, proposals, import history and audits. Review stored contacts
and demo inventory before using that data with a live sender.

## Operation

One Uvicorn process and one maximum Cloud Run instance are configured. A MongoDB
lease prevents old/new revisions from processing jobs simultaneously during normal
rollouts. It renews every 15 seconds and expires after 90 seconds if an instance dies.
Model calls run outside short database transactions. Concurrent writes use revision
checks and return HTTP 409; reload and retry those admin operations.

An interrupted external send can still have an ambiguous outcome; review
`delivery_unknown` before retrying. Monitor Cloud Run failures and Atlas storage.
Revert and push a known-good commit for rollback; review document compatibility first.
Configure image retention so old revisions do not accumulate indefinitely.
