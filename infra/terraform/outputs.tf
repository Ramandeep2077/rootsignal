output "url" {
  description = "Dashboard + API entry point (when compute is deployed)."
  value       = var.deploy_compute ? module.services[0].url : null
}

output "ecr_repositories" {
  value = var.deploy_registry ? module.registry[0].repository_urls : {}
}

output "artifacts_bucket" {
  value = module.data.artifacts_bucket
}

output "vpc_id" {
  value = module.network.vpc_id
}
