import { createHash } from 'node:crypto';
import * as path from 'node:path';
import { Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import {
  AUTO_ROUTE,
  EXPERIMENT,
  FAILOVER_DRILLS,
  GUARDRAIL_FAIL_MODE,
  GUARDRAIL_MAX_CHARS,
  LOG_RETENTION_DAYS,
  MODELS,
  modelByKey,
} from '../config';

export interface GuardrailInterceptorProps {
  /** Cognito client ID → team name, for metric attribution. */
  readonly teamClients: Record<string, string>;
  readonly premiumScope: string;
  readonly metricsNamespace: string;
}

/**
 * Input guardrail + REQUEST interceptor.
 *
 * Guardrails-in-Policy (Cedar `when guardrails {...}`) is not offered in
 * ap-northeast-2, so the interceptor calls Bedrock ApplyGuardrail itself.
 * Content filters use the Standard tier (multilingual, including Korean),
 * which requires the APAC cross-Region guardrail profile.
 */
export class GuardrailInterceptor extends Construct {
  readonly guardrail: bedrock.CfnGuardrail;
  readonly guardrailVersion: bedrock.CfnGuardrailVersion;
  readonly function: lambda.Function;

  constructor(scope: Construct, id: string, props: GuardrailInterceptorProps) {
    super(scope, id);
    const stack = Stack.of(this);
    const guardrailProfileArn = `arn:${stack.partition}:bedrock:${stack.region}:${stack.account}:guardrail-profile/apac.guardrail.v1:0`;

    const guardrailProps: bedrock.CfnGuardrailProps = {
      name: 'llm-gateway-input',
      description: 'LLM Gateway input guardrail (applied by the REQUEST interceptor to 3P and 1P traffic)',
      blockedInputMessaging: 'Blocked by the LLM Gateway input guardrail.',
      blockedOutputsMessaging: 'Blocked by the LLM Gateway output guardrail.',
      crossRegionConfig: { guardrailProfileArn },
      contentPolicyConfig: {
        contentFiltersTierConfig: { tierName: 'STANDARD' },
        filtersConfig: [
          { type: 'HATE', inputStrength: 'MEDIUM', outputStrength: 'NONE' },
          { type: 'INSULTS', inputStrength: 'MEDIUM', outputStrength: 'NONE' },
          { type: 'SEXUAL', inputStrength: 'MEDIUM', outputStrength: 'NONE' },
          { type: 'VIOLENCE', inputStrength: 'MEDIUM', outputStrength: 'NONE' },
          { type: 'MISCONDUCT', inputStrength: 'LOW', outputStrength: 'NONE' },
          { type: 'PROMPT_ATTACK', inputStrength: 'HIGH', outputStrength: 'NONE' },
        ],
      },
      sensitiveInformationPolicyConfig: {
        // Secrets should never leave the company in a prompt.
        piiEntitiesConfig: [
          { type: 'AWS_ACCESS_KEY', action: 'BLOCK' },
          { type: 'AWS_SECRET_KEY', action: 'BLOCK' },
          { type: 'CREDIT_DEBIT_CARD_NUMBER', action: 'BLOCK' },
        ],
        regexesConfig: [
          {
            name: 'kr-resident-registration-number',
            description: '주민등록번호 (YYMMDD-GNNNNNN)',
            pattern: '\\b\\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\\d|3[01])-?[1-4]\\d{6}\\b',
            action: 'BLOCK',
          },
        ],
      },
    };
    this.guardrail = new bedrock.CfnGuardrail(this, 'Guardrail', guardrailProps);

    // GuardrailVersion is immutable; hashing the config into the description
    // makes any guardrail change publish a new numbered version. Hash the
    // resolved form: raw token strings (${Token[...]}) are renumbered whenever
    // constructs are added, which would publish a new version on every change.
    const configHash = createHash('sha256')
      .update(JSON.stringify(stack.resolve(guardrailProps)))
      .digest('hex')
      .slice(0, 12);
    this.guardrailVersion = new bedrock.CfnGuardrailVersion(this, 'GuardrailVersion', {
      guardrailIdentifier: this.guardrail.attrGuardrailId,
      description: `config ${configHash}`,
    });

    // Name → canonical model, for metric attribution only. Static aliases are
    // routed by the gateway rules (which match before the interceptor runs),
    // so the interceptor never rewrites them.
    const canonical: Record<string, string> = {};
    const family: Record<string, string> = {};
    for (const m of MODELS) {
      for (const name of [m.canonical, m.bedrockModel, m.vendorModel, ...m.aliases]) canonical[name] = m.canonical;
      family[m.canonical] = m.family;
    }
    // Rule-only aliases are models too: the interceptor refuses any model missing from MODEL_FAMILIES.
    for (const d of FAILOVER_DRILLS) family[d.alias] = modelByKey(d.modelKey).family;
    family[EXPERIMENT.alias] = modelByKey(EXPERIMENT.legs[0].modelKey).family;
    const bedrockId = (key: string) => modelByKey(key).bedrockModel;

    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      logGroupName: '/aws/lambda/llm-gateway-interceptor',
      retention: LOG_RETENTION_DAYS as logs.RetentionDays,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    this.function = new lambda.Function(this, 'Function', {
      functionName: 'llm-gateway-interceptor',
      description: 'AgentCore Gateway REQUEST interceptor: model aliases, input guardrail, per-team metrics',
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: 'index.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'lambda', 'interceptor')),
      memorySize: 512,
      timeout: Duration.seconds(10),
      // Links the function's own segment (init, invocation) to the gateway trace.
      tracing: lambda.Tracing.ACTIVE,
      logGroup,
      environment: {
        GUARDRAIL_ID: this.guardrail.attrGuardrailId,
        GUARDRAIL_VERSION: this.guardrailVersion.attrVersion,
        GUARDRAIL_FAIL_MODE,
        GUARDRAIL_MAX_CHARS: String(GUARDRAIL_MAX_CHARS),
        METRICS_NAMESPACE: props.metricsNamespace,
        CANONICAL_MODELS: JSON.stringify(canonical),
        MODEL_FAMILIES: JSON.stringify(family),
        AUTO_MODEL_ALIAS: AUTO_ROUTE.alias,
        // claude-auto resolves to Bedrock IDs: the auto rule's primary serves the rewritten model.
        AUTO_MODELS: JSON.stringify({ small: bedrockId('haiku'), medium: bedrockId('sonnet'), large: bedrockId('opus') }),
        TEAM_CLIENTS: stack.toJsonString(props.teamClients),
        PREMIUM_SCOPE: props.premiumScope,
      },
    });

    // Standard tier evaluates in any APAC Region of the guardrail profile.
    this.function.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:ApplyGuardrail'],
        resources: [
          this.guardrail.attrGuardrailArn,
          `arn:${stack.partition}:bedrock:*:${stack.account}:guardrail/${this.guardrail.attrGuardrailId}`,
          `arn:${stack.partition}:bedrock:*:${stack.account}:guardrail-profile/apac.guardrail.v1:0`,
        ],
      }),
    );
  }
}
