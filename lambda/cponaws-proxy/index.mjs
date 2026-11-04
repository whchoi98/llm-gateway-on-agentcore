/**
 * Streaming proxy: AgentCore Gateway → Claude Platform on AWS (1P fallback).
 *
 * Why it exists: Claude Platform on AWS requires an `anthropic-workspace-id`
 * header on every request, and a gateway inference target cannot add static
 * headers (one credential provider per target, and the model discovery call
 * made when the target is created bypasses interceptors).
 *
 * - Invoked through a Lambda Function URL (AWS_IAM, RESPONSE_STREAM); the
 *   gateway signs with its execution role, so no 1P credential lives in the
 *   gateway.
 * - Adds the API key (from Secrets Manager) and the workspace header, then
 *   streams the upstream response (SSE included) back byte for byte.
 * - Only the Messages and Models APIs are reachable through it.
 */
import { GetSecretValueCommand, SecretsManagerClient } from '@aws-sdk/client-secrets-manager';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

const UPSTREAM = process.env.UPSTREAM_URL; // https://aws-external-anthropic.<region>.api.aws
const WORKSPACE_ID = process.env.WORKSPACE_ID;
const SECRET_ID = process.env.SECRET_ID;
const KEY_TTL_MS = 5 * 60 * 1000;

const ALLOWED_PATHS = [/^\/v1\/messages$/, /^\/v1\/messages\/count_tokens$/, /^\/v1\/models(\/[A-Za-z0-9._-]+)?$/];
const FORWARD_REQUEST_HEADERS = new Set(['content-type', 'accept', 'anthropic-version', 'anthropic-beta']);
const forwardResponseHeader = (name) =>
  name === 'content-type' || name === 'request-id' || name === 'retry-after' || name.startsWith('anthropic-');

const secrets = new SecretsManagerClient({});
let cachedKey;

async function apiKey() {
  if (cachedKey && Date.now() - cachedKey.at < KEY_TTL_MS) return cachedKey.value;
  const out = await secrets.send(new GetSecretValueCommand({ SecretId: SECRET_ID }));
  cachedKey = { value: JSON.parse(out.SecretString).api_key, at: Date.now() };
  return cachedKey.value;
}

function writeError(responseStream, statusCode, type, message) {
  const stream = awslambda.HttpResponseStream.from(responseStream, {
    statusCode,
    headers: { 'content-type': 'application/json' },
  });
  stream.end(JSON.stringify({ type: 'error', error: { type, message } }));
}

export const handler = awslambda.streamifyResponse(async (event, responseStream) => {
  const method = event.requestContext?.http?.method ?? 'GET';
  const path = event.rawPath ?? '/';
  if (!ALLOWED_PATHS.some((re) => re.test(path))) {
    writeError(responseStream, 404, 'not_found_error', `Path ${path} is not exposed by the LLM Gateway 1P proxy`);
    return;
  }

  const headers = {};
  for (const [name, value] of Object.entries(event.headers ?? {})) {
    if (FORWARD_REQUEST_HEADERS.has(name.toLowerCase())) headers[name.toLowerCase()] = value;
  }
  headers['anthropic-version'] ??= '2023-06-01';
  headers['anthropic-workspace-id'] = WORKSPACE_ID;

  let upstream;
  try {
    headers['x-api-key'] = await apiKey();
    const body = event.body ? Buffer.from(event.body, event.isBase64Encoded ? 'base64' : 'utf8') : undefined;
    const query = event.rawQueryString ? `?${event.rawQueryString}` : '';
    upstream = await fetch(`${UPSTREAM}${path}${query}`, {
      method,
      headers,
      body: method === 'GET' || method === 'HEAD' ? undefined : body,
      signal: AbortSignal.timeout(890_000),
    });
  } catch (err) {
    // 502 so the gateway treats it as a provider failure (5XX).
    console.error(JSON.stringify({ msg: 'upstream request failed', path, error: String(err) }));
    writeError(responseStream, 502, 'api_error', 'Claude Platform on AWS is unreachable');
    return;
  }

  const responseHeaders = {};
  upstream.headers.forEach((value, name) => {
    if (forwardResponseHeader(name)) responseHeaders[name] = value;
  });
  console.log(JSON.stringify({ msg: 'proxied', method, path, status: upstream.status, requestId: upstream.headers.get('request-id') }));

  const stream = awslambda.HttpResponseStream.from(responseStream, { statusCode: upstream.status, headers: responseHeaders });
  if (!upstream.body) {
    stream.end();
    return;
  }
  await pipeline(Readable.fromWeb(upstream.body), stream);
});
