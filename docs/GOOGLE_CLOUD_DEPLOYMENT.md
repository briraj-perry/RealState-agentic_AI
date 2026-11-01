# Google Cloud CI/CD

Pushes to `main` run lint, SQLite tests, a real PostgreSQL worker-election test,
and a Docker build/HTTP smoke test. Deployment runs only after those checks pass.
Pull requests run CI without cloud credentials. Manual deployment is also available
under Actions → Deploy Google Cloud Run → Run workflow.

The target is Cloud Run + Cloud SQL PostgreSQL + Artifact Registry + Secret Manager.
GitHub uses Workload Identity Federation (OIDC); no Google service-account JSON key
is stored in GitHub. The container excludes `.env`, databases, imports, tests and Git.

## 1. GitHub access

The remote is `https://github.com/briraj-perry/RealState-agentic_AI.git`.
The previously selected `sinny777` account returned HTTP 403. Sign in as an account
with write access, or have the owner grant that account collaborator access first:

```powershell
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
git push -u origin main
```

Do not paste personal access tokens into Git remotes or commit `.env`.

## 2. Create cloud resources once

Create/select a Google Cloud project and enable billing. Cloud SQL and the always-on
Cloud Run worker incur charges even while idle; this configuration does not scale
to zero because the current app processes durable jobs in a background loop.
The workflow does not create or delete databases automatically.

Use **Google Cloud Shell (Bash)** for the commands below. Replace the project ID.
Choose the region before creating resources; the example uses Mumbai.

```bash
export PROJECT_ID='YOUR_GOOGLE_CLOUD_PROJECT_ID'
export REGION='asia-south1'
export REPO='briraj-perry/RealState-agentic_AI'
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  sqladmin.googleapis.com secretmanager.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com

gcloud artifacts repositories create estate-ai --repository-format=docker --location="$REGION"
gcloud iam service-accounts create estate-ai-deploy
gcloud iam service-accounts create estate-ai-runtime
export DEPLOY_SA="estate-ai-deploy@$PROJECT_ID.iam.gserviceaccount.com"
export RUNTIME_SA="estate-ai-runtime@$PROJECT_ID.iam.gserviceaccount.com"
for role in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$DEPLOY_SA" --role="$role"
done
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/iam.serviceAccountUser
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/cloudsql.client
```

Create a **PostgreSQL 17 Cloud SQL instance** in the same region using the console.
Select the instance size, availability and automated backup/PITR settings appropriate
to your budget. Enable its public IP for the Cloud Run managed Unix socket connection;
you do not need an `0.0.0.0/0` authorized network. Use second-generation Cloud Run as
configured by the workflow. Create a database named `estate_ai` and a database user
with permissions to create/update tables in that database. Record the instance
connection name, such as `PROJECT_ID:asia-south1:estate-ai-db`.

The app creates missing tables on startup. Existing local SQLite listings, images,
conversations and import history are **not automatically migrated**. Back up data
and review schema compatibility before future upgrades; `create_all` is not a
schema migration tool.

## 3. Configure GitHub OIDC

```bash
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
gcloud iam workload-identity-pools create github --location=global --display-name='GitHub Actions'
gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github \
  --issuer-uri='https://token.actions.githubusercontent.com' \
  --attribute-mapping='google.subject=assertion.sub,attribute.repository=assertion.repository' \
  --attribute-condition="assertion.repository == '$REPO' && assertion.ref == 'refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"
```

For an organization-managed deployment, additionally constrain the provider to
GitHub's immutable `repository_id` and `repository_owner_id` claims to protect
against repository/owner name reuse. Never trust all GitHub repositories.

## 4. Add Secret Manager values

In Google Cloud Console → **Secret Manager**, create these secrets. Add their values
privately in the console; do not put credentials in GitHub workflow files or shell history.

| Secret ID | Value |
| --- | --- |
| `estate-ai-database-url` | `postgresql+psycopg://USER:URL_ENCODED_PASSWORD@/estate_ai?host=/cloudsql/PROJECT:REGION:INSTANCE` |
| `estate-ai-admin-key` | A long random dashboard API key |
| `estate-ai-ollama-key` | API key for the remote Ollama endpoint |
| `estate-ai-whatsapp-token` | Meta access token |
| `estate-ai-whatsapp-app-secret` | Meta app secret |
| `estate-ai-whatsapp-verify-token` | Your separate random webhook verification secret |

