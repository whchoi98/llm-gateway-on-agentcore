import { Duration, RemovalPolicy, SecretValue, Stack } from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
import { RESOURCE_SERVER_ID, SCOPE_INVOKE, SCOPE_PREMIUM, TEAMS, TeamConfig } from '../config';

export interface TeamClient {
  readonly team: TeamConfig;
  readonly client: cognito.UserPoolClient;
  /** Secret holding client_id / client_secret / token_url / scope for that team. */
  readonly credentials: secretsmanager.Secret;
}

/**
 * Inbound authentication: a Cognito user pool that issues OAuth2
 * client-credentials (machine-to-machine) access tokens, one app client per
 * team. Cognito access tokens carry `client_id` and `scope`, which the gateway
 * uses for JWT validation, per-team rate limits and Cedar authorization.
 */
export class InboundAuth extends Construct {
  readonly userPool: cognito.UserPool;
  readonly discoveryUrl: string;
  readonly tokenEndpoint: string;
  readonly teamClients: TeamClient[];
  readonly invokeScope: string;
  readonly premiumScope: string;

  constructor(scope: Construct, id: string) {
    super(scope, id);
    const stack = Stack.of(this);

    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: 'llm-gateway-clients',
      selfSignUpEnabled: false,
      featurePlan: cognito.FeaturePlan.LITE,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const domain = this.userPool.addDomain('Domain', {
      cognitoDomain: { domainPrefix: `llm-gw-${stack.account}` },
    });

    const invoke = new cognito.ResourceServerScope({ scopeName: SCOPE_INVOKE, scopeDescription: 'Invoke LLM models' });
    const premium = new cognito.ResourceServerScope({ scopeName: SCOPE_PREMIUM, scopeDescription: 'Access premium models (Opus)' });
    const resourceServer = this.userPool.addResourceServer('ResourceServer', {
      identifier: RESOURCE_SERVER_ID,
      scopes: [invoke, premium],
    });

    this.invokeScope = `${RESOURCE_SERVER_ID}/${SCOPE_INVOKE}`;
    this.premiumScope = `${RESOURCE_SERVER_ID}/${SCOPE_PREMIUM}`;
    this.discoveryUrl = `https://cognito-idp.${stack.region}.amazonaws.com/${this.userPool.userPoolId}/.well-known/openid-configuration`;
    this.tokenEndpoint = `${domain.baseUrl()}/oauth2/token`;

    this.teamClients = TEAMS.map((team) => {
      const scopes = [cognito.OAuthScope.resourceServer(resourceServer, invoke)];
      if (team.premium) scopes.push(cognito.OAuthScope.resourceServer(resourceServer, premium));

      const client = this.userPool.addClient(team.name, {
        userPoolClientName: team.name,
        generateSecret: true,
        oAuth: { flows: { clientCredentials: true }, scopes },
        accessTokenValidity: Duration.hours(1),
        preventUserExistenceErrors: true,
      });

      // Hand-off package for the team: everything needed to obtain a token.
      const credentials = new secretsmanager.Secret(this, `${team.name}-credentials`, {
        secretName: `llm-gateway/clients/${team.name}`,
        description: `OAuth2 client credentials for ${team.name} (LLM Gateway)`,
        secretObjectValue: {
          client_id: SecretValue.unsafePlainText(client.userPoolClientId),
          client_secret: client.userPoolClientSecret,
          token_url: SecretValue.unsafePlainText(this.tokenEndpoint),
          scope: SecretValue.unsafePlainText(scopes.map((s) => s.scopeName).join(' ')),
        },
        removalPolicy: RemovalPolicy.DESTROY,
      });

      return { team, client, credentials };
    });
  }
}
