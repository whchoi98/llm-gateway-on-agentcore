import { CfnOutput, CfnResource, Stack, StackProps } from 'aws-cdk-lib';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct, IDependable } from 'constructs';
import {
  AUTO_ROUTE,
  DEFAULT_MODEL_TPM,
  DEFAULT_TEAM_LIMITS,
  DRILL_FIRST_BYTE_TIMEOUT_MS,
  EXPERIMENT,
  FAILOVER_DRILLS,
  FALLBACK_ERRORS,
  FALLBACK_STATUS_CODES,
  GATEWAY_DEBUG_ERRORS,
  GATEWAY_NAME,
  MANTLE,
  MODELS,
  ModelRoute,
  modelByKey,
  TARGET_ANTHROPIC,
  TARGET_BEDROCK,
  TARGET_MANTLE,
} from './config';
import { CpOnAwsProxy } from './constructs/cponaws-proxy';
import { GuardrailInterceptor } from './constructs/guardrail-interceptor';
import { InboundAuth } from './constructs/inbound-auth';
import { Observability } from './constructs/observability';

export interface LlmGatewayStackProps extends StackProps {
  /**
   * ENFORCE (default) or LOG_ONLY — LOG_ONLY records Cedar decisions without denying.
   * OFF detaches the policy engine (benchmark only): no Cedar evaluation, no ~40/s policy throttle.
   */
  readonly policyMode?: 'ENFORCE' | 'LOG_ONLY' | 'OFF';
  readonly alarmEmail?: string;
  /** Deploy the 1P (Claude Platform on AWS) target and fallback chains. Requires the API key secret. Default true. */
  readonly enableAnthropicFallback?: boolean;
  /** false makes the interceptor skip ApplyGuardrail (benchmark only). Default true. */
  readonly guardrailEnabled?: boolean;
}

const METRICS_NAMESPACE = 'LlmGateway';

/**
 * LLM Gateway on AgentCore Gateway.
 *
 *   client (Anthropic / OpenAI / Bedrock SDK, Cognito JWT)
 *     → inbound JWT authorizer → REQUEST interceptor (auto routing, guardrail,
 *       metrics) → rate limits (RPM/TPM/CPS) → Cedar policy
 *     Rules match the model as the client sent it, not the interceptor's rewrite.
 *     (Interceptor before rate limits: measured 2026-11-05. Rate limits before
 *     rules and Cedar: AWS docs.)
 *     → Claude: Bedrock Global CRIS (Seoul) ──fallback──▶ Claude Platform on AWS (1P, via proxy λ)
 *     → GPT:    Bedrock Global CRIS (Seoul) ──fallback──▶ Bedrock Mantle us-east-1
 *     → Kimi:   Bedrock Global CRIS (Seoul), no fallback
 */
export class LlmGatewayStack extends Stack {
  readonly gateway: agentcore.CfnGateway;
  readonly policyEngine: agentcore.CfnPolicyEngine;

