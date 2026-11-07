#!/usr/bin/env node
import { App, Tags } from 'aws-cdk-lib';
import { REGION } from '../lib/config';
import { LlmGatewayStack } from '../lib/llm-gateway-stack';
import { LlmGatewayPolicyStack } from '../lib/policy-stack';

const app = new App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: REGION };

// OFF detaches the policy engine from the gateway (benchmark only: no Cedar authorization at all).
const policyMode = String(app.node.tryGetContext('policyMode') ?? 'ENFORCE') as 'ENFORCE' | 'LOG_ONLY' | 'OFF';
if (!['ENFORCE', 'LOG_ONLY', 'OFF'].includes(policyMode)) throw new Error(`policyMode must be ENFORCE, LOG_ONLY or OFF, got ${policyMode}`);
const alarmEmail = app.node.tryGetContext('alarmEmail') as string | undefined;
const enableAnthropicFallback = String(app.node.tryGetContext('enable1p') ?? 'true') !== 'false';
// guardrail=off makes the interceptor skip ApplyGuardrail (benchmark only).
const guardrailEnabled = String(app.node.tryGetContext('guardrail') ?? 'on') !== 'off';

const core = new LlmGatewayStack(app, 'LlmGatewayStack', {
  env,
  description: 'LLM Gateway on AgentCore Gateway — Bedrock Global CRIS (3P) with Claude Platform on AWS (1P) fallback',
  policyMode,
  alarmEmail,
  enableAnthropicFallback,
  guardrailEnabled,
});

new LlmGatewayPolicyStack(app, 'LlmGatewayPolicyStack', {
  env,
  description: 'Cedar policies for the LLM Gateway',
  policyEngineId: core.policyEngine.attrPolicyEngineId,
  gatewayArn: core.gateway.attrGatewayArn,
  enableAnthropicFallback,
});

Tags.of(app).add('Project', 'llm-gateway');
