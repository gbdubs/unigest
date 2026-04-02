#!/usr/bin/env bash
set -euo pipefail

# Deploy Unigest server to Google Cloud Run
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - A GCP project with Cloud Run and Artifact Registry enabled
#   - A Neon.tech Postgres database
#
# Configuration:
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="unigest"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "Building and pushing image..."
docker build -f Dockerfile.server -t "${IMAGE}" .
docker push "${IMAGE}"

echo "Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 2 \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 100 \
  --set-env-vars "DEV_MODE=false" \
  --set-env-vars "DATABASE_URL=${DATABASE_URL:?Set DATABASE_URL}"

echo "Done. Service URL:"
gcloud run services describe "${SERVICE_NAME}" --region "${REGION}" --format 'value(status.url)'
