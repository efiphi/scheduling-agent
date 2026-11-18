# Bootstrap

The pieces every other stack depends on (ADR-023): the state bucket, the budget alarm and the
role CI uses for `terraform plan`. Applied by hand, with the owner's own login:

```bash
aws sso login --profile sa-admin
export AWS_PROFILE=sa-admin
cd infra/terraform/bootstrap
```

The first time only, the state bucket does not exist yet, so start with local state:

```bash
terraform init -backend=false
terraform import aws_budgets_budget.monthly "571771087482:scheduling-agent monthly"
terraform apply
terraform init -migrate-state   # move the local state into the bucket it just created
rm terraform.tfstate*
```

After that, the usual `terraform init && terraform plan && terraform apply`.

`terraform.tfvars` (git-ignored) holds `alert_email`.
