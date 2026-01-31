#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.json"

# Read config
REGION=$(jq -r '.region' "$CONFIG_FILE")
BUCKET_NAME=$(jq -r '.s3.bucketName' "$CONFIG_FILE")
STACK_NAME="notes-assistant"

echo "=== Notes Assistant - Destroy Infrastructure ==="
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
echo ""

read -p "Are you sure you want to delete everything? (y/N): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

# Empty the bucket first (required before CloudFormation can delete it)
echo "Emptying S3 bucket..."
aws s3 rm "s3://$BUCKET_NAME" --recursive --region "$REGION" || true

# Delete all versions if versioning was enabled
echo "Deleting object versions..."
aws s3api delete-objects \
    --bucket "$BUCKET_NAME" \
    --region "$REGION" \
    --delete "$(aws s3api list-object-versions \
        --bucket "$BUCKET_NAME" \
        --region "$REGION" \
        --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
        --output json 2>/dev/null)" 2>/dev/null || true

# Delete delete markers
aws s3api delete-objects \
    --bucket "$BUCKET_NAME" \
    --region "$REGION" \
    --delete "$(aws s3api list-object-versions \
        --bucket "$BUCKET_NAME" \
        --region "$REGION" \
        --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
        --output json 2>/dev/null)" 2>/dev/null || true

# Delete CloudFormation stack
echo "Deleting CloudFormation stack..."
aws cloudformation delete-stack \
    --stack-name "$STACK_NAME" \
    --region "$REGION"

echo "Waiting for stack deletion..."
aws cloudformation wait stack-delete-complete \
    --stack-name "$STACK_NAME" \
    --region "$REGION"

echo ""
echo "=== Infrastructure Destroyed ==="
