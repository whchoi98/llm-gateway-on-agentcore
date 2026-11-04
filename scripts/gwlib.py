"""Shared helpers for the LLM Gateway scripts: stack outputs, team tokens."""

import json
import os
import pathlib
import time
import urllib.parse
import urllib.request

import boto3

REGION = "ap-northeast-2"
ROOT = pathlib.Path(__file__).resolve().parent.parent
_token_cache: dict = {}


def outputs() -> dict:
    """CloudFormation outputs of LlmGatewayStack (cdk-outputs.json, else the live stack)."""
    path = ROOT / "cdk-outputs.json"
    if path.exists():
        data = json.loads(path.read_text())
        if "LlmGatewayStack" in data:
            return data["LlmGatewayStack"]
    cfn = boto3.client("cloudformation", region_name=REGION)
    stack = cfn.describe_stacks(StackName="LlmGatewayStack")["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}


def team_credentials(team: str) -> dict:
    sm = boto3.client("secretsmanager", region_name=REGION)
    return json.loads(sm.get_secret_value(SecretId=f"llm-gateway/clients/{team}")["SecretString"])


def token(team: str) -> str:
    """OAuth2 client-credentials access token for a team (cached until near expiry)."""
    cached = _token_cache.get(team)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    creds = team_credentials(team)
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "scope": creds["scope"],
    }).encode()
    req = urllib.request.Request(creds["token_url"], data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
    _token_cache[team] = (body["access_token"], time.time() + int(body.get("expires_in", 3600)))
    return body["access_token"]


def endpoint() -> str:
    return os.environ.get("LLM_GATEWAY_ENDPOINT") or outputs()["InferenceEndpoint"]
