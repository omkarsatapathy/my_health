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
    echo
    echo ">>> Deployed. Runtime details:"
    run_agentcore status
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
    echo "Usage: $0 [configure|launch|status|invoke <json>|destroy]"
    exit 1
    ;;
esac
