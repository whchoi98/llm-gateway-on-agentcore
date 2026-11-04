#!/usr/bin/env node
import { App, Tags } from 'aws-cdk-lib';
import { REGION } from '../lib/config';
import { LlmGatewayStack } from '../lib/llm-gateway-stack';
import { LlmGatewayPolicyStack } from '../lib/policy-stack';

const app = new App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: REGION };

const policyMode = (app.node.tryGetContext('policyMode') ?? 'ENFORCE') as 'ENFORCE' | 'LOG_ONLY';
const alarmEmail = app.node.tryGetContext('alarmEmail') as string | undefined;
const enableAnthropicFallback = String(app.node.tryGetContext('enable1p') ?? 'true') !== 'false';

const core = new LlmGatewayStack(app, 'LlmGatewayStack', {
  env,
  description: 'LLM Gateway on AgentCore Gateway — Bedrock Global CRIS (3P) with Claude Platform on AWS (1P) fallback',
  policyMode,
  alarmEmail,
  enableAnthropicFallback,
});

new LlmGatewayPolicyStack(app, 'LlmGatewayPolicyStack', {
  env,
  description: 'Cedar policies for the LLM Gateway',
  policyEngineId: core.policyEngine.attrPolicyEngineId,
  gatewayArn: core.gateway.attrGatewayArn,
  enableAnthropicFallback,
});

Tags.of(app).add('Project', 'llm-gateway');
