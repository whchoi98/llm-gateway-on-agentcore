/**
 * LLM Gateway configuration — the single source of truth.
 *
 * Every routing rule, fallback chain, rate-limit entry, IAM resource and
 * interceptor alias is derived from the values below, so adding or changing a
 * model is a one-line edit here.
 */

export const REGION = 'ap-northeast-2';
export const GATEWAY_NAME = 'llm-gateway';

/**
 * Gateway target names. They also appear in Cedar action names
 * (`<target>___POST:/v1/messages`) and in qualified model IDs (`bedrock/...`).
 */
export const TARGET_BEDROCK = 'bedrock'; // 3P primary: Amazon Bedrock Runtime (Global CRIS), Seoul
export const TARGET_ANTHROPIC = 'cponaws'; // Claude fallback: Claude Platform on AWS (1P) via proxy
export const TARGET_MANTLE = 'mantle'; // GPT fallback: Bedrock Mantle in us-east-1 (in-Region model IDs)

/**
 * 1P: Claude Platform on AWS (Anthropic's native API, billed through AWS).
 * - The API key secret (JSON `{"api_key": "..."}`) is a deploy-time
 *   prerequisite created by scripts/set-cponaws-key.sh, not owned by the stack:
 *   the gateway target calls GET /v1/models when it is created and fails on a
 *   bad credential.
 * - The workspace ID is region-bound and every request needs it in the
 *   `anthropic-workspace-id` header (added by the proxy Lambda). It is kept out
 *   of the repository: scripts/set-cponaws-key.sh stores it in an SSM parameter,
 *   which CloudFormation resolves at deploy time.
 */
export const ONE_P = {
  endpoint: `https://aws-external-anthropic.${REGION}.api.aws`,
  workspaceParameter: '/llm-gateway/anthropic-workspace-id',
  secretName: 'llm-gateway/anthropic-api-key',
};

/**
 * GPT fallback: Bedrock Mantle serves the GPT 6.x models with in-Region IDs only
 * in us-east-1, under the `/openai/v1` prefix. It is a separate endpoint with
 * its own quotas, so it is independent capacity from Seoul's Global CRIS.
 * (From a Seoul source Region the `us.` geo profiles are not callable.)
 */
export const MANTLE = {
  region: 'us-east-1',
  endpoint: 'https://bedrock-mantle.us-east-1.api.aws',
  pathPrefix: '/openai',
};

export type ModelFamily = 'claude' | 'gpt';

export interface ModelRoute {
  /** Short key used for construct IDs and metric dimensions. */
  readonly key: string;
  readonly family: ModelFamily;
  /** Canonical model name clients send. */
  readonly canonical: string;
  /** Vendor-prefixed ID (`anthropic.…` / `openai.…`), also accepted from clients. */
  readonly vendorModel: string;
  /** Primary destination on the `bedrock` target: Global cross-Region inference profile ID. */
  readonly bedrockModel: string;
  /** Fallback destination (target + model ID on that target). */
  readonly fallback: { readonly target: string; readonly model: string };
  /**
   * First-byte timeout for the primary. Non-streaming requests send their first
   * byte only after generation finishes, so this must cover the slowest
   * expected non-streaming completion — otherwise healthy requests fall back.
   */
  readonly primaryFirstByteTimeoutMs: number;
  /** Rule priority (lower = evaluated first). */
  readonly priority: number;
  /** Requires the `premium` OAuth scope (enforced by Cedar policy). */
  readonly premiumOnly: boolean;
  /**
   * Gateway-wide TPM ceiling per served model, applied to the primary and the
   * fallback model ID. Keep it at or below 80% of the account's Global
   * cross-Region TPM quota for the primary, so the gateway throttles before
   * Bedrock returns 429 (which would trigger a fallback instead). Quotas are
   * per account and adjustable: `uv run scripts/smoke_test.py --only quota-headroom`
   * compares the deployed values with the live quotas.
   */
  readonly tpm: number;
  /**
   * Extra model names that share this route (and its fallback chain).
   * They go into the rule's matchModels: rules match the model as the client
   * sent it, BEFORE the REQUEST interceptor runs, so an interceptor rewrite
   * would bypass the rule.
   */
  readonly aliases: string[];
}

