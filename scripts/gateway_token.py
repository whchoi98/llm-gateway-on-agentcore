# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.40"]
# ///
"""Print a gateway access token for a team, for example to start Claude Code:

    ANTHROPIC_AUTH_TOKEN="$(uv run --quiet scripts/gateway_token.py team-standard)" claude

Reads the team's client credentials from Secrets Manager (`llm-gateway/clients/<team>`)
with the caller's AWS credentials and prints a Cognito access token, valid for one hour.
Do not use it as Claude Code's `apiKeyHelper`: that value is sent in both `x-api-key` and
`Authorization`, and the gateway rejects a request that carries both.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gwlib  # noqa: E402

if len(sys.argv) != 2:
    sys.exit("usage: gateway_token.py <team>")
print(gwlib.token(sys.argv[1]))
