#!/usr/bin/env bash
# Creates or updates the Claude Platform on AWS (1P) API key secret and the
# workspace ID parameter. Deploy prerequisites: the gateway's 1P target lists
# models through the proxy when it is created and fails if the key does not
# work, and CloudFormation resolves the workspace parameter at deploy time.
#
# The key is read from $ANTHROPIC_API_KEY or prompted for (input hidden) and is
# never put on a command line, so it stays out of shell history and `ps`.
# The workspace ID comes from $ANTHROPIC_WORKSPACE_ID, else the existing
# parameter, else a prompt. Neither value is kept in the repository.
set -euo pipefail
REGION=ap-northeast-2
SECRET_ID=llm-gateway/anthropic-api-key
WORKSPACE_PARAM=/llm-gateway/anthropic-workspace-id
ENDPOINT="https://aws-external-anthropic.${REGION}.api.aws"

WORKSPACE_ID="${ANTHROPIC_WORKSPACE_ID:-$(aws ssm get-parameter --region "$REGION" --name "$WORKSPACE_PARAM" \
  --query Parameter.Value --output text 2>/dev/null || true)}"
if [[ -z "$WORKSPACE_ID" ]]; then
  read -r -p "Claude Platform on AWS workspace ID (Seoul, wrkspc_...): " WORKSPACE_ID
fi
if [[ ! "$WORKSPACE_ID" =~ ^wrkspc_[A-Za-z0-9]+$ ]]; then
  echo "error: workspace ID must look like wrkspc_..." >&2
  exit 1
fi

key="${ANTHROPIC_API_KEY:-}"
if [[ -z "$key" ]]; then
  read -r -s -p "Claude Platform on AWS API key: " key
  echo
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
chmod 700 "$tmp"
printf '{"api_key":"%s"}' "$key" > "$tmp/secret.json"
printf 'x-api-key: %s\n' "$key" > "$tmp/headers"

# Verify before storing: a bad key would make the gateway target FAILED.
code=$(curl -s -o "$tmp/out" -w '%{http_code}' "$ENDPOINT/v1/models" -H @"$tmp/headers" \
  -H "anthropic-workspace-id: $WORKSPACE_ID" -H 'anthropic-version: 2023-06-01')
if [[ "$code" != 200 ]]; then
  echo "error: GET $ENDPOINT/v1/models returned HTTP $code: $(head -c 300 "$tmp/out")" >&2
  exit 1
fi
echo "key verified against $ENDPOINT"

aws ssm put-parameter --region "$REGION" --name "$WORKSPACE_PARAM" --type String --overwrite \
  --value "$WORKSPACE_ID" >/dev/null
echo "stored the workspace ID in $WORKSPACE_PARAM"

if aws secretsmanager describe-secret --region "$REGION" --secret-id "$SECRET_ID" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value --region "$REGION" --secret-id "$SECRET_ID" \
    --secret-string "file://$tmp/secret.json" >/dev/null
  echo "updated $SECRET_ID"
else
  aws secretsmanager create-secret --region "$REGION" --name "$SECRET_ID" \
    --description "Claude Platform on AWS (1P) API key for the LLM Gateway (JSON key: api_key)" \
    --tags Key=Project,Value=llm-gateway --secret-string "file://$tmp/secret.json" >/dev/null
  echo "created $SECRET_ID"
fi