type RouteOptions = Pick<ModelRoute, 'key' | 'primaryFirstByteTimeoutMs' | 'priority' | 'tpm'> &
  Partial<Pick<ModelRoute, 'premiumOnly' | 'aliases'>>;

/** Claude: Bedrock Global CRIS → Claude Platform on AWS (same model ID as canonical). */
const claude = (canonical: string, o: RouteOptions): ModelRoute => ({
  family: 'claude',
  canonical,
  vendorModel: `anthropic.${canonical}`,
  bedrockModel: `global.anthropic.${canonical}`,
  fallback: { target: TARGET_ANTHROPIC, model: canonical },
  premiumOnly: false,
  aliases: [],
  ...o,
});

/** GPT: Bedrock Global CRIS (Seoul) → Bedrock Mantle us-east-1 (in-Region ID). */
const gpt = (canonical: string, o: RouteOptions): ModelRoute => ({
  family: 'gpt',
  canonical,
  vendorModel: `openai.${canonical}`,
  bedrockModel: `global.openai.${canonical}`,
  fallback: { target: TARGET_MANTLE, model: `openai.${canonical}` },
  premiumOnly: false,
  aliases: [],
  ...o,
});

export const MODELS: ModelRoute[] = [
  // tpm vs. Global cross-Region TPM quota in ap-northeast-2 (2026-11-04): Opus 4M of 30M and
  // Haiku 8M of 10M (cost-capped below 80%); Sonnet 4.8M of 6M; GPT 6.1 Sol and 6 Sol 1.6M of 2M;
  // GPT 6.1 Terra, 6 Astra and 6 Luna 3.2M of 4M.
  claude('claude-opus-5-5', { key: 'opus', primaryFirstByteTimeoutMs: 180_000, priority: 100, tpm: 4_000_000, premiumOnly: true, aliases: ['opus', 'claude-opus'] }),
  claude('claude-sonnet-5-5', { key: 'sonnet', primaryFirstByteTimeoutMs: 120_000, priority: 110, tpm: 4_800_000, aliases: ['sonnet', 'claude-sonnet'] }),
  claude('claude-haiku-5-5', { key: 'haiku', primaryFirstByteTimeoutMs: 60_000, priority: 120, tpm: 8_000_000, aliases: ['haiku', 'claude-haiku'] }),
  // GPT 6.x are reasoning models: long non-streaming completions are normal.
  gpt('gpt-6.1-sol', { key: 'gpt-6-1-sol', primaryFirstByteTimeoutMs: 180_000, priority: 200, tpm: 1_600_000 }),
  gpt('gpt-6.1-terra', { key: 'gpt-6-1-terra', primaryFirstByteTimeoutMs: 180_000, priority: 210, tpm: 3_200_000 }),
  gpt('gpt-6-astra', { key: 'gpt-6-astra', primaryFirstByteTimeoutMs: 180_000, priority: 220, tpm: 3_200_000 }),
  gpt('gpt-6-sol', { key: 'gpt-6-sol', primaryFirstByteTimeoutMs: 180_000, priority: 230, tpm: 1_600_000 }),
  gpt('gpt-6-luna', { key: 'gpt-6-luna', primaryFirstByteTimeoutMs: 120_000, priority: 240, tpm: 3_200_000 }),
];
export const modelByKey = (key: string) => {
  const m = MODELS.find((x) => x.key === key);
  if (!m) throw new Error(`unknown model key ${key}`);
  return m;
};

