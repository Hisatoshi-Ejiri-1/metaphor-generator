resource "aws_lb" "main" {
  name                       = var.project
  load_balancer_type         = "application"
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  # Streamlit は WebSocket をつなぎっぱなしにするので、無通信で切れるまでの時間を長めにする
  idle_timeout = 300
}

resource "aws_lb_target_group" "app" {
  name        = var.project
  port        = 8501
  protocol    = "HTTP"
  target_type = "ip" # Fargate（awsvpc）はタスクのIPを直接登録する
  vpc_id      = aws_vpc.main.id

  # destroy や入れ替えを速くする（既定は300秒待つ）
  deregistration_delay = 30

  health_check {
    path                = "/_stcore/health" # Streamlit 組み込みのヘルスチェック
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # Streamlit はセッションをタスクのメモリに持つ。
  # タスクを2台以上にしたとき、同じ人を同じタスクに送り続けるため
  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400
    enabled         = true
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
