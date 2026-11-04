import { Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cwActions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import { Construct } from 'constructs';
import {
  FAILOVER_DRILLS,
  GATEWAY_NAME,
  LOG_RETENTION_DAYS,
  MODELS,
  TARGET_ANTHROPIC,
  TARGET_BEDROCK,
  TARGET_MANTLE,
  TEAMS,
} from '../config';

export interface ObservabilityProps {
  readonly gatewayArn: string;
  readonly gatewayId: string;
  readonly policyEngineId: string;
  readonly interceptor: lambda.IFunction;
  readonly proxy?: lambda.IFunction;
  readonly metricsNamespace: string;
  /** Optional e-mail for alarm notifications (`-c alarmEmail=...`). */
  readonly alarmEmail?: string;
}

/**
 * Gateway observability, built on what an inference gateway actually emits
 * (verified on this deployment):
 *
 * - Request/latency/error metrics: `ApplicationSignals` namespace (from the
 *   gateway's X-Ray traces), Service=<gateway-id>, Operation=AgentCore.Gateway.InvokeHttp.
 *   (The `AWS/Bedrock-AgentCore` InvokeGateway metrics are emitted for MCP
 *   traffic, not inference; that namespace carries the Policy decision metrics.)
 * - Routing decisions: vended APPLICATION_LOGS carry `body.routing`
 *   {requestedModelId, resolvedModelId, targetName, reason, routingRuleId}.
 *   `reason = servedViaFallbackHop:N` marks a request served by a fallback,
 *   which callers cannot see. Metric filters turn this into metrics.
 * - Per-team / per-model usage and guardrail outcomes: interceptor EMF.
 */
export class Observability extends Construct {
  readonly logGroup: logs.LogGroup;
  readonly dashboard: cloudwatch.Dashboard;
  readonly alarmTopic: sns.Topic;

  constructor(scope: Construct, id: string, props: ObservabilityProps) {
    super(scope, id);
    const stack = Stack.of(this);
    const ns = props.metricsNamespace;

    // ---------------------------------------------------------------- logs
    this.logGroup = new logs.LogGroup(this, 'GatewayLogs', {
      logGroupName: `/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/${GATEWAY_NAME}`,
      retention: LOG_RETENTION_DAYS as logs.RetentionDays,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const logsSource = new logs.CfnDeliverySource(this, 'LogsSource', {
      name: `${GATEWAY_NAME}-logs`,
      logType: 'APPLICATION_LOGS',
      resourceArn: props.gatewayArn,
    });
    const logsDestination = new logs.CfnDeliveryDestination(this, 'LogsDestination', {
      name: `${GATEWAY_NAME}-logs-cwl`,
      destinationResourceArn: this.logGroup.logGroupArn,
    });
    new logs.CfnDelivery(this, 'LogsDelivery', {
      deliverySourceName: logsSource.ref,
      deliveryDestinationArn: logsDestination.attrArn,
    }).addDependency(logsSource);

    // Transaction Search is enabled in this account, so X-Ray is the trace sink
    // (it also feeds the ApplicationSignals metrics used below).
    const tracesSource = new logs.CfnDeliverySource(this, 'TracesSource', {
      name: `${GATEWAY_NAME}-traces`,
      logType: 'TRACES',
      resourceArn: props.gatewayArn,
    });
    const tracesDestination = new logs.CfnDeliveryDestination(this, 'TracesDestination', {
      name: `${GATEWAY_NAME}-traces-xray`,
      deliveryDestinationType: 'XRAY',
    });
    new logs.CfnDelivery(this, 'TracesDelivery', {
      deliverySourceName: tracesSource.ref,
      deliveryDestinationArn: tracesDestination.attrArn,
    }).addDependency(tracesSource);

    // Routing decisions → metrics.
    new logs.MetricFilter(this, 'RoutedRequestsFilter', {
      logGroup: this.logGroup,
      metricNamespace: ns,
      metricName: 'RoutedRequests',
      filterPattern: logs.FilterPattern.literal('{ $.body.log = "Model routing succeeded" }'),
      metricValue: '1',
      dimensions: { Target: '$.body.routing.targetName', Model: '$.body.routing.resolvedModelId' },
      unit: cloudwatch.Unit.COUNT,
    });
    new logs.MetricFilter(this, 'FallbackServedFilter', {
      logGroup: this.logGroup,
      metricNamespace: ns,
      metricName: 'FallbackServed',
      // Drill traffic always fails over by design; keep it out of the health signal.
      filterPattern: logs.FilterPattern.literal(
        `{ ($.body.routing.reason = "servedViaFallbackHop*")${FAILOVER_DRILLS.map((d) => ` && ($.body.routing.requestedModelId != "${d.alias}")`).join('')} }`,
      ),
      metricValue: '1',
      dimensions: { Model: '$.body.routing.resolvedModelId', Target: '$.body.routing.targetName' },
      unit: cloudwatch.Unit.COUNT,
    });

    // Saved Logs Insights queries.
    const interceptorLogs = logs.LogGroup.fromLogGroupName(this, 'InterceptorLogs', '/aws/lambda/llm-gateway-interceptor');
    new logs.QueryDefinition(this, 'FallbackQuery', {
      queryDefinitionName: `${GATEWAY_NAME}/fallbacks`,
      logGroups: [this.logGroup],
      queryString: new logs.QueryString({
        fields: ['@timestamp', 'request_id', 'body.routing.requestedModelId', 'body.routing.resolvedModelId', 'body.routing.targetName', 'body.routing.reason'],
        filterStatements: ['body.routing.reason like /Fallback/'],
        sort: '@timestamp desc',
        limit: 200,
      }),
    });
    new logs.QueryDefinition(this, 'RoutingMixQuery', {
      queryDefinitionName: `${GATEWAY_NAME}/routing-mix`,
      logGroups: [this.logGroup],
      queryString: new logs.QueryString({
        filterStatements: ['body.log = "Model routing succeeded"'],
        stats: 'count(*) as requests by body.routing.targetName, body.routing.resolvedModelId, body.routing.reason',
        sort: 'requests desc',
      }),
    });
    new logs.QueryDefinition(this, 'GuardrailBlocksQuery', {
      queryDefinitionName: `${GATEWAY_NAME}/guardrail-blocks`,
      logGroups: [interceptorLogs],
      queryString: new logs.QueryString({
        fields: ['@timestamp', 'Team', 'Model', 'guardrailReason', 'gatewayRequestId'],
        filterStatements: ['GuardrailBlocked = 1'],
        sort: '@timestamp desc',
        limit: 200,
      }),
    });

    // ------------------------------------------------------------- metrics
    const svc = (metricName: string, statistic: string, label?: string) =>
      new cloudwatch.Metric({
        namespace: 'ApplicationSignals',
        metricName,
        dimensionsMap: {
          Environment: 'bedrock-agentcore:default',
          Service: props.gatewayId,
          Operation: 'AgentCore.Gateway.InvokeHttp',
        },
        statistic,
        period: Duration.minutes(1),
        label,
      });
    const policy = (metricName: string, label: string) =>
      new cloudwatch.Metric({
        namespace: 'AWS/Bedrock-AgentCore',
        metricName,
        dimensionsMap: { TargetResource: props.gatewayId, OperationName: 'AuthorizeAction', PolicyEngine: props.policyEngineId },
        statistic: 'Sum',
        period: Duration.minutes(1),
        label,
      });
    const emf = (metricName: string, dims: Record<string, string>, statistic = 'Sum', label?: string) =>
      new cloudwatch.Metric({ namespace: ns, metricName, dimensionsMap: dims, statistic, period: Duration.minutes(1), label });
    const routedByTarget = (target: string, label: string) =>
      new cloudwatch.MathExpression({
        expression: `SUM(SEARCH('{${ns},Model,Target} MetricName="RoutedRequests" Target="${target}"', 'Sum', 60))`,
        label,
        period: Duration.minutes(1),
      });

    this.dashboard = new cloudwatch.Dashboard(this, 'Dashboard', {
      dashboardName: `${GATEWAY_NAME}-${stack.region}`,
      defaultInterval: Duration.hours(3),
    });
    this.dashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown:
          `# LLM Gateway (${stack.region})\n` +
          `Primary **Bedrock Global CRIS** (3P, target \`${TARGET_BEDROCK}\`). Fallback: Claude to **Claude Platform on AWS** (1P, target \`${TARGET_ANTHROPIC}\`), ` +
          `GPT to **Bedrock Mantle us-east-1** (target \`${TARGET_MANTLE}\`). Routing decisions: \`${this.logGroup.logGroupName}\` (\`body.routing\`); ` +
          `spans: \`aws/spans\` (X-Ray, Transaction Search).`,
        width: 24,
        height: 2,
      }),
    );
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'Gateway requests and errors',
        left: [svc('Latency', 'SampleCount', 'Requests')],
        right: [svc('Error', 'Sum', '4xx'), svc('Fault', 'Sum', '5xx'), svc('Throttle', 'Sum', 'Throttled')],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: 'Gateway latency (ms)',
        left: [svc('Latency', 'p50', 'p50'), svc('Latency', 'p90', 'p90'), svc('Latency', 'p99', 'p99')],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: 'Served by target',
        left: [
          routedByTarget(TARGET_BEDROCK, 'Bedrock Global CRIS (primary)'),
          routedByTarget(TARGET_ANTHROPIC, 'CPonAWS (Claude fallback)'),
          routedByTarget(TARGET_MANTLE, 'Mantle us-east-1 (GPT fallback)'),
        ],
        right: [
          new cloudwatch.MathExpression({
            expression: `SUM(SEARCH('{${ns},Model,Target} MetricName="FallbackServed"', 'Sum', 60))`,
            label: 'Fallbacks (excl. drills)',
            period: Duration.minutes(1),
          }),
        ],
        width: 8,
      }),
    );
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'Requests by team',
        left: TEAMS.map((t) => emf('Requests', { Team: t.name }, 'Sum', t.name)),
        width: 6,
      }),
      new cloudwatch.GraphWidget({
        title: 'Requests by model',
        left: MODELS.map((m) => emf('Requests', { Model: m.canonical }, 'Sum', m.canonical)),
        width: 6,
      }),
      new cloudwatch.GraphWidget({
        title: 'Policy decisions (Cedar)',
        left: [policy('AllowDecisions', 'Allow'), policy('DenyDecisions', 'Deny')],
        width: 6,
      }),
      new cloudwatch.GraphWidget({
        title: 'Guardrail',
        left: TEAMS.map((t) => emf('GuardrailBlocked', { Team: t.name }, 'Sum', `blocked ${t.name}`)),
        right: TEAMS.map((t) => emf('GuardrailLatency', { Team: t.name }, 'p90', `p90 ms ${t.name}`)),
        width: 6,
      }),
    );
    const lambdaWidgets: cloudwatch.IWidget[] = [
      new cloudwatch.GraphWidget({
        title: 'Interceptor Lambda',
        left: [props.interceptor.metricInvocations(), props.interceptor.metricErrors(), props.interceptor.metricThrottles()],
        right: [props.interceptor.metricDuration({ statistic: 'p99' })],
        width: 8,
      }),
    ];
    if (props.proxy) {
      lambdaWidgets.push(
        new cloudwatch.GraphWidget({
          title: '1P proxy Lambda (CPonAWS)',
          left: [props.proxy.metricInvocations(), props.proxy.metricErrors()],
          right: [props.proxy.metricDuration({ statistic: 'p90' })],
          width: 8,
        }),
      );
    }
    lambdaWidgets.push(
      new cloudwatch.LogQueryWidget({
        title: 'Recent fallbacks',
        logGroupNames: [this.logGroup.logGroupName],
        queryLines: [
          'fields @timestamp, body.routing.requestedModelId, body.routing.targetName, body.routing.reason',
          'filter body.routing.reason like /Fallback/',
          'sort @timestamp desc',
          'limit 50',
        ],
        width: props.proxy ? 8 : 16,
      }),
    );
    this.dashboard.addWidgets(...lambdaWidgets);

    // Fallback detail, interceptor denials, and quota pressure on the primary.
    const bedrock = (metricName: string, modelId: string) =>
      new cloudwatch.Metric({ namespace: 'AWS/Bedrock', metricName, dimensionsMap: { ModelId: modelId }, statistic: 'Sum', period: Duration.minutes(1) });
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'Fallbacks by model (excl. drills)',
        left: [
          new cloudwatch.MathExpression({
            expression: `SEARCH('{${ns},Model,Target} MetricName="FallbackServed"', 'Sum', 60)`,
            label: '',
            period: Duration.minutes(1),
          }),
        ],
        width: 6,
      }),
      new cloudwatch.GraphWidget({
        title: 'Interceptor denials by reason',
        left: [
          new cloudwatch.MathExpression({
            expression: `SEARCH('{${ns},Reason} MetricName="Denied"', 'Sum', 60)`,
            label: '',
            period: Duration.minutes(1),
          }),
        ],
        width: 6,
      }),
      new cloudwatch.GraphWidget({
        title: 'Bedrock tokens per minute (primary, input + output)',
        left: MODELS.map((m, i) =>
          new cloudwatch.MathExpression({
            expression: `in${i} + out${i}`,
            usingMetrics: { [`in${i}`]: bedrock('InputTokenCount', m.bedrockModel), [`out${i}`]: bedrock('OutputTokenCount', m.bedrockModel) },
            label: `${m.canonical} (gateway cap ${m.tpm / 1_000_000}M)`,
            period: Duration.minutes(1),
          }),
        ),
        width: 6,
      }),
      new cloudwatch.GraphWidget({
        title: 'Bedrock throttles (primary)',
        left: MODELS.map((m) => bedrock('InvocationThrottles', m.bedrockModel).with({ label: m.canonical })),
        width: 6,
      }),
    );
    const httpSpans = "filter name like /^AgentCore\\.Gateway\\.Http\\./";
    this.dashboard.addWidgets(
      new cloudwatch.LogQueryWidget({
        title: 'Target calls by target and status (spans)',
        logGroupNames: ['aws/spans'],
        queryLines: [
          httpSpans,
          'stats count(*) as calls, avg(durationNano) / 1000000 as avg_ms, pct(durationNano, 90) / 1000000 as p90_ms by name, attributes.http.status_code as status',
          'sort calls desc',
        ],
        width: 12,
      }),
      new cloudwatch.LogQueryWidget({
        title: 'Requests served by a fallback target (spans, incl. drills; open traceId in X-Ray)',
        logGroupNames: ['aws/spans'],
        queryLines: [
          "filter name in ['AgentCore.Gateway.Http.cponaws', 'AgentCore.Gateway.Http.mantle']",
          'fields @timestamp, name, traceId, durationNano / 1000000 as ms, attributes.http.status_code as status',
          'sort @timestamp desc',
          'limit 20',
        ],
        width: 12,
      }),
    );

    // -------------------------------------------------------------- alarms
    this.alarmTopic = new sns.Topic(this, 'AlarmTopic', { topicName: `${GATEWAY_NAME}-alarms` });
    if (props.alarmEmail) this.alarmTopic.addSubscription(new subscriptions.EmailSubscription(props.alarmEmail));
    const action = new cwActions.SnsAction(this.alarmTopic);
    const alarm = (id: string, metric: cloudwatch.IMetric, threshold: number, description: string) =>
      new cloudwatch.Alarm(this, id, {
        alarmName: `${GATEWAY_NAME}-${id}`,
        alarmDescription: description,
        metric,
        threshold,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        evaluationPeriods: 1,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      }).addAlarmAction(action);
    const fiveMin = { period: Duration.minutes(5) };

    alarm('GatewayFaults', svc('Fault', 'Sum').with(fiveMin), 5, '5xx returned to callers (fallback chain exhausted or gateway error)');
    alarm('GatewayThrottles', svc('Throttle', 'Sum').with(fiveMin), 50, 'Callers throttled (rate limits or provider quota)');
    alarm('InterceptorErrors', props.interceptor.metricErrors(fiveMin), 0, 'Interceptor Lambda errors — every gateway request depends on it');
    if (props.proxy) {
      alarm('ProxyErrors', props.proxy.metricErrors(fiveMin), 0, '1P proxy Lambda errors — the fallback path is impaired');
    }

    // Alarms cannot use SEARCH; Metrics Insights aggregates across dimensions.
    const insightsAlarm = (id: string, query: string, threshold: number, description: string) =>
      new cloudwatch.CfnAlarm(this, id, {
        alarmName: `${GATEWAY_NAME}-${id}`,
        alarmDescription: description,
        comparisonOperator: 'GreaterThanThreshold',
        evaluationPeriods: 1,
        threshold,
        treatMissingData: 'notBreaching',
        metrics: [{ id: 'q1', expression: query, period: 300, returnData: true }],
        alarmActions: [this.alarmTopic.topicArn],
      });
    insightsAlarm(
      'FallbackActive',
      `SELECT SUM(FallbackServed) FROM SCHEMA("${ns}", Model, Target)`,
      10,
      'Bedrock Global CRIS is degraded: more than 10 requests in 5 minutes were served by a fallback (CPonAWS or Mantle)',
    );
    insightsAlarm(
      'GuardrailErrors',
      `SELECT SUM(GuardrailErrors) FROM SCHEMA("${ns}", Team)`,
      0,
      'ApplyGuardrail failures (requests pass unchecked in fail-open mode)',
    );
  }
}