/**
 * When the primary (3P) leaves for the fallback.
 * - 429 / 5XX / 408: throttling, capacity and transient provider errors.
 * - 403: Bedrock-side access problems (model access revoked, SCP change).
 * - 400 is deliberately NOT included: a malformed request fails on the
 *   fallback too and would only double the cost.
 */
export const FALLBACK_STATUS_CODES = ['429', '5XX', '408', '403'];
export const FALLBACK_ERRORS = ['CONNECTION_ERROR', 'FIRST_BYTE_TIMEOUT', 'UNROUTABLE'];

/** A/B experiment: one virtual model split across two real models (each leg keeps its own fallback). */
export const EXPERIMENT = {
  alias: 'claude-experiment',
  priority: 500,
  legs: [
    { name: 'control-sonnet', modelKey: 'sonnet', weight: 90 },
    { name: 'treatment-opus', modelKey: 'opus', weight: 10 },
  ],
};

/**
 * Failover drills: simulate a stalled primary. The primary is the real model's
 * profile addressed by its ARN (a destination string distinct from the
 * production route, so drills never trip production circuit breakers) with a
 * 50 ms first-byte timeout, so every call fails over with FIRST_BYTE_TIMEOUT.
 *
 * (An unservable model ID is NOT a reliable drill: from Seoul the bare
 * `anthropic.claude-haiku-5-5` returns HTTP 200 with an UnknownOperationException
 * body, and 2xx responses are never fallback-eligible.)
 */
export const FAILOVER_DRILLS = [
  { alias: 'claude-haiku-5-5-failover-drill', priority: 900, modelKey: 'haiku' },
  { alias: 'gpt-6-luna-failover-drill', priority: 910, modelKey: 'gpt-6-luna' },
];
export const DRILL_FIRST_BYTE_TIMEOUT_MS = 50;

/**
 * Dynamic virtual model. The interceptor picks a Bedrock Claude model by prompt
 * size (Opus only for premium callers) and rewrites `model`; the rule matches
 * the original alias, routes the rewritten model to Bedrock (primary without a
 * pinned model) and, if Bedrock fails, degrades to a fixed 1P model.
 */
export const AUTO_ROUTE = {
  alias: 'claude-auto',
  priority: 400,
  degradedModelKey: 'sonnet',
  firstByteTimeoutMs: 180_000,
};

/** Inbound identity: Cognito resource server and scopes. */
export const RESOURCE_SERVER_ID = 'llm-gateway';
export const SCOPE_INVOKE = 'invoke';
export const SCOPE_PREMIUM = 'premium';

export interface TeamConfig {
  /** Cognito app client name (one machine-to-machine client per team). */
  readonly name: string;
  readonly premium: boolean;
  /** Requests per minute. */
  readonly rpm: number;
  /** Tokens (input + output) per minute. */
  readonly tpm: number;
  /** Concurrent connections (per-second connection limit). */
  readonly connections: number;
}

export const TEAMS: TeamConfig[] = [
  { name: 'team-standard', premium: false, rpm: 60, tpm: 200_000, connections: 10 },
  { name: 'team-premium', premium: true, rpm: 300, tpm: 2_000_000, connections: 50 },
];

/** Applied to any authenticated client without a named entry. */
export const DEFAULT_TEAM_LIMITS = { rpm: 10, tpm: 20_000, connections: 2 };

/** TPM ceiling for any served model without a named entry. */
export const DEFAULT_MODEL_TPM = 1_000_000;

/** Output-token cap for non-premium callers (Cedar token limit policy). */
export const MAX_OUTPUT_TOKENS_STANDARD = 16_384;

/** Interceptor behaviour. */
export const GUARDRAIL_FAIL_MODE: 'open' | 'closed' = 'open';
export const GUARDRAIL_MAX_CHARS = 20_000;

/** Returns verbose errors to callers — useful for a PoC, disable for production. */
export const GATEWAY_DEBUG_ERRORS = true;
export const LOG_RETENTION_DAYS = 30;
