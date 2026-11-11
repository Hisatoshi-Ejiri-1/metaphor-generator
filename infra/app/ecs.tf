resource "aws_ecs_cluster" "main" {
  name = var.project
  # Container Insights は有料なので使わない（必要になったら enabled にする）
  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = var.project
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256 # 0.25 vCPU（Fargate の最小）
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64" # --platform linux/amd64 でビルドしたイメージに合わせる
  }

  container_definitions = jsonencode([{
    name      = "app"
    image     = "${data.aws_ecr_repository.app.repository_url}:${var.image_tag}"
    essential = true
    portMappings = [{
      containerPort = 8501
      protocol      = "tcp"
    }]
    # 秘密情報は1つもない。すべてただの設定値
    environment = [
      { name = "AWS_REGION", value = var.region },
      { name = "TABLE_NAME", value = data.aws_dynamodb_table.timeline.name },
      { name = "BEDROCK_MODEL_ID", value = var.bedrock_inference_profile_id },
      { name = "APP_URL", value = var.app_url },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = data.aws_cloudwatch_log_group.app.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "app"
      }
    }
  }])
}

resource "aws_ecs_service" "app" {
  name            = var.project
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true # NATなしで ECR・Bedrock・DynamoDB に出ていくため
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = 8501
  }

  # 起動直後はヘルスチェックに落ちても入れ替えない
  health_check_grace_period_seconds = 60

  # 新しいイメージが起動しなければ、自動で前のバージョンに戻す
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.http]
}
