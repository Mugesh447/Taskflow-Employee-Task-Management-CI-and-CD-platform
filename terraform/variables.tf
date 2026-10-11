variable "app_name" {
  description = "Lowercase name used for TaskFlow AWS resources."
  type        = string
  default     = "taskflow"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.app_name))
    error_message = "app_name must be 3-20 lowercase letters, digits, or hyphens and start with a letter."
  }
}

variable "aws_region" {
  description = "AWS region for the TaskFlow environment."
  type        = string
  default     = "ap-south-1"
}

variable "vpc_cidr" {
  description = "IPv4 range for the TaskFlow VPC. It must be a /16 to fit the generated subnets."
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr)) && tonumber(split("/", var.vpc_cidr)[1]) == 16
    error_message = "vpc_cidr must be a valid IPv4 /16 network."
  }
}

variable "certificate_arn" {
  description = "ARN of an ACM certificate in aws_region for the HTTPS load balancer."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:acm:[a-z0-9-]+:[0-9]{12}:certificate/.+$", var.certificate_arn))
    error_message = "certificate_arn must be an ACM certificate ARN in the selected AWS region."
  }
}

variable "app_domain" {
  description = "DNS name covered by the ACM certificate and used to access TaskFlow."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$", var.app_domain))
    error_message = "app_domain must be a valid fully qualified DNS name."
  }
}

variable "hosted_zone_id" {
  description = "Optional Route 53 hosted zone ID; leave empty to manage the DNS alias outside AWS."
  type        = string
  default     = ""
}

variable "github_repository" {
  description = "GitHub repository allowed to deploy, in owner/repository format."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/repository format."
  }
}

variable "github_branch" {
  description = "Git branch allowed to assume the GitHub Actions deployment role."
  type        = string
  default     = "main"
}

variable "database_name" {
  description = "Initial PostgreSQL database name."
  type        = string
  default     = "taskflow"
}

variable "database_username" {
  description = "RDS master username; AWS Secrets Manager generates and manages its password."
  type        = string
  default     = "taskflow_admin"
}

variable "database_instance_class" {
  description = "RDS PostgreSQL instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "database_multi_az" {
  description = "Enable a standby RDS instance in another availability zone."
  type        = bool
  default     = false
}

variable "desired_count" {
  description = "Number of TaskFlow tasks to run after deployment."
  type        = number
  default     = 2

  validation {
    condition     = var.desired_count >= 0 && var.desired_count <= 10
    error_message = "desired_count must be between 0 and 10."
  }
}

variable "task_cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 1024
}

variable "image_tag" {
  description = "Immutable image tag to deploy. Use bootstrap for the first infrastructure apply."
  type        = string
  default     = "bootstrap"
}

variable "alert_email" {
  description = "Optional email address for CloudWatch alarm and backup notifications."
  type        = string
  default     = ""
}
