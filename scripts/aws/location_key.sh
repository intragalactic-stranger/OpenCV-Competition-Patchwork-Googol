#!/usr/bin/env bash
# Amazon Location Service API key for the viewer basemap (Terraform has no resource for keys yet).
# Restricted to map tiles/styles only, and only from the viewer's CloudFront domain (referer check).
set -euo pipefail
REGION=ap-south-1
URL=$(cd "$(dirname "$0")/../../infra/terraform/envs/dev" && terraform output -raw viewer_url)
NAME=patchwork-viewer-maps
if ! aws location describe-key --region $REGION --key-name $NAME >/dev/null 2>&1; then
  aws location create-key --region $REGION --key-name $NAME --no-expiry \
    --description "Patchwork viewer basemap (tiles only, viewer domain only)" \
    --restrictions "{\"AllowActions\":[\"geo-maps:GetTile\",\"geo-maps:GetStaticMap\"],\"AllowResources\":[\"arn:aws:geo-maps:${REGION}::provider/default\"],\"AllowReferers\":[\"${URL}/*\",\"http://localhost:8000/*\"]}" \
    --tags Project=patchwork,Phase=4 >/dev/null
fi
aws location describe-key --region $REGION --key-name $NAME --query Key --output text
