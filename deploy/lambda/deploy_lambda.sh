#!/usr/bin/env bash
# Deploy HealthPulse AgentCore Lambda proxy (zip-based, no Docker needed).
#
# Usage:
#   ./deploy_lambda.sh          # full deploy (IAM + zip + Lambda + Function URL)
#   ./deploy_lambda.sh update   # rebuild zip + update Lambda code only
#   ./deploy_lambda.sh url      # print the Function URL
#   ./deploy_lambda.sh destroy  # tear everything down

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-personal-dev}"
AWS_REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT_ID="177697910426"
RUNTIME_ARN="arn:aws:bedrock-agentcore:ap-south-1:177697910426:runtime/healthpulse_ai-ZXGdMz3NyB"

FUNCTION_NAME="healthpulse-agentcore-proxy"
ROLE_NAME="healthpulse-lambda-proxy-role"
API_NAME="healthpulse-agentcore-proxy-api"

export AWS_PROFILE AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/.build"
ZIP_PATH="$SCRIPT_DIR/lambda.zip"

aws_cmd() { aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"; }

# ── IAM ──────────────────────────────────────────────────────────────────────

create_role() {
    echo ">>> IAM role: $ROLE_NAME"

    aws_cmd iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }' 2>/dev/null || echo "    (role exists)"

    aws_cmd iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true

    aws_cmd iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "InvokeAgentCoreRuntime" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Effect\": \"Allow\",
                \"Action\": [\"bedrock-agentcore:InvokeAgentRuntime\"],
                \"Resource\": \"$RUNTIME_ARN\"
            }]
        }"

    echo ">>> IAM role ready."
}

# ── Build zip ─────────────────────────────────────────────────────────────────

build_zip() {
    echo ">>> Building zip package"
    rm -rf "$BUILD_DIR" "$ZIP_PATH"
    mkdir -p "$BUILD_DIR"

    # Install boto3 for arm64/linux (Lambda runtime may have older version without bedrock-agentcore)
    pip install boto3 \
        --target "$BUILD_DIR" \
        --platform manylinux2014_aarch64 \
        --only-binary=:all: \
        --python-version 3.12 \
        --implementation cp \
        --quiet

    cp "$SCRIPT_DIR/handler.py" "$BUILD_DIR/handler.py"

    cd "$BUILD_DIR"
    zip -r "$ZIP_PATH" . -x "*.pyc" -x "*/__pycache__/*" > /dev/null
    cd "$SCRIPT_DIR"

    echo ">>> Zip ready: $(du -sh "$ZIP_PATH" | cut -f1)"
}

# ── Lambda ───────────────────────────────────────────────────────────────────

