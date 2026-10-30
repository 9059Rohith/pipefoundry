# AWS infrastructure

This root composes local `network` and `eks` modules. It creates billable resources
only after an explicit operator apply. `terraform validate` checks configuration,
not regional IAM permissions, quotas, available EKS versions, addons or a live
cluster.

```sh
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
# Configure a protected remote backend, authenticate with SSO/OIDC, then:
terraform plan -var='cluster_admin_principal_arn=arn:aws:iam::123456789012:role/YourEKSAdmin'
```

Use a real role/account and verify region/AZs and EKS version support. The API is
private-only; a VPC-connected operator/runner is required. The caller must be
authorized to create IAM roles, pass roles and configure EKS/KMS/network resources.
The default creates two NAT gateways and two t3.large worker nodes, plus EKS and
logs. Cost and quota review precede apply. Do not commit plan/state files.

EBS/EFS CSI drivers, storage classes, database services, external DNS/ingress/TLS,
workload secrets, artifact registries and application-specific IAM are explicit
operator integration tasks. A private EKS network alone does not configure those
resources. The Helm application chart should run only after these prerequisites
and the workload image are ready.

The OIDC provider relies on IAM's automatic intermediate CA thumbprint retrieval
at creation. Compare the resulting thumbprint with the issuer certificate during
cloud acceptance; see [AWS's OIDC guidance](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc_verify-thumbprint.html).
This removes a separate TLS provider/read from the Terraform graph. The
[AWS provider documentation](https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/website/docs/r/iam_openid_connect_provider.html.markdown)
defines thumbprints as optional for a newly created IdP.
