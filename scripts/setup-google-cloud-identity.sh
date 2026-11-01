#!/usr/bin/env bash
# Run in Google Cloud Shell after reviewing the IAM grants below.
# Creates deployment identities/registry only; no database, passwords or secret values.
set -euo pipefail

PROJECT_ID=gen-lang-client-0081910278
PROJECT_NUMBER=879940632641
REGION=asia-south1
REPOSITORY=briraj-perry/RealState-agentic_AI
REPOSITORY_ID=1441703959
OWNER_ID=304775270
DEPLOY_SA="estate-ai-deploy@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_SA="estate-ai-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"
actual_number="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
test "$actual_number" = "$PROJECT_NUMBER"

gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  sqladmin.googleapis.com secretmanager.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com --quiet

for name in estate-ai-deploy estate-ai-runtime; do
  if ! gcloud iam service-accounts describe "$name@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$name" --display-name="$name"
  fi
done
if ! gcloud artifacts repositories describe estate-ai --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create estate-ai --location="$REGION" --repository-format=docker
fi

# Project-wide Cloud Run admin permits creating the service and setting its public
# webhook invoker policy. Artifact writes are restricted to this repository.
gcloud projects add-iam-policy-binding "$PROJECT_ID" --quiet --condition=None \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/run.admin
gcloud artifacts repositories add-iam-policy-binding estate-ai --location="$REGION" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/artifactregistry.writer --quiet
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/iam.serviceAccountUser --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --quiet --condition=None \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/cloudsql.client

if ! gcloud iam workload-identity-pools describe estate-ai-github --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create estate-ai-github --location=global --display-name='Estate AI GitHub'
fi
condition="assertion.repository_id == '$REPOSITORY_ID' && assertion.repository_owner_id == '$OWNER_ID' && assertion.ref == 'refs/heads/main' && assertion.sub == 'repo:$REPOSITORY:environment:production'"
if ! gcloud iam workload-identity-pools providers describe github \
  --workload-identity-pool=estate-ai-github --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc github --location=global \
    --workload-identity-pool=estate-ai-github \
    --issuer-uri=https://token.actions.githubusercontent.com \
    --attribute-mapping='google.subject=assertion.sub,attribute.repository_id=assertion.repository_id' \
    --attribute-condition="$condition"
else
  # Fail rather than silently reconfigure trust for an existing provider.
  current_condition="$(gcloud iam workload-identity-pools providers describe github \
    --workload-identity-pool=estate-ai-github --location=global --format='value(attributeCondition)')"
  test "$current_condition" = "$condition"
fi
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/estate-ai-github/attribute.repository_id/$REPOSITORY_ID" \
  --role=roles/iam.workloadIdentityUser --quiet

printf '\nGitHub production variables:\n'
printf 'DEPLOY_SERVICE_ACCOUNT=%s\nRUNTIME_SERVICE_ACCOUNT=%s\n' "$DEPLOY_SA" "$RUNTIME_SA"
printf 'WIF_PROVIDER=projects/%s/locations/global/workloadIdentityPools/estate-ai-github/providers/github\n' "$PROJECT_NUMBER"
printf '\nNext: create Cloud SQL and configure only the app-specific Secret Manager values.\n'
