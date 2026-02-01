#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.json"

# Read config
REGION=$(jq -r '.region' "$CONFIG_FILE")
BUCKET_NAME=$(jq -r '.s3.bucketName' "$CONFIG_FILE")
NOTES_DIR=$(jq -r '.notesDirectory' "$CONFIG_FILE")
AGENT_MODEL=$(jq -r '.models.agent' "$CONFIG_FILE")
EMBEDDING_MODEL=$(jq -r '.models.embedding' "$CONFIG_FILE")
STACK_NAME="notes-assistant"

echo "=== Notes Assistant - Complete Deployment ==="
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
echo "Notes directory: $NOTES_DIR"
echo "Agent model: $AGENT_MODEL"
echo "Embedding model: $EMBEDDING_MODEL"
echo ""

# Validate notes directory exists
if [ ! -d "$NOTES_DIR" ]; then
    echo "Error: Notes directory not found: $NOTES_DIR"
    exit 1
fi

# Check if notes directory has content
if [ -z "$(find "$NOTES_DIR" -name "*.md" -o -name "*.txt" | head -1)" ]; then
    echo "Warning: No .md or .txt files found in $NOTES_DIR"
    read -p "Continue anyway? (y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        exit 0
    fi
fi

# Build with SAM (packages Lambda code)
echo "Building SAM application..."
sam build \
    --template-file "$SCRIPT_DIR/cloudformation/template.yaml" \
    --build-dir "$SCRIPT_DIR/.aws-sam/build"

# Deploy with SAM
echo "Deploying complete Notes Assistant infrastructure..."
sam deploy \
    --template-file "$SCRIPT_DIR/.aws-sam/build/template.yaml" \
    --stack-name "$STACK_NAME" \
    --parameter-overrides \
        BucketName="$BUCKET_NAME" \
        AgentModelId="$AGENT_MODEL" \
        EmbeddingModelId="$EMBEDDING_MODEL" \
    --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
    --region "$REGION" \
    --resolve-s3 \
    --no-fail-on-empty-changeset

echo "Infrastructure deployed successfully."
echo ""

# Sync text files to S3
echo "Syncing text files to S3..."
aws s3 sync "$NOTES_DIR" "s3://$BUCKET_NAME/notes/" \
    --region "$REGION" \
    --delete \
    --exclude "*" \
    --include "*.md" \
    --include "*.txt" \
    --include "*.html"

echo "Files uploaded."

# Get Knowledge Base and Data Source IDs
KB_ID=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseId`].OutputValue' --output text)
DS_ID=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`DataSourceId`].OutputValue' --output text)

# Trigger ingestion after files are uploaded
echo ""
echo "Starting ingestion job..."
aws bedrock-agent start-ingestion-job \
    --knowledge-base-id "$KB_ID" \
    --data-source-id "$DS_ID" \
    --region "$REGION" \
    --output text \
    --query 'ingestionJob.ingestionJobId'

echo ""
echo "=== Deployment Complete ==="
echo "S3 bucket: $BUCKET_NAME"
echo "Knowledge Base: $KB_ID"
echo "Ingestion started"
echo ""
echo "Check ingestion status:"
echo "aws bedrock-agent list-ingestion-jobs --knowledge-base-id $KB_ID --data-source-id $DS_ID --region $REGION --max-results 1"
