variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "environment" {
  type    = string
  default = "portfolio"
}
variable "cluster_name" {
  type    = string
  default = "pipefoundry"
}
variable "cluster_version" {
  description = "Confirm EKS standard support and regional availability before apply."
  type        = string
  default     = "1.34"
}
variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}
variable "availability_zones" {
  type    = list(string)
  default = ["ap-south-1a", "ap-south-1b"]
  validation {
    condition     = length(var.availability_zones) == 2
    error_message = "Supply exactly two availability zones in the chosen region."
  }
}
variable "cluster_admin_principal_arn" {
  description = "An existing administrator IAM role, preferably assumed through OIDC/SSO."
  type        = string
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/.+$", var.cluster_admin_principal_arn))
    error_message = "Supply an IAM role ARN; account root and user ARNs are forbidden."
  }
}
