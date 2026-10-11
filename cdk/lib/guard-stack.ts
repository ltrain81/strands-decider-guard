import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import { HttpUserPoolAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';

const ROOT = path.join(__dirname, '..', '..');
const DLAMI = '/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id';

export class DeciderGuardStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    const ctx = (k: string) => this.node.tryGetContext(k) as string;
    const instanceType = ctx('instanceType');
    const modelId = ctx('modelId');
    const deciderRef = ctx('deciderRef');

    // No NAT: the decider host sits in a public subnet with no inbound rules except from the guard Lambda,
    // and the Lambda sits in isolated subnets and only talks to the host's private IP.
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'isolated', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });

    const lambdaSg = new ec2.SecurityGroup(this, 'GuardFnSg', { vpc, allowAllOutbound: false, description: 'decider guard Lambda' });
    const deciderSg = new ec2.SecurityGroup(this, 'DeciderSg', { vpc, allowAllOutbound: true, description: 'strands-decider host' });
    deciderSg.addIngressRule(lambdaSg, ec2.Port.tcp(8000), 'guard Lambda to decider');
    lambdaSg.addEgressRule(deciderSg, ec2.Port.tcp(8000), 'guard Lambda to decider');
    // Policy reads go to S3 through a (free) gateway endpoint; the isolated subnets have no other route out.
    vpc.addGatewayEndpoint('S3Endpoint', { service: ec2.GatewayVpcEndpointAwsService.S3, subnets: [{ subnetType: ec2.SubnetType.PRIVATE_ISOLATED }] });
    lambdaSg.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'guard Lambda to S3 gateway endpoint');

    // Versioned policy store edited by the admin console; every save is a version (history + rollback).
    // No autoDeleteObjects: that adds a custom-resource IAM role; destroy.sh empties the bucket instead.
    const policyBucket = new s3.Bucket(this, 'PolicyBucket', {
      versioned: true, enforceSSL: true, blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED, removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const role = new iam.Role(this, 'DeciderRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore')],
    });

    const userData = ec2.UserData.forLinux();
    userData.addCommands(
      'set -euxo pipefail',
      'exec > >(tee -a /var/log/decider-setup.log) 2>&1',
      'export HOME=/root',
      'id decider || useradd --system --create-home --home-dir /opt/decider decider',
      'curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh',
      'export UV_PYTHON_INSTALL_DIR=/opt/decider/python',
      'uv venv --python 3.12 /opt/decider/venv',
      `VIRTUAL_ENV=/opt/decider/venv uv pip install "strands-decider @ git+https://github.com/strands-labs/strands-decider@${deciderRef}"`,
      'chown -R decider:decider /opt/decider',
      'cat > /etc/systemd/system/strands-decider.service <<EOF',
      '[Unit]',
      'Description=strands-decider',
      'After=network-online.target',
      'Wants=network-online.target',
      '[Service]',
      'User=decider',
      'Environment=HF_HOME=/opt/decider/hf',
      `ExecStart=/opt/decider/venv/bin/strands-decider serve ${modelId} --host 0.0.0.0 --port 8000`,
      'Restart=always',
      'RestartSec=5',
      '[Install]',
      'WantedBy=multi-user.target',
      'EOF',
      'systemctl daemon-reload',
      'systemctl enable --now strands-decider',
    );

    const host = new ec2.Instance(this, 'DeciderHost', {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      instanceType: new ec2.InstanceType(instanceType),
      // deploy.sh pins the running host's AMI (-c amiId=...) so a newer DLAMI release does not replace it on redeploy.
      machineImage: ctx('amiId')
        ? ec2.MachineImage.genericLinux({ [this.region]: ctx('amiId') })
        : ec2.MachineImage.fromSsmParameter(DLAMI, { os: ec2.OperatingSystemType.LINUX }),
      securityGroup: deciderSg,
      role,
      userData,
      requireImdsv2: true,
      associatePublicIpAddress: true,
      blockDevices: [{ deviceName: '/dev/sda1', volume: ec2.BlockDeviceVolume.ebs(100, { volumeType: ec2.EbsDeviceVolumeType.GP3, encrypted: true }) }],
    });
    cdk.Tags.of(host).add('Name', `${this.stackName}-decider`);

    const guardLogs = new logs.LogGroup(this, 'GuardFnLogs', { retention: logs.RetentionDays.ONE_MONTH, removalPolicy: cdk.RemovalPolicy.DESTROY });
    const fn = new lambda.Function(this, 'GuardFn', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'lambda_handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'guard'), { exclude: ['__pycache__', '*.pyc'] }),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [lambdaSg],
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
      environment: { DECIDER_URL: `http://${host.instancePrivateIp}:8000`, POLICY_BUCKET: policyBucket.bucketName, POLICY_KEY: 'policy.json' },
      logGroup: guardLogs,
    });
    policyBucket.grantRead(fn);

    // Attach this to the IAM users/roles your developers use for Bedrock.
    const invokePolicy = new iam.ManagedPolicy(this, 'InvokeGuardPolicy', {
      description: 'Allows coding-agent hooks to call the decider guard',
      statements: [new iam.PolicyStatement({ actions: ['lambda:InvokeFunction'], resources: [fn.functionArn] })],
    });

    if (this.node.tryGetContext('console') !== 'false' && this.node.tryGetContext('console') !== false) {
      this.adminConsole(fn, guardLogs, policyBucket, host);
    }

    new cdk.CfnOutput(this, 'GuardFunctionName', { value: fn.functionName });
    new cdk.CfnOutput(this, 'GuardFunctionArn', { value: fn.functionArn });
    new cdk.CfnOutput(this, 'InvokePolicyArn', { value: invokePolicy.managedPolicyArn });
    new cdk.CfnOutput(this, 'DeciderInstanceId', { value: host.instanceId });
    new cdk.CfnOutput(this, 'Region', { value: this.region });
  }

  /**
   * Policy console: S3 + CloudFront static site, Cognito login, HTTP API -> admin Lambda.
   * Adds exactly one IAM role (the admin Lambda's). The site files are uploaded by `ctl.sh publish-console`.
   */
  private adminConsole(guardFn: lambda.Function, guardLogs: logs.LogGroup, policyBucket: s3.Bucket, host: ec2.Instance) {
    const site = new s3.Bucket(this, 'ConsoleSite', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, enforceSSL: true, encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    const dist = new cloudfront.Distribution(this, 'ConsoleCdn', {
      defaultRootObject: 'index.html',
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(site),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        responseHeadersPolicy: cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
      },
    });
    const consoleUrl = `https://${dist.distributionDomainName}/`;

    const pool = new cognito.UserPool(this, 'Admins', {
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      passwordPolicy: { minLength: 12, requireSymbols: false },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      userInvitation: {
        emailSubject: 'PII 가드 정책 관리 콘솔 초대',
        emailBody: `PII 가드 정책 관리 콘솔 계정이 만들어졌습니다.<br>주소: ${consoleUrl}<br>아이디: {username}<br>임시 비밀번호: {####}<br>처음 로그인할 때 새 비밀번호를 정합니다.`,
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    const domain = pool.addDomain('Login', { cognitoDomain: { domainPrefix: `decider-guard-${this.account}` } });
    const client = pool.addClient('Console', {
      generateSecret: false,
      authFlows: { userSrp: true },
      preventUserExistenceErrors: true,
      oAuth: { flows: { authorizationCodeGrant: true }, scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
               callbackUrls: [consoleUrl], logoutUrls: [consoleUrl] },
    });

    // handler.py + guard_core.py in one asset, copied without Docker; hashed on the output so engine changes redeploy.
    const adminCode = lambda.Code.fromAsset(path.join(ROOT, 'admin', 'api'), {
      assetHashType: cdk.AssetHashType.OUTPUT,
      bundling: {
        image: cdk.DockerImage.fromRegistry('public.ecr.aws/docker/library/busybox'),
        local: {
          tryBundle(outDir: string) {
            const fs = require('fs');
            const api = path.join(ROOT, 'admin', 'api');
            for (const f of fs.readdirSync(api).filter((n: string) => n.endsWith('.py'))) fs.copyFileSync(path.join(api, f), path.join(outDir, f));
            fs.copyFileSync(path.join(ROOT, 'guard', 'guard_core.py'), path.join(outDir, 'guard_core.py'));
            return true;
          },
        },
      },
    });
    // Monitoring and alerts. None of this adds an IAM role: SNS, metric filters and an EventBridge rule
    // targeting a Lambda need none. The alarms themselves are created by the admin Lambda (Alerts tab).
    const namespace = 'DeciderGuard';
    const alarmPrefix = `${this.stackName}-`;
    const topic = new sns.Topic(this, 'Alerts', { displayName: 'DeciderGuard alerts' });
    const adminLogs = new logs.LogGroup(this, 'AdminFnLogs', { retention: logs.RetentionDays.ONE_MONTH, removalPolicy: cdk.RemovalPolicy.DESTROY });
    for (const [name, decision] of [['Blocks', 'block'], ['Asks', 'ask'], ['Checks', '*']] as const) {
      new logs.MetricFilter(this, `${name}Metric`, {
        logGroup: guardLogs, metricNamespace: namespace, metricName: name, metricValue: '1', defaultValue: 0,
        filterPattern: decision === '*' ? logs.FilterPattern.exists('$.decision') : logs.FilterPattern.stringValue('$.decision', '=', decision),
      });
    }

    const adminFn = new lambda.Function(this, 'AdminFn', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.handler',
      code: adminCode,
      timeout: cdk.Duration.seconds(29),
      memorySize: 256,
      environment: {
        POLICY_BUCKET: policyBucket.bucketName, POLICY_KEY: 'policy.json', GUARD_FUNCTION: guardFn.functionName,
        GUARD_LOG_GROUP: guardLogs.logGroupName, ADMIN_LOG_GROUP: adminLogs.logGroupName, GUARD_INSTANCE_ID: host.instanceId,
        ALERTS_TOPIC: topic.topicArn, ALARM_PREFIX: alarmPrefix, METRIC_NAMESPACE: namespace,
      },
      logGroup: adminLogs,
    });
    policyBucket.grantReadWrite(adminFn);
    guardFn.grantInvoke(adminFn);
    adminFn.addToRolePolicy(new iam.PolicyStatement({ actions: ['logs:StartQuery'], resources: [guardLogs.logGroupArn, adminLogs.logGroupArn] }));
    adminFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['sns:Subscribe', 'sns:Unsubscribe', 'sns:ListSubscriptionsByTopic', 'sns:Publish'], resources: [topic.topicArn] }));
    adminFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['cloudwatch:PutMetricAlarm', 'cloudwatch:DeleteAlarms'],
      resources: [`arn:${this.partition}:cloudwatch:${this.region}:${this.account}:alarm:${alarmPrefix}*`] }));
    adminFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['cloudwatch:DescribeAlarms', 'cloudwatch:GetMetricData', 'ec2:DescribeInstances'], resources: ['*'] }));
    adminFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['cloudwatch:PutMetricData'], resources: ['*'], conditions: { StringEquals: { 'cloudwatch:namespace': namespace } } }));
    // Health check every 5 minutes -> GuardHealthy metric (watched by the "guard down" alarm).
    new events.Rule(this, 'HealthCheck', {
      schedule: events.Schedule.rate(cdk.Duration.minutes(5)),
      targets: [new targets.LambdaFunction(adminFn, { event: events.RuleTargetInput.fromObject({ health_check: true }) })],
    });
    adminFn.addToRolePolicy(new iam.PolicyStatement({ actions: ['logs:GetQueryResults'], resources: ['*'] }));

    const api = new apigw.HttpApi(this, 'AdminApi', {
      corsPreflight: {
        allowOrigins: [`https://${dist.distributionDomainName}`],
        allowMethods: [apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.PUT, apigw.CorsHttpMethod.POST],
        allowHeaders: ['authorization', 'content-type', 'x-lang'],
        maxAge: cdk.Duration.hours(1),
      },
    });
    const authorizer = new HttpUserPoolAuthorizer('AdminAuth', pool, { userPoolClients: [client] });
    const integration = new HttpLambdaIntegration('AdminIntegration', adminFn);
    const routes: [string, apigw.HttpMethod][] = [
      ['/api/policy', apigw.HttpMethod.GET], ['/api/policy', apigw.HttpMethod.PUT], ['/api/test', apigw.HttpMethod.POST],
      ['/api/history', apigw.HttpMethod.GET], ['/api/history/{version}', apigw.HttpMethod.GET], ['/api/stats', apigw.HttpMethod.GET],
    ];
    for (const [p, m] of routes) api.addRoutes({ path: p, methods: [m], integration, authorizer });


    new cdk.CfnOutput(this, 'AdminUrl', { value: consoleUrl });
    new cdk.CfnOutput(this, 'ConsoleBucketName', { value: site.bucketName });
    new cdk.CfnOutput(this, 'ConsoleDistributionId', { value: dist.distributionId });
    new cdk.CfnOutput(this, 'ConsoleApiUrl', { value: api.apiEndpoint });
    new cdk.CfnOutput(this, 'ConsoleLoginDomain', { value: domain.baseUrl() });
    new cdk.CfnOutput(this, 'ConsoleClientId', { value: client.userPoolClientId });
    new cdk.CfnOutput(this, 'AdminUserPoolId', { value: pool.userPoolId });
    new cdk.CfnOutput(this, 'PolicyBucketName', { value: policyBucket.bucketName });
    new cdk.CfnOutput(this, 'AlertsTopicArn', { value: topic.topicArn });
    new cdk.CfnOutput(this, 'AlarmPrefix', { value: alarmPrefix });
  }
}