  constructor(scope: Construct, id: string, props: LlmGatewayStackProps = {}) {
    super(scope, id, props);
    const partition = this.partition;
    const region = this.region;
    const account = this.account;

    // ------------------------------------------------------------------
    // 1. Inbound identity (Cognito M2M, one client per team)
    // ------------------------------------------------------------------
    const auth = new InboundAuth(this, 'InboundAuth');
    const teamClientMap: Record<string, string> = {};
    for (const tc of auth.teamClients) teamClientMap[tc.client.userPoolClientId] = tc.team.name;

    // ------------------------------------------------------------------
    // 2. 1P path: Claude Platform on AWS behind a streaming proxy
    //
    // CPonAWS needs an `anthropic-workspace-id` header on every request and a
    // gateway target cannot add static headers, so the 1P target points at a
    // Lambda Function URL that adds the header and the API key. The gateway
    // calls it with SigV4 (its own role) — no 1P credential in the gateway.
    // The key secret is a deploy prerequisite (scripts/set-cponaws-key.sh).
    // ------------------------------------------------------------------
    const with1p = props.enableAnthropicFallback ?? true;
    const oneP = with1p ? new CpOnAwsProxy(this, 'CpOnAwsProxy') : undefined;

    // ------------------------------------------------------------------
    // 3. Guardrail + REQUEST interceptor
    // ------------------------------------------------------------------
    const interceptor = new GuardrailInterceptor(this, 'Interceptor', {
      teamClients: teamClientMap,
      premiumScope: auth.premiumScope,
      metricsNamespace: METRICS_NAMESPACE,
      guardrailEnabled: props.guardrailEnabled,
    });

    // ------------------------------------------------------------------
    // 4. Gateway execution role (least privilege)
    // ------------------------------------------------------------------
    const role = new iam.Role(this, 'GatewayRole', {
      description: `Execution role for AgentCore Gateway ${GATEWAY_NAME}`,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', {
        conditions: {
          StringEquals: { 'aws:SourceAccount': account },
          ArnLike: { 'aws:SourceArn': `arn:${partition}:bedrock-agentcore:${region}:${account}:gateway/${GATEWAY_NAME}*` },
        },
      }),
    });
    const gatewayArnPattern = `arn:${partition}:bedrock-agentcore:${region}:${account}:gateway/${GATEWAY_NAME}-??????????`;

    // 3P: only the configured models via Global CRIS. A global profile needs the
    // profile ARN plus the foundation model in every destination Region
    // (region-less ARN for global). The OpenAI Responses API on bedrock-runtime
    // additionally authorizes InvokeModel on the account's default project.
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: 'InvokeModelsOnBedrock',
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: [
          ...MODELS.flatMap((m) => [
            `arn:${partition}:bedrock:${region}:${account}:inference-profile/${m.bedrockModel}`,
            `arn:${partition}:bedrock:*::foundation-model/${m.vendorModel}`,
            `arn:${partition}:bedrock:::foundation-model/${m.vendorModel}`,
          ]),
          `arn:${partition}:bedrock:${region}:${account}:project/default`,
        ],
      }),
    );
    // GPT fallback: Bedrock Mantle in us-east-1 (SigV4 service bedrock-mantle).
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: 'InvokeGptOnMantle',
        actions: ['bedrock-mantle:CreateInference', 'bedrock-mantle:CountTokens'],
        resources: [`arn:${partition}:bedrock-mantle:${MANTLE.region}:${account}:project/*`],
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: 'MantleModelDiscovery',
        actions: ['bedrock-mantle:Get*', 'bedrock-mantle:List*'],
        resources: ['*'],
      }),
    );
    // The bedrock-runtime connector discovers models from the Bedrock catalog;
    // the target does not reach READY without these.
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: 'BedrockModelDiscovery',
        actions: [
          'bedrock:ListFoundationModels',
          'bedrock:ListInferenceProfiles',
          'bedrock:ListProvisionedModelThroughputs',
          'bedrock:ListCustomModelDeployments',
          'bedrock:ListImportedModels',
          'bedrock:ListMarketplaceModelEndpoints',
          'bedrock:ListPromptRouters',
        ],
        resources: ['*'],
      }),
    );
    // 1P: SigV4 to the proxy Function URL (the proxy holds the CPonAWS key).
    oneP?.grantInvoke(role);
    interceptor.function.grantInvoke(role);

    // ------------------------------------------------------------------
    // 5. Policy engine (Cedar). Policies live in LlmGatewayPolicyStack.
    // ------------------------------------------------------------------
    this.policyEngine = new agentcore.CfnPolicyEngine(this, 'PolicyEngine', {
      name: 'llm_gateway_policies',
      description: 'Cedar authorization for the LLM Gateway (team scopes, premium models)',
    });
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: 'PolicyEngineRead',
        actions: ['bedrock-agentcore:GetPolicyEngine'],
        resources: [this.policyEngine.attrPolicyEngineArn],
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: 'PolicyEvaluation',
        actions: ['bedrock-agentcore:AuthorizeAction', 'bedrock-agentcore:PartiallyAuthorizeActions'],
        resources: [this.policyEngine.attrPolicyEngineArn, gatewayArnPattern],
      }),
    );

    // ------------------------------------------------------------------
    // 6. Gateway
    // ------------------------------------------------------------------
    this.gateway = new agentcore.CfnGateway(this, 'Gateway', {
      name: GATEWAY_NAME,
      description: 'LLM Gateway: Bedrock Global CRIS primary; fallback Claude Platform on AWS (Claude) / Mantle us-east-1 (GPT)',
      protocolType: 'MCP',
      roleArn: role.roleArn,
      authorizerType: 'CUSTOM_JWT',
      authorizerConfiguration: {
        customJwtAuthorizer: {
          discoveryUrl: auth.discoveryUrl,
          allowedClients: auth.teamClients.map((tc) => tc.client.userPoolClientId),
          allowedScopes: [auth.invokeScope],
        },
      },
      interceptorConfigurations: [
        {
          interceptor: { lambda: { arn: interceptor.function.functionArn } },
          interceptionPoints: ['REQUEST'],
          // Headers carry the JWT, used only to attribute metrics to a team.
          inputConfiguration: { passRequestHeaders: true },
        },
      ],
      ...(props.policyMode === 'OFF'
        ? {}
        : { policyEngineConfiguration: { arn: this.policyEngine.attrPolicyEngineArn, mode: props.policyMode ?? 'ENFORCE' } }),
      exceptionLevel: GATEWAY_DEBUG_ERRORS ? 'DEBUG' : undefined,
    });
    this.gateway.node.addDependency(role); // role + its default policy must exist first
    const gatewayId = this.gateway.attrGatewayIdentifier;

    // Gateway child resources are created one at a time to avoid concurrent
    // updates on the same gateway.
    let previous: IDependable = this.gateway;
    const chain = <T extends Construct>(resource: T): T => {
      resource.node.addDependency(previous);
      previous = resource;
      return resource;
    };

    // ------------------------------------------------------------------
    // 7. Inference targets
    // ------------------------------------------------------------------
    // 3P — bedrock-runtime connector: serves Global CRIS profiles and translates
    // Anthropic Messages / OpenAI Chat Completions to InvokeModel.
    chain(
      new agentcore.CfnGatewayTarget(this, 'BedrockTarget', {
        gatewayIdentifier: gatewayId,
        name: TARGET_BEDROCK,
        description: '3P: Amazon Bedrock Runtime (Global cross-Region inference)',
        targetConfiguration: { inference: { connector: { source: { connectorId: 'bedrock-runtime' } } } },
        credentialProviderConfigurations: [{ credentialProviderType: 'GATEWAY_IAM_ROLE' }],
      }),
    );

    // 1P — Claude Platform on AWS via the proxy: Claude 5.5 family, Messages API
    // only (Bedrock serves Claude only in the Messages / InvokeModel schema, so
    // the fallback exposes the same surface as the primary).
    const fallbackModels = (target: string) =>
      MODELS.flatMap((m) => (m.fallback?.target === target ? [{ model: m.fallback.model }] : []));
    if (oneP) {
      const target = chain(
        new agentcore.CfnGatewayTarget(this, 'CpOnAwsTarget', {
          gatewayIdentifier: gatewayId,
          name: TARGET_ANTHROPIC,
          description: '1P: Claude Platform on AWS (fallback, via streaming proxy)',
          targetConfiguration: {
            inference: {
              provider: {
                endpoint: oneP.endpoint,
                operations: [{ path: '/v1/messages', models: fallbackModels(TARGET_ANTHROPIC) }],
              },
            },
          },
          credentialProviderConfigurations: [
            {
              credentialProviderType: 'GATEWAY_IAM_ROLE',
              credentialProvider: { iamCredentialProvider: { service: 'lambda', region } },
            },
          ],
        }),
      );
      // The target's discovery call goes through the proxy, so its IAM must be in place first.
      target.node.addDependency(role);
      target.node.addDependency(oneP);
    }

    // GPT fallback — Bedrock Mantle us-east-1. The gateway serves OpenAI paths
    // under /v1; Mantle serves these GPT models under /openai/v1.
    const mantleModels = fallbackModels(TARGET_MANTLE);
    chain(
      new agentcore.CfnGatewayTarget(this, 'MantleTarget', {
        gatewayIdentifier: gatewayId,
        name: TARGET_MANTLE,
        description: `GPT fallback: Bedrock Mantle ${MANTLE.region} (in-Region model IDs)`,
        targetConfiguration: {
          inference: {
            provider: {
              endpoint: MANTLE.endpoint,
              operations: ['/v1/chat/completions', '/v1/responses'].map((path) => ({
                path,
                providerPath: `${MANTLE.pathPrefix}${path}`,
                models: mantleModels,
              })),
            },
          },
        },
        credentialProviderConfigurations: [
          {
            credentialProviderType: 'GATEWAY_IAM_ROLE',
            credentialProvider: { iamCredentialProvider: { service: 'bedrock-mantle', region: MANTLE.region } },
          },
        ],
      }),
    ).node.addDependency(role);

    // ------------------------------------------------------------------
    // 8. Routing rules: model → 3P primary with ordered 1P fallback
    //
    // aws-cdk-lib 2.275's CfnGatewayRule predates MatchModels / Model /
    // Fallback and would silently drop them, so rules are emitted as raw
    // AWS::BedrockAgentCore::GatewayRule resources (CloudFormation schema casing).
    // ------------------------------------------------------------------
    const rule = (id: string, priority: number, description: string, models: string[], routeToTarget: object) => {
      const resource = new CfnResource(this, id, {
        type: 'AWS::BedrockAgentCore::GatewayRule',
        properties: {
          GatewayIdentifier: gatewayId,
          Priority: priority,
          Description: description,
          Conditions: [{ MatchModels: { AnyOf: models.map((Value) => ({ Value, Operator: 'StringEquals' })) } }],
          Actions: [{ RouteToTarget: routeToTarget }],
        },
      });
      // Synth prints F3018 warnings for these rules: the CDK-bundled cfn-lint
      // spec predates model routing, while the live ap-northeast-2 registry
      // schema (DescribeType) accepts MatchModels / Model / Fallback.
      return chain(resource);
    };
    // A fallback is only rendered when its target exists in this deployment.
    const targetEnabled = (target: string) => target !== TARGET_ANTHROPIC || with1p;
    // The auto route and the drills exist to reach a fallback, so their models must have one.
    const fallbackOf = (m: ModelRoute) => {
      if (!m.fallback) throw new Error(`model ${m.key} has no fallback`);
      return m.fallback;
    };
    // The first-byte timeout lives inside the fallback block (rule schema), so a route
    // without a fallback has no timeout at all.
    const fallbackBlock = (m: ModelRoute, firstByteTimeoutMs: number | undefined, circuitBreaker: 'ENABLED' | 'DISABLED' = 'ENABLED') =>
      m.fallback && targetEnabled(m.fallback.target)
        ? {
            CircuitBreaker: { Mode: circuitBreaker },
            TriggerOn: { StatusCodes: FALLBACK_STATUS_CODES, Errors: FALLBACK_ERRORS },
            FirstByteTimeoutMilliseconds: firstByteTimeoutMs,
            TargetFallback: [{ TargetName: m.fallback.target, Model: m.fallback.model }],
          }
        : undefined; // Kimi (no fallback), or Claude in 3P-only mode (-c enable1p=false)

    // Every name a client may use for a model maps to the same rule, so aliases
    // and vendor/Bedrock-style IDs get the same fallback chain as the canonical name.
    for (const m of MODELS) {
      rule(
        `Route-${m.key}`,
        m.priority,
        `${m.canonical}: Bedrock ${m.bedrockModel}, ${m.fallback ? `fallback ${m.fallback.target} ${m.fallback.model}` : 'no fallback'}`,
        [m.canonical, m.bedrockModel, m.vendorModel, ...m.aliases],
        { StaticRoute: { TargetName: TARGET_BEDROCK, Model: m.bedrockModel, Fallback: fallbackBlock(m, m.primaryFirstByteTimeoutMs) } },
      );
    }

    // Dynamic routing: the primary has no pinned model, so Bedrock serves the
    // model the interceptor chose; a Bedrock failure degrades to one fixed 1P model.
    const degraded = modelByKey(AUTO_ROUTE.degradedModelKey);
    const degradedTo = fallbackOf(degraded);
    rule('Route-auto', AUTO_ROUTE.priority,
      `${AUTO_ROUTE.alias}: interceptor-selected model on Bedrock, degrades to ${degradedTo.target} ${degradedTo.model}`,
      [AUTO_ROUTE.alias], {
        StaticRoute: { TargetName: TARGET_BEDROCK, Fallback: fallbackBlock(degraded, AUTO_ROUTE.firstByteTimeoutMs) },
      });

    // A/B experiment: each leg keeps its own fallback chain.
    rule('Route-experiment', EXPERIMENT.priority, `${EXPERIMENT.alias}: weighted model experiment`, [EXPERIMENT.alias], {
      WeightedRoute: {
        TrafficSplit: EXPERIMENT.legs.map((leg) => {
          const m = modelByKey(leg.modelKey);
          return {
            Name: leg.name,
            Weight: leg.weight,
            TargetName: TARGET_BEDROCK,
            Model: m.bedrockModel,
            Fallback: fallbackBlock(m, m.primaryFirstByteTimeoutMs),
            Metadata: { experiment: EXPERIMENT.alias, variant: leg.name },
          };
        }),
      },
    });

    // Failover drills: a stalled primary (50 ms first-byte timeout) → exercises
    // each family's fallback. The breaker is disabled so every call fails over.
    // The first drill keeps its original construct ID: replacing a rule would
    // briefly need two rules with the same priority.
    FAILOVER_DRILLS.forEach((d, i) => {
      const m = modelByKey(d.modelKey);
      const to = fallbackOf(m);
      if (!targetEnabled(to.target)) return;
      rule(i === 0 ? 'Route-failover-drill' : `Route-failover-drill-${m.key}`, d.priority,
        `${d.alias}: simulated stall on Bedrock, always fails over to ${to.target} (operational drill)`,
        [d.alias], {
          StaticRoute: {
            TargetName: TARGET_BEDROCK,
            Model: `arn:${partition}:bedrock:${region}:${account}:inference-profile/${m.bedrockModel}`,
            Fallback: fallbackBlock(m, DRILL_FIRST_BYTE_TIMEOUT_MS, 'DISABLED'),
          },
        });
    });

    // ------------------------------------------------------------------
    // 9. Rate limits: before rules and Cedar (AWS docs), but after the REQUEST
    //    interceptor (measured 2026-11-05: requests rejected here had already invoked
    //    the interceptor and ApplyGuardrail), so they cannot shield either one.
    // ------------------------------------------------------------------
    const perMinute = (rate: number) => [{ rate, period: 'minute' }];
    const perSecond = (rate: number) => [{ rate, period: 'second' }];
    const teamKey = '$.context.jwt.client_id';
    chain(
      new agentcore.CfnGatewayRateLimit(this, 'TeamRateLimit', {
        gatewayIdentifier: gatewayId,
        rateLimitId: 'per-team',
        description: 'Per-team RPM / TPM / concurrent connections (Cognito client_id)',
        dimensionKeys: [teamKey],
        entries: [
          ...auth.teamClients.map((tc) => ({
            dimensions: { [teamKey]: tc.client.userPoolClientId },
            requests: perMinute(tc.team.rpm),
            tokens: perMinute(tc.team.tpm),
            connections: perSecond(tc.team.connections),
          })),
          {
            dimensions: { [teamKey]: '*' },
            requests: perMinute(DEFAULT_TEAM_LIMITS.rpm),
            tokens: perMinute(DEFAULT_TEAM_LIMITS.tpm),
            connections: perSecond(DEFAULT_TEAM_LIMITS.connections),
          },
        ],
      }),
    );
    chain(
      new agentcore.CfnGatewayRateLimit(this, 'ModelRateLimit', {
        gatewayIdentifier: gatewayId,
        rateLimitId: 'per-model',
        description: 'Gateway-wide TPM per served model (protects shared provider quotas)',
        dimensionKeys: ['qualifiedModelId'],
        entries: [
          ...MODELS.flatMap((m) =>
            [m.bedrockModel, ...(m.fallback ? [m.fallback.model] : [])].map((model) => ({
              dimensions: { qualifiedModelId: model },
              tokens: perMinute(m.tpm),
            })),
          ),
          { dimensions: { qualifiedModelId: '*' }, tokens: perMinute(DEFAULT_MODEL_TPM) },
        ],
      }),
    );

    // ------------------------------------------------------------------
    // 10. Observability
    // ------------------------------------------------------------------
    const observability = new Observability(this, 'Observability', {
      gatewayArn: this.gateway.attrGatewayArn,
      gatewayId,
      policyEngineId: this.policyEngine.attrPolicyEngineId,
      interceptor: interceptor.function,
      proxy: oneP?.function,
      metricsNamespace: METRICS_NAMESPACE,
      alarmEmail: props.alarmEmail,
    });

    // ------------------------------------------------------------------
    // Outputs
    // ------------------------------------------------------------------
    const out = (id: string, value: string, description: string) =>
      new CfnOutput(this, id, { value, description, exportName: `LlmGateway-${id}` });
    out('GatewayId', gatewayId, 'AgentCore Gateway identifier');
    out('GatewayArn', this.gateway.attrGatewayArn, 'AgentCore Gateway ARN');
    out('InferenceEndpoint', `https://${gatewayId}.gateway.bedrock-agentcore.${region}.amazonaws.com/inference`,
      'Base URL — Anthropic SDK base_url; append /v1 for the OpenAI SDK');
    out('TokenEndpoint', auth.tokenEndpoint, 'Cognito OAuth2 token endpoint (client_credentials)');
    out('PolicyEngineId', this.policyEngine.attrPolicyEngineId, 'Cedar policy engine ID');
    out('AnthropicFallback', with1p ? 'enabled' : 'disabled (3P only)', '1P fallback state');
    out('TeamCredentialSecrets', auth.teamClients.map((tc) => tc.credentials.secretName).join(','),
      'Per-team OAuth client credential secrets');
    out('GuardrailId', interceptor.guardrail.attrGuardrailId, 'Bedrock guardrail used by the interceptor');
    out('GatewayLogGroup', observability.logGroup.logGroupName, 'Vended gateway application logs');
    out('DashboardUrl',
      `https://${region}.console.aws.amazon.com/cloudwatch/home?region=${region}#dashboards/dashboard/${observability.dashboard.dashboardName}`,
      'CloudWatch dashboard');
  }
}
