#!/usr/bin/env bash
# Deploy HealthPulse AI to AWS Bedrock AgentCore Runtime (ap-south-1).
#
# Prerequisites:
#   - Docker / colima running with buildx (ARM64 build).
#   - AWS CLI configured with profile `personal-dev`.
#   - Python with the `my_health` uv env (provides agentcore CLI).
#
# Usage:
#   ./deploy.sh            # build + push + update runtime
#   ./deploy.sh configure  # one-time: regenerate .bedrock_agentcore.yaml
#   ./deploy.sh iam        # (re)attach inline IAM policies the runtime needs
#   ./deploy.sh invoke '{"user_id":"u1","chatHistory":[],"currentMessage":{"role":"user","content":"hi"}}'

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export AWS_PROFILE="${AWS_PROFILE:-personal-dev}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"

AGENT_NAME="${AGENT_NAME:-healthpulse_ai}"
ENTRYPOINT="app/main.py"

# Ensure agentcore CLI exists as an isolated uv tool (avoids project dep clash)
if ! command -v agentcore >/dev/null 2>&1; then
  echo ">>> Installing bedrock-agentcore-starter-toolkit as uv tool"
  uv tool install bedrock-agentcore-starter-toolkit
fi

# Verify AWS credentials via boto3 (avoids slow/broken aws CLI installs)
uv run --frozen python -c "
import boto3, sys
s = boto3.Session(profile_name='$AWS_PROFILE', region_name='$AWS_REGION')
ident = s.client('sts').get_caller_identity()
print(f'>>> AWS account={ident[\"Account\"]} arn={ident[\"Arn\"]}')
" || { echo "AWS credentials check failed for profile=$AWS_PROFILE region=$AWS_REGION"; exit 1; }

run_agentcore() { agentcore "$@"; }

# Idempotently attach inline IAM policies the runtime needs at invoke time.
# Reads bucket from config/config.yaml and role from .bedrock_agentcore.yaml so
# we never hardcode names that drift from the rest of the codebase.
ensure_runtime_iam() {
  if [ ! -f ".bedrock_agentcore.yaml" ]; then
    echo ">>> Skipping IAM step — .bedrock_agentcore.yaml not present yet"
    return 0
  fi
  echo ">>> Ensuring runtime IAM policies (chat-media S3)"
  uv run --frozen python -c "
import json, sys, yaml, boto3
cfg = yaml.safe_load(open('config/config.yaml'))
bucket = cfg['storage']['chat_media_bucket']
ac = yaml.safe_load(open('.bedrock_agentcore.yaml'))
agent = ac['agents'][ac['default_agent']]
role_arn = agent['aws']['execution_role']
role_name = role_arn.split('/')[-1]
policy = {
  'Version': '2012-10-17',
  'Statement': [
    {'Effect': 'Allow',
     'Action': ['s3:PutObject', 's3:GetObject', 's3:DeleteObject'],
     'Resource': f'arn:aws:s3:::{bucket}/*'},
    {'Effect': 'Allow',
     'Action': ['s3:ListBucket'],
     'Resource': f'arn:aws:s3:::{bucket}'},
  ],
}
iam = boto3.Session(profile_name='$AWS_PROFILE', region_name='$AWS_REGION').client('iam')
iam.put_role_policy(RoleName=role_name, PolicyName='MyHealthChatMediaAccess',
                    PolicyDocument=json.dumps(policy))
print(f'>>> Attached MyHealthChatMediaAccess to {role_name} (bucket={bucket})')
" || { echo "IAM step failed"; exit 1; }
}

cmd="${1:-launch}"

case "$cmd" in
  configure)
    echo ">>> agentcore configure (region=$AWS_REGION, agent=$AGENT_NAME)"
    run_agentcore configure \
      --entrypoint "$ENTRYPOINT" \
      --name "$AGENT_NAME" \
      --container-runtime docker \
      --region "$AWS_REGION" \
      --requirements-file pyproject.toml \
      --non-interactive
    echo ">>> Restoring custom Dockerfile (configure clobbers it)"
    cp deploy/Dockerfile.template Dockerfile
    ;;

  launch)
    if [ ! -f ".bedrock_agentcore.yaml" ]; then
      echo ">>> First run — running configure"
      "$0" configure
    fi
    echo ">>> Restoring custom Dockerfile before launch"
    cp deploy/Dockerfile.template Dockerfile

    # Pass runtime env vars from local .env, but SKIP AWS_PROFILE
    # (containers use the AgentCore IAM execution role, not profiles).
    env_args=()
    if [ -f ".env" ]; then
      while IFS= read -r line; do
        case "$line" in ''|\#*|AWS_PROFILE=*) continue ;; esac
        kv="$(echo "$line" | sed -E 's/^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*"?([^"]*)"?[[:space:]]*$/\1=\2/')"
        env_args+=(--env "$kv")
      done < .env
      echo ">>> Injecting ${#env_args[@]} env var(s) into runtime"
    fi

    echo ">>> agentcore launch --local-build (build ARM64 locally, push ECR, register runtime)"
    run_agentcore launch --local-build "${env_args[@]}"

    ensure_runtime_iam

    echo
    echo ">>> Deployed. Runtime details:"
    run_agentcore status
    ;;

  iam)
    ensure_runtime_iam
    ;;

  status)
    run_agentcore status
    ;;

  invoke)
    payload="${2:-}"
    if [ -z "$payload" ]; then
      echo "Usage: $0 invoke '<json-payload>'"
      exit 1
    fi
    run_agentcore invoke "$payload"
    ;;

  destroy)
    read -p "Destroy AgentCore runtime '$AGENT_NAME' in $AWS_REGION? [y/N] " ans
    [ "$ans" = "y" ] || exit 0
    run_agentcore destroy
    ;;

  *)
    echo "Unknown command: $cmd"
    echo "Usage: $0 [configure|launch|iam|status|invoke <json>|destroy]"
    exit 1
    ;;
esac
