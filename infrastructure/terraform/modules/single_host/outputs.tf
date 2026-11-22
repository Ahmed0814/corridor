output "hostname" {
  value = local.hostname
}

output "base_url" {
  value = "https://${local.hostname}"
}

output "instance_id" {
  value = aws_instance.host.id
}

output "ssm_session_command" {
  value = "aws ssm start-session --region ${data.aws_region.current.region} --target ${aws_instance.host.id}"
}
