variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "project" {
  type    = string
  default = "metaphor-generator"
}

variable "image_tag" {
  description = "ECRにpushしたイメージのタグ（例：gitのコミットハッシュ）"
  type        = string
}

variable "allowed_cidr" {
  description = "ALBにアクセスできる送信元。確認中は自分のIP（x.x.x.x/32）に絞ると安心"
  type        = string
  default     = "0.0.0.0/0"
}

variable "desired_count" {
  description = "動かすタスクの数"
  type        = number
  default     = 1
}

variable "bedrock_inference_profile_id" {
  description = "日本国内の推論プロファイル"
  type        = string
  default     = "jp.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "bedrock_foundation_model_id" {
  description = "推論プロファイルの裏で使われる基盤モデル"
  type        = string
  default     = "anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "bedrock_regions" {
  description = "jp 推論プロファイルが推論を振り分けるリージョン（東京・大阪）"
  type        = list(string)
  default     = ["ap-northeast-1", "ap-northeast-3"]
}

variable "app_url" {
  description = "Xでの共有文に入れるURL（空なら入れない）"
  type        = string
  default     = ""
}
