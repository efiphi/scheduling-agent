# Cloud

The always-on server (Layer 6, ADR-023): one spot ARM instance in eu-central-1 running k3s,
with a fixed address and a data volume that outlives the instance.

```bash
aws sso login --profile sa-admin
export AWS_PROFILE=sa-admin
cd infra/terraform/cloud
terraform init && terraform plan && terraform apply
```

## What it costs

About $19-21 a month (18.11 prices): the spot instance $13-16, the disks $2.9, the public
IPv4 address $3.7. The account's budget alarm is $25 (bootstrap stack).

## Stopping every charge: the kill switch

```bash
terraform destroy
```

This deletes the server, the disks and the address, and the charges stop. **The data volume
goes with it**: restore from the nightly backup in S3 afterwards (step 6.5). Stopping the
instance in the console is not enough: the disks and the address keep costing about $6 a
month. What remains after a destroy: the state and backup buckets (cents) and the domain.

## Getting on the server

No SSH. Session Manager, with the owner's AWS login:

```bash
aws ssm start-session --target "$(aws ec2 describe-instances \
  --filters Name=tag:project,Values=scheduling-agent Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)"
```

## When spot takes the server back

The Auto Scaling group starts a new instance. Its boot script (`user-data.sh.tftpl`) takes the
Elastic IP, waits for the data volume to be free, attaches it and starts k3s under the same
node name, so the cluster continues where it stopped. Tested on 18.11 by terminating the
instance: a new one was up in 30 seconds and the cluster, with its objects, was back about
two minutes later.
