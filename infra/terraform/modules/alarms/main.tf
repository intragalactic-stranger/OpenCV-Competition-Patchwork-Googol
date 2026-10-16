# Failure alarms: any failed pipeline or approval execution, or any failed Batch job, emails the owner.

variable "name" { type = string }
variable "alert_emails" { type = list(string) }
variable "state_machine_arns" { type = map(string) }
variable "job_queue_name" { type = string }

resource "aws_sns_topic" "alerts" {
  name = "${var.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  for_each  = toset(var.alert_emails)
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_cloudwatch_metric_alarm" "sfn_failed" {
  for_each            = var.state_machine_arns
  alarm_name          = "${var.name}-${each.key}-failed"
  alarm_description   = "A ${each.key} Step Functions execution failed, timed out or was aborted"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = each.value }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# Batch publishes job state changes to EventBridge; a FAILED job (after its retries) notifies the topic.
resource "aws_cloudwatch_event_rule" "batch_failed" {
  name        = "${var.name}-batch-job-failed"
  description = "A Patchwork Batch job failed after its retries"
  event_pattern = jsonencode({
    source      = ["aws.batch"]
    detail-type = ["Batch Job State Change"]
    detail      = { status = ["FAILED"], jobQueue = [{ suffix = var.job_queue_name }] }
  })
}

resource "aws_cloudwatch_event_target" "batch_failed" {
  rule = aws_cloudwatch_event_rule.batch_failed.name
  arn  = aws_sns_topic.alerts.arn
  input_transformer {
    input_paths    = { job = "$.detail.jobName", reason = "$.detail.statusReason" }
    input_template = "\"Patchwork Batch job <job> failed: <reason>\""
  }
}

data "aws_iam_policy_document" "topic" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com", "cloudwatch.amazonaws.com"]
    }
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.topic.json
}

output "topic_arn" { value = aws_sns_topic.alerts.arn }

# ---------------------------------------------------------------- operations dashboard (console, agent, models, DB)
variable "console_api_id" {
  type    = string
  default = ""
}
variable "console_lambda" {
  type    = string
  default = ""
}
variable "agent_runtime_arn" {
  type    = string
  default = ""
}
variable "db_cluster_id" { type = string }

data "aws_region" "current" {}

locals {
  r = data.aws_region.current.region
}

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${var.name}-operations"
  dashboard_body = jsonencode({
    widgets = [
      { type = "text", x = 0, y = 0, width = 24, height = 2, properties = { markdown = "## Patchwork operations\nHuman control (decisions, **override rate**), the agent on AgentCore, Amazon Nova usage, the approval console and the register. Pipeline throughput: dashboard `${var.name}-pipeline`. Alarms email the owner." } },
      { type = "metric", x = 0, y = 2, width = 8, height = 6, properties = {
        title = "Human decisions and overrides (override rate = overrides / decisions)", region = local.r, stat = "Sum", period = 86400, view = "bar",
      metrics = [["Patchwork", "Decisions", "Decision", "approve"], ["Patchwork", "Decisions", "Decision", "reject"], ["Patchwork", "Overrides", "Decision", "reject"]] } },
      { type = "metric", x = 8, y = 2, width = 8, height = 6, properties = {
        title = "Agent runs, tool calls, ungrounded IDs (must stay 0)", region = local.r, stat = "Sum", period = 3600, view = "timeSeries",
      metrics = [["Patchwork", "AgentRuns", "Runtime", "agentcore"], [".", "ToolCalls", ".", "."], [".", "UngroundedIds", ".", "."], ["Patchwork", "AgentRuns", "Runtime", "local"]] } },
      { type = "metric", x = 16, y = 2, width = 8, height = 6, properties = {
        title = "AgentCore runtime: invocations, errors, latency", region = local.r, period = 3600, view = "timeSeries",
        metrics = [["AWS/Bedrock-AgentCore", "Invocations", "Resource", var.agent_runtime_arn, "Operation", "InvokeAgentRuntime", "Name", "patchwork_ward_assistant::DEFAULT", { stat = "Sum" }],
          [".", "SystemErrors", ".", ".", ".", ".", ".", ".", { stat = "Sum" }], [".", "UserErrors", ".", ".", ".", ".", ".", ".", { stat = "Sum" }],
      [".", "Latency", ".", ".", ".", ".", ".", ".", { stat = "Average", yAxis = "right" }]] } },
      { type = "metric", x = 0, y = 8, width = 8, height = 6, properties = {
        title = "Amazon Nova tokens (Bedrock)", region = local.r, stat = "Sum", period = 3600, view = "timeSeries",
      metrics = [["AWS/Bedrock", "InputTokenCount", "ModelId", "apac.amazon.nova-pro-v1:0"], [".", "OutputTokenCount", ".", "."], [".", "InputTokenCount", "ModelId", "apac.amazon.nova-lite-v1:0"]] } },
      { type = "metric", x = 8, y = 8, width = 8, height = 6, properties = {
        title = "Approval console API: requests, 4xx, 5xx, latency", region = local.r, period = 3600, view = "timeSeries",
        metrics = [["AWS/ApiGateway", "Count", "ApiId", var.console_api_id, { stat = "Sum" }], [".", "4xx", ".", ".", { stat = "Sum" }], [".", "5xx", ".", ".", { stat = "Sum" }],
      [".", "Latency", ".", ".", { stat = "p90", yAxis = "right" }]] } },
      { type = "metric", x = 16, y = 8, width = 8, height = 6, properties = {
        title = "Console Lambda and approval workflow", region = local.r, stat = "Sum", period = 3600, view = "timeSeries",
        metrics = [["AWS/Lambda", "Invocations", "FunctionName", var.console_lambda], [".", "Errors", ".", "."],
      ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", var.state_machine_arns["approval"]], [".", "ExecutionsFailed", ".", "."], [".", "ExecutionsTimedOut", ".", "."]] } },
      { type = "metric", x = 0, y = 14, width = 12, height = 6, properties = {
        title = "Register (Aurora Serverless v2): capacity in ACU, 0 = paused", region = local.r, stat = "Average", period = 300, view = "timeSeries",
      metrics = [["AWS/RDS", "ServerlessDatabaseCapacity", "DBClusterIdentifier", var.db_cluster_id]] } },
      { type = "alarm", x = 12, y = 14, width = 12, height = 6, properties = {
      title = "Alarms", alarms = [for a in aws_cloudwatch_metric_alarm.sfn_failed : a.arn] } },
    ]
  })
}
