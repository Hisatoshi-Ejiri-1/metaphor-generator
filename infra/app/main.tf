# 使うときだけ立てる層：VPC・ALB・ECS。
# 時間課金のもの（ALB・Fargate・パブリックIP）はすべてここにあり、
# 確認が終わったら terraform destroy で消す。データは infra/base 側にあるので消えない。

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
      Layer     = "app"
    }
  }
}

data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

# base 層で作ったものは、名前で参照する（state を共有しないので、層どうしが疎結合になる）
data "aws_dynamodb_table" "timeline" {
  name = "${var.project}-timeline"
}

data "aws_ecr_repository" "app" {
  name = var.project
}

data "aws_cloudwatch_log_group" "app" {
  name = "/ecs/${var.project}"
}

locals {
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)
  account_id = data.aws_caller_identity.current.account_id
}
