# ロールは2つに分ける。
#   実行ロール：ECSがタスクを起動するために使う（イメージの取得・ログの書き込み）
#   タスクロール：アプリ自身が使う（Bedrock・DynamoDB）。APIキーの代わりになるもの

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    # 自分のアカウントのECSからだけ引き受けられる
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

# ---------- 実行ロール ----------

resource "aws_iam_role" "execution" {
  name               = "${var.project}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "execution" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"] # リソースを絞れないAPI
    resources = ["*"]
  }
  statement {
    sid       = "PullThisRepoOnly"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [data.aws_ecr_repository.app.arn]
  }
  statement {
    sid       = "WriteThisLogGroupOnly"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${data.aws_cloudwatch_log_group.app.arn}:*"]
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "pull-image-and-write-logs"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# ---------- タスクロール ----------

resource "aws_iam_role" "task" {
  name               = "${var.project}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

locals {
  inference_profile_arn = "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/${var.bedrock_inference_profile_id}"
}

data "aws_iam_policy_document" "task" {
  statement {
    sid = "TimelineReadWriteDelete"
    # 使う操作だけ。Scan や UpdateItem、テーブル自体の変更は許可しない
    actions   = ["dynamodb:Query", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [data.aws_dynamodb_table.timeline.arn]
  }

  statement {
    sid       = "InvokeJapanInferenceProfile"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.inference_profile_arn]
  }

  # 基盤モデルは「jp 推論プロファイル経由」のときだけ呼べる（直接・他リージョン経由は不可）
  statement {
    sid     = "FoundationModelViaJapanProfileOnly"
    actions = ["bedrock:InvokeModel"]
    resources = [
      for r in var.bedrock_regions : "arn:aws:bedrock:${r}::foundation-model/${var.bedrock_foundation_model_id}"
    ]
    condition {
      test     = "StringEquals"
      variable = "bedrock:InferenceProfileArn"
      values   = [local.inference_profile_arn]
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "timeline-and-bedrock"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}
