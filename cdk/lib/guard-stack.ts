import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';

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
      machineImage: ec2.MachineImage.fromSsmParameter(DLAMI, { os: ec2.OperatingSystemType.LINUX }),
      securityGroup: deciderSg,
      role,
      userData,
      requireImdsv2: true,
      associatePublicIpAddress: true,
      blockDevices: [{ deviceName: '/dev/sda1', volume: ec2.BlockDeviceVolume.ebs(100, { volumeType: ec2.EbsDeviceVolumeType.GP3, encrypted: true }) }],
    });
    cdk.Tags.of(host).add('Name', `${this.stackName}-decider`);

    const fn = new lambda.Function(this, 'GuardFn', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'lambda_handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'guard'), { exclude: ['__pycache__', '*.pyc'] }),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [lambdaSg],
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
      environment: { DECIDER_URL: `http://${host.instancePrivateIp}:8000` },
      logGroup: new logs.LogGroup(this, 'GuardFnLogs', { retention: logs.RetentionDays.ONE_MONTH, removalPolicy: cdk.RemovalPolicy.DESTROY }),
    });

    // Attach this to the IAM users/roles your developers use for Bedrock.
    const invokePolicy = new iam.ManagedPolicy(this, 'InvokeGuardPolicy', {
      description: 'Allows coding-agent hooks to call the decider guard',
      statements: [new iam.PolicyStatement({ actions: ['lambda:InvokeFunction'], resources: [fn.functionArn] })],
    });

    new cdk.CfnOutput(this, 'GuardFunctionName', { value: fn.functionName });
    new cdk.CfnOutput(this, 'GuardFunctionArn', { value: fn.functionArn });
    new cdk.CfnOutput(this, 'InvokePolicyArn', { value: invokePolicy.managedPolicyArn });
    new cdk.CfnOutput(this, 'DeciderInstanceId', { value: host.instanceId });
    new cdk.CfnOutput(this, 'Region', { value: this.region });
  }
}
