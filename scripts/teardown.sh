#!/usr/bin/env bash
# Remove every Patchwork resource from the AWS account (Phase 9). Destructive: asks before each step.
#   1. empties the project buckets (they are versioned/locked against accidental `terraform destroy`)
#   2. terraform destroy of envs/dev (pipeline, Batch, Aurora, CloudFront, console, alarms, roles)
#   3. prints the bootstrap destroy command (state bucket + budget) to run last, by hand
set -euo pipefail
cd "$(dirname "$0")/../infra/terraform/envs/dev"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "This deletes ALL Patchwork data and infrastructure in account $ACCOUNT (ap-south-1)."
read -r -p "Type the account ID to continue: " ok
[ "$ok" = "$ACCOUNT" ] || { echo "aborted"; exit 1; }
for b in raw artifacts datasets site; do
  aws s3 rm "s3://patchwork-$ACCOUNT-$b" --recursive --quiet || true
done
terraform destroy
echo
echo "Last step (removes the Terraform state bucket and the budget alarm):"
echo "  cd infra/terraform/bootstrap && terraform destroy"
