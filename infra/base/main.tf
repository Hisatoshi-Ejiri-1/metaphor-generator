# 常時残す層：データと、アプリを立て直すたびに必要になるもの。
# ほぼ無料で置いておけるものだけをここに入れる。普段 destroy するのは infra/app だけ。

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Layer     = "base"
    }
  }
}

# みんなの比喩。オンデマンド課金なので、使わない間はほぼ0円
resource "aws_dynamodb_table" "timeline" {
  name         = "${var.project}-timeline"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  # 誤って消さないための二重の鍵（AWS側の削除保護と、Terraform側の destroy 拒否）
  deletion_protection_enabled = true
  lifecycle {
    prevent_destroy = true
  }
}

# コンテナイメージ置き場。タグの上書きを禁止し、どのイメージが動いているかを一意にする
resource "aws_ecr_repository" "app" {
  name                 = var.project
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "最新5件だけ残す"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

# ログは app 層を destroy しても残るよう、こちらに置く
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.project}"
  retention_in_days = 30
}
