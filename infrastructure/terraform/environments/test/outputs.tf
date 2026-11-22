output "base_url" {
  value = module.host.base_url
}

output "public_ip" {
  value = aws_eip.host.public_ip
}

output "ssm_session_command" {
  value = module.host.ssm_session_command
}

output "cognito" {
  value = {
    user_pool_id  = module.cognito.user_pool_id
    hosted_domain = module.cognito.hosted_domain
    client_ids    = module.cognito.client_ids
  }
}
