import { Stack, StackProps } from 'aws-cdk-lib';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import { Construct } from 'constructs';
import {
  EXPERIMENT,
  MAX_OUTPUT_TOKENS_STANDARD,
  MODELS,
  RESOURCE_SERVER_ID,
  SCOPE_INVOKE,
  SCOPE_PREMIUM,
  TARGET_ANTHROPIC,
  TARGET_BEDROCK,
  TARGET_MANTLE,
} from './config';

export interface LlmGatewayPolicyStackProps extends StackProps {
  readonly policyEngineId: string;
  readonly gatewayArn: string;
  /** Include actions of the Anthropic (1P) target. Must match the core stack. */
  readonly enableAnthropicFallback: boolean;
}

/**
 * Cedar authorization for the LLM Gateway, kept in its own stack: policies
 * change more often than the gateway, and a policy rejected by validation
 * (run against the gateway's generated schema) rolls back only this stack.
 *
 * Evaluation is deny-by-default: `permit` grants, `forbid` subtracts.
 *
 * Schema facts verified against this gateway:
 * - Actions are `<target>___<METHOD>:<path>`, e.g. `bedrock___POST:/v1/messages`.
 * - Request body fields are `context.input.<field>` and are optional, so every
 *   read needs a `has` guard. Without it Cedar Analysis reports the forbid as
 *   "Overly Restrictive" (it would deny every request).
 * - OAuth claims are principal tags (`principal.getTag("scope")`).
 */
export class LlmGatewayPolicyStack extends Stack {
  constructor(scope: Construct, id: string, props: LlmGatewayPolicyStackProps) {
    super(scope, id, props);

    const gateway = `AgentCore::Gateway::"${props.gatewayArn}"`;
    const hasScope = (s: string) =>
      `(principal.hasTag("scope") && principal.getTag("scope") like "*${RESOURCE_SERVER_ID}/${s}*")`;
    const actions = (targets: string[], path: string) =>
      targets.map((t) => `AgentCore::Action::"${t}___POST:${path}"`).join(', ');
    // One action per target per API shape: Claude speaks Messages, GPT speaks the OpenAI APIs.
    const messagesActions = actions(props.enableAnthropicFallback ? [TARGET_BEDROCK, TARGET_ANTHROPIC] : [TARGET_BEDROCK], '/v1/messages');
    const chatActions = actions([TARGET_BEDROCK, TARGET_MANTLE], '/v1/chat/completions');
    const responsesActions = actions([TARGET_BEDROCK, TARGET_MANTLE], '/v1/responses');
    const cap = MAX_OUTPUT_TOKENS_STANDARD;
    const over = (field: string) => `(context.input has ${field} && context.input.${field} > ${cap})`;

    // Premium models by family name, plus the experiment alias (it routes a share of traffic to Opus).
    const premiumFamilies = MODELS.filter((m) => m.premiumOnly).map((m) => `context.input.model like "*${m.key}*"`);
    const premiumModel = [...premiumFamilies, `context.input.model == "${EXPERIMENT.alias}"`].join(' || ');

    const statements: Record<string, { description: string; statement: string }> = {
      permit_invoke_scope: {
        description: 'Clients holding the invoke scope may use the gateway',
        statement: `permit(principal is AgentCore::OAuthUser, action, resource == ${gateway})
when { ${hasScope(SCOPE_INVOKE)} };`,
      },
      forbid_premium_models: {
        description: 'Opus (and the Opus-bearing experiment) require the premium scope',
        statement: `forbid(principal is AgentCore::OAuthUser, action in [${messagesActions}], resource == ${gateway})
when { context.input has model && (${premiumModel}) && !${hasScope(SCOPE_PREMIUM)} };`,
      },
      forbid_large_max_tokens: {
        description: `Token limit policy (Messages): max_tokens above ${cap} requires the premium scope`,
        statement: `forbid(principal is AgentCore::OAuthUser, action in [${messagesActions}], resource == ${gateway})
when { ${over('max_tokens')} && !${hasScope(SCOPE_PREMIUM)} };`,
      },
      forbid_large_output_chat: {
        description: `Token limit policy (Chat Completions): output tokens above ${cap} require the premium scope`,
        statement: `forbid(principal is AgentCore::OAuthUser, action in [${chatActions}], resource == ${gateway})
when { (${over('max_completion_tokens')} || ${over('max_tokens')}) && !${hasScope(SCOPE_PREMIUM)} };`,
      },
      forbid_large_output_responses: {
        description: `Token limit policy (Responses): max_output_tokens above ${cap} requires the premium scope`,
        statement: `forbid(principal is AgentCore::OAuthUser, action in [${responsesActions}], resource == ${gateway})
when { ${over('max_output_tokens')} && !${hasScope(SCOPE_PREMIUM)} };`,
      },
    };

    for (const [name, { description, statement }] of Object.entries(statements)) {
      new agentcore.CfnPolicy(this, name, {
        policyEngineId: props.policyEngineId,
        name,
        description,
        definition: { cedar: { statement } },
        validationMode: 'FAIL_ON_ANY_FINDINGS',
      });
    }
  }
}
