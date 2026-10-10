#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { DeciderGuardStack } from '../lib/guard-stack';

const app = new cdk.App();
new DeciderGuardStack(app, app.node.tryGetContext('stackName') ?? 'DeciderGuard', {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION },
  description: 'strands-decider PII guard for coding agents (Claude Code / Kiro / Codex hooks)',
});