deploy_function() {
    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    ENV_VARS="Variables={AGENTCORE_RUNTIME_ARN=${RUNTIME_ARN}}"

    if aws_cmd lambda get-function --function-name "$FUNCTION_NAME" &>/dev/null; then
        echo ">>> Updating Lambda function code"
        aws_cmd lambda update-function-code \
            --function-name "$FUNCTION_NAME" \
            --zip-file "fileb://$ZIP_PATH" \
            --architectures arm64

        aws_cmd lambda wait function-updated --function-name "$FUNCTION_NAME"

        aws_cmd lambda update-function-configuration \
            --function-name "$FUNCTION_NAME" \
            --timeout 900 \
            --memory-size 512 \
            --environment "$ENV_VARS"
    else
        echo ">>> Creating Lambda function (waiting for IAM role propagation)"
        sleep 12

        aws_cmd lambda create-function \
            --function-name "$FUNCTION_NAME" \
            --runtime python3.12 \
            --handler handler.handler \
            --zip-file "fileb://$ZIP_PATH" \
            --role "$ROLE_ARN" \
            --architectures arm64 \
            --timeout 900 \
            --memory-size 512 \
            --environment "$ENV_VARS"

        aws_cmd lambda wait function-active --function-name "$FUNCTION_NAME"
    fi

    LAMBDA_ARN="arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"

    echo ">>> API Gateway HTTP API"
    # Find existing API ID or create new one
    EXISTING_API=$(aws_cmd apigatewayv2 get-apis \
        --query "Items[?Name=='${API_NAME}'].ApiId" --output text)

    if [ -n "$EXISTING_API" ] && [ "$EXISTING_API" != "None" ]; then
        API_ID="$EXISTING_API"
        echo "    (API exists: $API_ID)"
    else
        API_ID=$(aws_cmd apigatewayv2 create-api \
            --name "$API_NAME" \
            --protocol-type HTTP \
            --cors-configuration 'AllowOrigins=*,AllowMethods=POST,AllowHeaders=content-type,x-session-id' \
            --query ApiId --output text)
        echo "    Created API: $API_ID"

        INTEGRATION_ID=$(aws_cmd apigatewayv2 create-integration \
            --api-id "$API_ID" \
            --integration-type AWS_PROXY \
            --integration-uri "$LAMBDA_ARN" \
            --payload-format-version "2.0" \
            --query IntegrationId --output text)

        aws_cmd apigatewayv2 create-route \
            --api-id "$API_ID" \
            --route-key '$default' \
            --target "integrations/${INTEGRATION_ID}" > /dev/null

        aws_cmd apigatewayv2 create-stage \
            --api-id "$API_ID" \
            --stage-name '$default' \
            --auto-deploy > /dev/null
    fi

    aws_cmd lambda add-permission \
        --function-name "$FUNCTION_NAME" \
        --statement-id AllowAPIGateway \
        --action lambda:InvokeFunction \
        --principal apigateway.amazonaws.com \
        --source-arn "arn:aws:execute-api:${AWS_REGION}:${ACCOUNT_ID}:${API_ID}/*" 2>/dev/null || true

    URL="https://${API_ID}.execute-api.${AWS_REGION}.amazonaws.com"
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "  POST ${URL}/stream"
    echo "  GET  ${URL}/health"
    echo "╚══════════════════════════════════════════════════════════════╝"
}

# ── Commands ─────────────────────────────────────────────────────────────────

cmd="${1:-deploy}"

case "$cmd" in
    deploy)
        create_role
        build_zip
        deploy_function
        ;;

    update)
        build_zip
        echo ">>> Updating Lambda code"
        aws_cmd lambda update-function-code \
            --function-name "$FUNCTION_NAME" \
            --zip-file "fileb://$ZIP_PATH" \
            --architectures arm64
        aws_cmd lambda wait function-updated --function-name "$FUNCTION_NAME"
        echo ">>> Updated."
        ;;

    url)
        API_ID=$(aws_cmd apigatewayv2 get-apis \
            --query "Items[?Name=='${API_NAME}'].ApiId" --output text)
        echo "https://${API_ID}.execute-api.${AWS_REGION}.amazonaws.com"
        ;;

    destroy)
        read -p "Delete Lambda, API Gateway, and IAM role for '$FUNCTION_NAME'? [y/N] " ans
        [ "$ans" = "y" ] || exit 0
        API_ID=$(aws_cmd apigatewayv2 get-apis \
            --query "Items[?Name=='${API_NAME}'].ApiId" --output text 2>/dev/null)
        [ -n "$API_ID" ] && [ "$API_ID" != "None" ] && \
            aws_cmd apigatewayv2 delete-api --api-id "$API_ID" 2>/dev/null || true
        aws_cmd lambda delete-function --function-name "$FUNCTION_NAME" 2>/dev/null || true
        aws_cmd iam detach-role-policy --role-name "$ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true
        aws_cmd iam delete-role-policy --role-name "$ROLE_NAME" \
            --policy-name InvokeAgentCoreRuntime 2>/dev/null || true
        aws_cmd iam delete-role --role-name "$ROLE_NAME" 2>/dev/null || true
        rm -f "$ZIP_PATH"
        echo ">>> Destroyed."
        ;;

    *)
        echo "Usage: $0 [deploy|update|url|destroy]"
        exit 1
        ;;
esac
