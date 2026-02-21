#!/usr/bin/env bash
set -euo pipefail

TABLE_NAME="${1:-${DYNAMODB_TABLE:-mail-syncer-state}}"
AWS_REGION="${AWS_REGION:-us-west-2}"
TTL_ATTRIBUTE="ttl"

echo "Ensuring DynamoDB table exists..."
echo "  table:  ${TABLE_NAME}"
echo "  region: ${AWS_REGION}"

if aws dynamodb describe-table \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}" >/dev/null 2>&1; then
  echo "Table already exists: ${TABLE_NAME}"
else
  echo "Creating table: ${TABLE_NAME}"
  aws dynamodb create-table \
    --table-name "${TABLE_NAME}" \
    --attribute-definitions \
      AttributeName=PK,AttributeType=S \
      AttributeName=SK,AttributeType=S \
    --key-schema \
      AttributeName=PK,KeyType=HASH \
      AttributeName=SK,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region "${AWS_REGION}" >/dev/null

  echo "Waiting for table to become ACTIVE..."
  aws dynamodb wait table-exists \
    --table-name "${TABLE_NAME}" \
    --region "${AWS_REGION}"
fi

echo "Enabling TTL on attribute: ${TTL_ATTRIBUTE}"
aws dynamodb update-time-to-live \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}" \
  --time-to-live-specification \
    "Enabled=true,AttributeName=${TTL_ATTRIBUTE}" >/dev/null || true

echo "Done."
echo "Verify:"
aws dynamodb describe-table \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Table.{TableName:TableName,TableStatus:TableStatus,BillingMode:BillingModeSummary.BillingMode}' \
  --output table
