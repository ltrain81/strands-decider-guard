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
import { HttpJwtAuthorizer, HttpUserPoolAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';

const ROOT = path.join(__dirname, '..', '..');
// Loopback redirect for the hook's browser sign-in (client/decider_guard.py login); must match CALLBACK_PORT there.
const DEV_CALLBACK = 'http://localhost:8723/callback';
const DLAMI = '/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id';

export class DeciderGuardStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    const ctx = (k: string) => this.node.tryGetContext(k) as string;
    const instanceType = ctx('instanceType');
    const modelId = ctx('modelId');
    const deciderRef = ctx('deciderRef');

    // network=nat (default): the decider host sits in a private subnet with no public IP; it reaches PyPI, GitHub and
    //   Hugging Face (first boot) and SSM through one NAT Gateway. network=public: the host sits in a public subnet with
    //   a public IP and no NAT (cheaper, for demos). Either way the only inbound rule is the guard Lambda on port 8000,
    //   and the Lambda sits in isolated subnets talking to the host's private IP. The private group is appended last so
    //   switching modes keeps the existing subnets' CIDRs.
    const network = (this.node.tryGetContext('network') as string | undefined) ?? 'nat';
    if (!['nat', 'public'].includes(network)) throw new Error(`network must be nat or public, got ${network}`);
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: network === 'nat' ? 1 : 0,
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'isolated', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
        ...(network === 'nat' ? [{ name: 'private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 }] : []),
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

    // Spot (about half the on-demand price): a persistent request that stops on interruption. While the host is away the
    // guard falls back to regex-only checks, so an interruption degrades quality instead of blocking developers.
    const spot = ['true', true].includes(this.node.tryGetContext('spot'));
    const host = new ec2.Instance(this, 'DeciderHost', {
      vpc,
      vpcSubnets: { subnetType: network === 'nat' ? ec2.SubnetType.PRIVATE_WITH_EGRESS : ec2.SubnetType.PUBLIC },
      instanceType: new ec2.InstanceType(instanceType),
      // deploy.sh pins the running host's AMI (-c amiId=...) so a newer DLAMI release does not replace it on redeploy.
      machineImage: ctx('amiId')
        ? ec2.MachineImage.genericLinux({ [this.region]: ctx('amiId') })
        : ec2.MachineImage.fromSsmParameter(DLAMI, { os: ec2.OperatingSystemType.LINUX }),
      securityGroup: deciderSg,
      role,
      userData,
      requireImdsv2: !spot,   // with Spot, IMDSv2 is set on the launch template below
      associatePublicIpAddress: network === 'public',
      blockDevices: [{ deviceName: '/dev/sda1', volume: ec2.BlockDeviceVolume.ebs(100, { volumeType: ec2.EbsDeviceVolumeType.GP3, encrypted: true }) }],
    });
    cdk.Tags.of(host).add('Name', `${this.stackName}-decider`);
    if (spot) {
      const lt = new ec2.LaunchTemplate(this, 'DeciderSpot', {
        requireImdsv2: true,
        spotOptions: { requestType: ec2.SpotRequestType.PERSISTENT, interruptionBehavior: ec2.SpotInstanceInterruption.STOP },
      });
      (host.node.defaultChild as ec2.CfnInstance).launchTemplate = { launchTemplateId: lt.launchTemplateId, version: lt.latestVersionNumber };
    }

    // Opt-in evidence (policy "evidence": blocked | all): checked text kept for admins, deleted after evidenceDays.
    const evidenceDays = Number(this.node.tryGetContext('evidenceDays') ?? 30);
    const evidenceBucket = new s3.Bucket(this, 'EvidenceBucket', {
      enforceSSL: true, blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY, lifecycleRules: [{ expiration: cdk.Duration.days(evidenceDays) }],
    });
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
      environment: { DECIDER_URL: `http://${host.instancePrivateIp}:8000`, POLICY_BUCKET: policyBucket.bucketName, POLICY_KEY: 'policy.json',
                     EVIDENCE_BUCKET: evidenceBucket.bucketName },
      logGroup: guardLogs,
    });
    policyBucket.grantRead(fn);
    evidenceBucket.grantPut(fn, 'evidence/*');

    // Attach this to the IAM users/roles your developers use for Bedrock.
    const invokePolicy = new iam.ManagedPolicy(this, 'InvokeGuardPolicy', {
      description: 'Allows coding-agent hooks to call the decider guard',
      statements: [new iam.PolicyStatement({ actions: ['lambda:InvokeFunction'], resources: [fn.functionArn] })],
    });

    // One HTTP API: POST /guard/check for signed-in hooks (always), /api/* for the policy console (when enabled).
    // Construct ids are unchanged from when both lived in adminConsole(), so existing deployments keep their URLs.
    const consoleOn = this.node.tryGetContext('console') !== 'false' && this.node.tryGetContext('console') !== false;
    const cdn = consoleOn ? this.consoleSite() : undefined;
    const api = new apigw.HttpApi(this, 'AdminApi', cdn ? {
      corsPreflight: {
        allowOrigins: [`https://${cdn.dist.distributionDomainName}`],
        allowMethods: [apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.PUT, apigw.CorsHttpMethod.POST],
        allowHeaders: ['authorization', 'content-type', 'x-lang'],
        maxAge: cdk.Duration.hours(1),
      },
    } : {});
    const dev = this.developerSignIn(fn, api, cdn?.url);
    if (cdn) this.adminConsole(fn, guardLogs, policyBucket, host, evidenceBucket, evidenceDays, api, cdn, dev);

    new cdk.CfnOutput(this, 'GuardFunctionName', { value: fn.functionName });
    new cdk.CfnOutput(this, 'GuardFunctionArn', { value: fn.functionArn });
    new cdk.CfnOutput(this, 'InvokePolicyArn', { value: invokePolicy.managedPolicyArn });
    new cdk.CfnOutput(this, 'DeciderInstanceId', { value: host.instanceId });
    new cdk.CfnOutput(this, 'Region', { value: this.region });
    new cdk.CfnOutput(this, 'Market', { value: spot ? 'spot' : 'on-demand' });
    new cdk.CfnOutput(this, 'Network', { value: network });
    new cdk.CfnOutput(this, 'EvidenceBucketName', { value: evidenceBucket.bucketName });
  }

  /** Console site: S3 + CloudFront. Also serves the public developer install page (install.html, dev/*). */
  private consoleSite() {
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
    return { site, dist, url: `https://${dist.distributionDomainName}/` };
  }

  /**
   * Hook sign-in (install.sh --auth jwt, the default): developers sign in in the browser and the hook sends an ID token to
   * POST /guard/check, so they need no AWS credentials and every decision is logged with the user and groups. A separate
   * user pool keeps developer logins out of the admin console; federate it with your corporate IdP (SAML/OIDC) instead of
   * inviting users. -c devIssuer=https://... -c devAudience=<client id> trusts an external OIDC IdP directly.
   * API Gateway invokes the guard through a resource policy, so this adds no IAM role. Independent of the console.
   */
  private developerSignIn(guardFn: lambda.Function, api: apigw.HttpApi, consoleUrl?: string) {
    const devIssuer = this.node.tryGetContext('devIssuer') as string | undefined;
    let devAuthorizer: apigw.IHttpRouteAuthorizer;
    let out: { issuer?: string; clientId: string; pool?: cognito.UserPool; authorizeUrl?: string; tokenUrl?: string };
    if (devIssuer) {
      const audience = this.node.tryGetContext('devAudience') as string | undefined;
      if (!audience) throw new Error('devIssuer needs devAudience (the OIDC client id the hooks sign in with)');
      devAuthorizer = new HttpJwtAuthorizer('DevAuth', devIssuer, { jwtAudience: [audience] });
      new cdk.CfnOutput(this, 'DevIssuer', { value: devIssuer });
      new cdk.CfnOutput(this, 'DevClientId', { value: audience });
      out = { issuer: devIssuer, clientId: audience };
    } else {
      const install = consoleUrl
        ? { en: `Install it as shown on ${consoleUrl}install.html ; the installer`, ko: `${consoleUrl}install.html 안내대로 설치하면` }
        : { en: 'Your admin will send you the install command; it', ko: '관리자가 보내 주는 설치 명령을 실행하면' };
      const devPool = new cognito.UserPool(this, 'Developers', {
        selfSignUpEnabled: false,
        signInAliases: { email: true },
        autoVerify: { email: true },
        passwordPolicy: { minLength: 12, requireSymbols: false },
        accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
        userInvitation: {
          emailSubject: 'PII guard sign-in / PII 가드 로그인',
          emailBody: `You are invited to the PII guard for coding agents. ${install.en} opens a sign-in page where you use this temporary password and then choose your own.<br>`
            + `PII 가드에 초대되었습니다. ${install.ko} 로그인 페이지가 열립니다. 아래 임시 비밀번호로 로그인한 뒤 새 비밀번호를 정하세요.<br><br>`
            + 'ID: {username}<br>Temporary password / 임시 비밀번호: {####}',
        },
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      });
      const devDomain = devPool.addDomain('DevLogin', { cognitoDomain: { domainPrefix: `decider-guard-dev-${this.account}` } });
      const devClient = devPool.addClient('Hooks', {
        generateSecret: false,
        preventUserExistenceErrors: true,
        oAuth: { flows: { authorizationCodeGrant: true }, scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
                 callbackUrls: [DEV_CALLBACK], logoutUrls: [DEV_CALLBACK] },
        idTokenValidity: cdk.Duration.hours(1),
        accessTokenValidity: cdk.Duration.hours(1),
        refreshTokenValidity: cdk.Duration.days(Number(this.node.tryGetContext('devSessionDays') ?? 30)),
      });
      devAuthorizer = new HttpUserPoolAuthorizer('DevAuth', devPool, { userPoolClients: [devClient] });
      out = { clientId: devClient.userPoolClientId, pool: devPool,
              authorizeUrl: `${devDomain.baseUrl()}/oauth2/authorize`, tokenUrl: `${devDomain.baseUrl()}/oauth2/token` };
      new cdk.CfnOutput(this, 'DevUserPoolId', { value: devPool.userPoolId });
      new cdk.CfnOutput(this, 'DevClientId', { value: out.clientId });
      new cdk.CfnOutput(this, 'DevAuthorizeUrl', { value: out.authorizeUrl! });
      new cdk.CfnOutput(this, 'DevTokenUrl', { value: out.tokenUrl! });
    }
    api.addRoutes({ path: '/guard/check', methods: [apigw.HttpMethod.POST], authorizer: devAuthorizer,
                    integration: new HttpLambdaIntegration('GuardIntegration', guardFn) });
    const guardApiUrl = `${api.apiEndpoint}/guard/check`;
    new cdk.CfnOutput(this, 'GuardApiUrl', { value: guardApiUrl });
    return { ...out, guardApiUrl };
  }

  /**
   * Policy console: Cognito admin login, /api/* on the HTTP API -> admin Lambda, monitoring and the Developers tab.
   * Adds exactly one IAM role (the admin Lambda's). The site files are uploaded by `ctl.sh publish-console`.
   */
  private adminConsole(guardFn: lambda.Function, guardLogs: logs.LogGroup, policyBucket: s3.Bucket, host: ec2.Instance,
                       evidenceBucket: s3.Bucket, evidenceDays: number, api: apigw.HttpApi,
                       cdn: { site: s3.Bucket; dist: cloudfront.Distribution; url: string },
                       dev: ReturnType<DeciderGuardStack['developerSignIn']>) {
    const { site, dist } = cdn;
    const consoleUrl = cdn.url;

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

    // Optional host schedule, e.g. -c schedule="MON-FRI 08:00-20:00" -c scheduleUtcOffset=9 (outside it the host is stopped
    // and the guard checks with regexes only). Implemented as two EventBridge rules -> admin Lambda: no extra IAM role.
    const schedule = (this.node.tryGetContext('schedule') as string | undefined) || undefined;
    const utcOffset = Number(this.node.tryGetContext('scheduleUtcOffset') ?? 9);

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
        SCHEDULE: schedule ?? '', SCHEDULE_UTC_OFFSET: String(utcOffset),
        EVIDENCE_BUCKET: evidenceBucket.bucketName, EVIDENCE_DAYS: String(evidenceDays),
      },
      logGroup: adminLogs,
    });
    policyBucket.grantReadWrite(adminFn);
    evidenceBucket.grantRead(adminFn, 'evidence/*');
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
    if (schedule) {
      const m = /^([A-Z]{3})-([A-Z]{3}) (\d{2}):(\d{2})-(\d{2}):(\d{2})$/.exec(schedule);
      if (!m) throw new Error(`schedule must look like "MON-FRI 08:00-20:00", got "${schedule}"`);
      const DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];
      const days = DAYS.slice(DAYS.indexOf(m[1]), DAYS.indexOf(m[2]) + 1);
      const cronAt = (h: number, min: number) => {   // local time -> UTC cron, shifting the weekdays when the hour wraps
        let utc = h - utcOffset, shift = 0;
        if (utc < 0) { utc += 24; shift = -1; } else if (utc >= 24) { utc -= 24; shift = 1; }
        const weekDay = days.map(d => DAYS[(DAYS.indexOf(d) + shift + 7) % 7]).join(',');
        return events.Schedule.cron({ minute: String(min), hour: String(Math.floor(utc)), weekDay });
      };
      for (const [name, h, min, power] of [['HostStart', +m[3], +m[4], 'start'], ['HostStop', +m[5], +m[6], 'stop']] as const) {
        new events.Rule(this, name, {
          schedule: cronAt(h, min),
          targets: [new targets.LambdaFunction(adminFn, { event: events.RuleTargetInput.fromObject({ power }) })],
        });
      }
      adminFn.addToRolePolicy(new iam.PolicyStatement({
        actions: ['ec2:StartInstances', 'ec2:StopInstances'],
        resources: [`arn:${this.partition}:ec2:${this.region}:${this.account}:instance/${host.instanceId}`] }));
    }
    new cdk.CfnOutput(this, 'Schedule', { value: schedule ? `${schedule} (UTC${utcOffset >= 0 ? '+' : ''}${utcOffset})` : 'always on' });

    // Health check every 5 minutes -> GuardHealthy metric (watched by the "guard down" alarm).
    new events.Rule(this, 'HealthCheck', {
      schedule: events.Schedule.rate(cdk.Duration.minutes(5)),
      targets: [new targets.LambdaFunction(adminFn, { event: events.RuleTargetInput.fromObject({ health_check: true }) })],
    });
    adminFn.addToRolePolicy(new iam.PolicyStatement({ actions: ['logs:GetQueryResults'], resources: ['*'] }));

    const authorizer = new HttpUserPoolAuthorizer('AdminAuth', pool, { userPoolClients: [client] });
    const integration = new HttpLambdaIntegration('AdminIntegration', adminFn);
    // One authorized catch-all route; handler.py does the routing. OPTIONS is left to the CORS preflight above.
    api.addRoutes({ path: '/api/{proxy+}', methods: [apigw.HttpMethod.GET, apigw.HttpMethod.PUT, apigw.HttpMethod.POST], integration, authorizer });

    // Developers tab: invite, disable, delete and group developers (permissions on the existing admin role, no new role).
    adminFn.addEnvironment('GUARD_API_URL', dev.guardApiUrl);
    adminFn.addEnvironment('DEV_CLIENT_ID', dev.clientId);
    if (dev.issuer) adminFn.addEnvironment('DEV_ISSUER', dev.issuer);
    if (dev.pool) {
      adminFn.addToRolePolicy(new iam.PolicyStatement({
        actions: ['cognito-idp:ListUsers', 'cognito-idp:AdminGetUser', 'cognito-idp:AdminCreateUser', 'cognito-idp:AdminDisableUser',
                  'cognito-idp:AdminEnableUser', 'cognito-idp:AdminDeleteUser', 'cognito-idp:AdminUserGlobalSignOut',
                  'cognito-idp:ListGroups', 'cognito-idp:CreateGroup', 'cognito-idp:DeleteGroup', 'cognito-idp:ListUsersInGroup',
                  'cognito-idp:AdminListGroupsForUser', 'cognito-idp:AdminAddUserToGroup', 'cognito-idp:AdminRemoveUserFromGroup'],
        resources: [dev.pool.userPoolArn] }));
      adminFn.addEnvironment('DEV_POOL_ID', dev.pool.userPoolId);
      adminFn.addEnvironment('DEV_AUTHORIZE_URL', dev.authorizeUrl!);
      adminFn.addEnvironment('DEV_TOKEN_URL', dev.tokenUrl!);
    }

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
