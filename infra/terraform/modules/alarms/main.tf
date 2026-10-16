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
