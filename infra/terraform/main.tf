module "network" {
  source             = "./modules/network"
  name               = var.cluster_name
  cidr               = var.vpc_cidr
  availability_zones = var.availability_zones
}

module "eks" {
  source                      = "./modules/eks"
  name                        = var.cluster_name
  cluster_version             = var.cluster_version
  vpc_id                      = module.network.vpc_id
  private_subnet_ids          = module.network.private_subnet_ids
  cluster_admin_principal_arn = var.cluster_admin_principal_arn
}

output "cluster_name" { value = module.eks.cluster_name }
output "private_endpoint" { value = module.eks.endpoint }
output "vpc_id" { value = module.network.vpc_id }
