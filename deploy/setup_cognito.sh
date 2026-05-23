#!/usr/bin/env bash
# One-shot: provision Cognito Identity Pool + IAM role for iOS direct AgentCore access.
# Run once: AWS_PROFILE=personal-dev bash deploy/setup_cognito.sh
# Idempotent — re-running prints existing IDs.

set -euo pipefail

PROFILE="${AWS_PROFILE:-personal-dev}"
REGION="ap-south-1"
ACCOUNT_ID="177697910426"
RUNTIME_ARN="arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:runtime/healthpulse_ai-ZXGdMz3NyB"

POOL_NAME="HealthPulseGuestPool"
ROLE_NAME="HealthPulseCognitoUnauth"
POLICY_NAME="HealthPulseAgentCoreInvoke"

aws() { command aws --profile "$PROFILE" --region "$REGION" "$@"; }

echo "▶ Looking up existing Identity Pool ($POOL_NAME)..."
POOL_ID="$(aws cognito-identity list-identity-pools --max-results 60 \
    --query "IdentityPools[?IdentityPoolName=='${POOL_NAME}'].IdentityPoolId | [0]" \
    --output text 2>/dev/null || echo "None")"

if [[ "$POOL_ID" == "None" || -z "$POOL_ID" ]]; then
    echo "  creating new pool..."
    POOL_ID="$(aws cognito-identity create-identity-pool \
        --identity-pool-name "$POOL_NAME" \
        --allow-unauthenticated-identities \
        --query 'IdentityPoolId' --output text)"
    echo "  ✓ created: $POOL_ID"
else
    echo "  ✓ exists: $POOL_ID"
fi

echo "▶ Building IAM trust policy..."
TRUST_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "cognito-identity.amazonaws.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {"cognito-identity.amazonaws.com:aud": "${POOL_ID}"},
      "ForAnyValue:StringLike": {"cognito-identity.amazonaws.com:amr": "unauthenticated"}
    }
  }]
}
EOF
)

echo "▶ Ensuring IAM role ($ROLE_NAME)..."
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    aws iam update-assume-role-policy --role-name "$ROLE_NAME" --policy-document "$TRUST_DOC"
    echo "  ✓ trust policy refreshed"
else
    aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "$TRUST_DOC" >/dev/null
    echo "  ✓ role created"
fi
ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)"

echo "▶ Attaching inline policy ($POLICY_NAME)..."
POLICY_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "bedrock-agentcore:InvokeAgentRuntime",
    "Resource": [
      "${RUNTIME_ARN}",
      "${RUNTIME_ARN}/*"
    ]
  }]
}
EOF
)
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "$POLICY_NAME" --policy-document "$POLICY_DOC"
echo "  ✓ inline policy applied"

echo "▶ Binding role to Identity Pool..."
aws cognito-identity set-identity-pool-roles \
    --identity-pool-id "$POOL_ID" \
    --roles "unauthenticated=${ROLE_ARN}"
echo "  ✓ role bound"

cat <<EOF

═══════════════════════════════════════════════════════════════
 ✓ Setup complete. Add these to iOS AgentCoreConfig.swift:
═══════════════════════════════════════════════════════════════

  identityPoolId  =  "${POOL_ID}"
  region          =  "${REGION}"
  runtimeArn      =  "${RUNTIME_ARN}"

═══════════════════════════════════════════════════════════════
EOF