All six secret IDs must exist. While using simulation, unconfigured WhatsApp secrets
can contain `unused-in-simulation`; replace every placeholder before enabling live mode.
For live use, replace the temporary Meta token with an appropriately scoped long-lived
token. Secret values are resolved at container startup; deploy again after rotation.

Grant access only to these secrets:

```bash
for name in database-url admin-key ollama-key whatsapp-token whatsapp-app-secret whatsapp-verify-token; do
  gcloud secrets add-iam-policy-binding "estate-ai-$name" \
    --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor
done
```

The deployed container cannot use Ollama at your PC's `localhost:11434`.
The initial cloud configuration uses native Ollama Cloud (`https://ollama.com`,
`gemma4:31b`), requiring its API key. You can change the model/endpoint variables;
the existing agent expects an Ollama-compatible native `/api/chat` API with tools.
Other vendors require an adapter rather than just changing the URL. Your local
`.env` and `gemma4:31b-cloud` configuration remain unchanged.

## 5. Set GitHub environment variables

Repository → Settings → Environments → create **production** → Environment variables.

| Variable | Value |
| --- | --- |
| `GCP_PROJECT_ID` | Your Google Cloud project ID |
| `GCP_REGION` | `asia-south1` (default) |
| `WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github` |
| `DEPLOY_SERVICE_ACCOUNT` | `estate-ai-deploy@PROJECT_ID.iam.gserviceaccount.com` |
| `RUNTIME_SERVICE_ACCOUNT` | `estate-ai-runtime@PROJECT_ID.iam.gserviceaccount.com` |
| `CLOUD_SQL_CONNECTION_NAME` | `PROJECT_ID:asia-south1:INSTANCE_NAME` |
| `ARTIFACT_REPOSITORY` | `estate-ai` (default) |
| `CLOUD_RUN_SERVICE` | `estate-ai` (default) |
| `OLLAMA_BASE_URL` | `https://ollama.com` (default) |
| `OLLAMA_MODEL` | `gemma4:31b` (default) |
| `WHATSAPP_MODE` | `simulate` initially; `live` when ready |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta's numeric **Phone Number ID**, not the telephone number |
| `WHATSAPP_GRAPH_VERSION` | Supported version shown in your Meta dashboard |

Run the deployment manually after setup, or push a new commit to main. Missing required
variables fail with a clear message before cloud authentication. Successful runs print
the dashboard URL and Meta callback URL in the GitHub Actions job summary.

## 6. Connect Meta

Use `https://YOUR_CLOUD_RUN_URL/webhooks/whatsapp` as the callback and the value of
`estate-ai-whatsapp-verify-token` as Meta's verify token. Verify/save and subscribe
to `messages`. The GET verification endpoint works in simulation mode; POST delivery
and actual replies require `WHATSAPP_MODE=live` and complete credentials. Follow Meta's
publishing requirements shown in your app before expecting real inbound deliveries.

Cloud Run's public access is required for Meta callbacks. Dashboard data and admin
APIs still require the admin key, and webhook POSTs require Meta's valid signature.
Demo inventory is disabled in this deployment, including in simulation.

## Operation and rollback

One Uvicorn process and one maximum instance are configured. PostgreSQL advisory
leadership prevents old/new revisions from running queue recovery/processing together
during a normal rolling deployment. Leadership uses a dedicated database session;
do not route that connection through a transaction-pooling proxy. The standby worker
waits until the old revision exits. A database/network failure during an external
send still has ambiguous outcomes: inspect `delivery_unknown` rather than blindly
retrying. Monitor Cloud Run logs and failed jobs.

The workflow gives the embedded worker continuously allocated CPU and keeps an
instance running so it can finish jobs after the webhook request returns.
This is the initial single-dealer deployment, not a horizontally scaled queue design.

To roll back, revert the source commit and push to main so the known version is
rebuilt and redeployed. Review database compatibility first. Images are tagged by
commit SHA; configure Artifact Registry retention without deleting a needed rollback.

References: [GitHub OIDC setup](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines),
[Cloud SQL connection](https://docs.cloud.google.com/sql/docs/postgres/connect-run),
[Cloud Run background CPU/billing](https://docs.cloud.google.com/run/docs/configuring/billing-settings),
[Google deployment action](https://github.com/google-github-actions/deploy-cloudrun).
