import * as path from 'node:path';
import { Duration, Fn, RemovalPolicy } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import { LOG_RETENTION_DAYS, ONE_P } from '../config';

/**
 * Lambda Function URL that fronts Claude Platform on AWS for the gateway's 1P
 * target, adding the API key and the required `anthropic-workspace-id` header.
 */
export class CpOnAwsProxy extends Construct {
  readonly function: lambda.Function;
  readonly functionUrl: lambda.FunctionUrl;
  /** Endpoint for the gateway target (scheme + host, no trailing slash). */
  readonly endpoint: string;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    const apiKeySecret = secretsmanager.Secret.fromSecretNameV2(this, 'ApiKey', ONE_P.secretName);
    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      logGroupName: '/aws/lambda/llm-gateway-cponaws-proxy',
      retention: LOG_RETENTION_DAYS as logs.RetentionDays,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    this.function = new lambda.Function(this, 'Function', {
      functionName: 'llm-gateway-cponaws-proxy',
      description: 'Streams gateway 1P traffic to Claude Platform on AWS, adding the workspace header',
      runtime: lambda.Runtime.NODEJS_24_X,
      architecture: lambda.Architecture.ARM_64,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'lambda', 'cponaws-proxy')),
      memorySize: 256,
      // Long non-streaming Opus completions on the fallback path.
      timeout: Duration.minutes(15),
      logGroup,
      environment: {
        UPSTREAM_URL: ONE_P.endpoint,
        // Resolved by CloudFormation at deploy time; the template holds only the parameter name.
        WORKSPACE_ID: ssm.StringParameter.valueForStringParameter(this, ONE_P.workspaceParameter),
        SECRET_ID: ONE_P.secretName,
      },
    });
    apiKeySecret.grantRead(this.function);

    this.functionUrl = this.function.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.AWS_IAM,
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
    });
    // https://<id>.lambda-url.<region>.on.aws/ → https://<id>.lambda-url.<region>.on.aws
    this.endpoint = `https://${Fn.select(2, Fn.split('/', this.functionUrl.url))}`;
  }

  /** Lets the gateway role call the URL (SigV4, service `lambda`). */
  grantInvoke(grantee: iam.IGrantable) {
    this.functionUrl.grantInvokeUrl(grantee);
    this.function.grantInvoke(grantee);
  }
}
