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

About $24-27 a month (18.11 prices): the spot instance $19-21 (m6g/m8g.medium, a full core),
the disks $2.9, the public IPv4 address $3.7. Spot is capped at $0.03 an hour
(`spot_max_price`), so never more than about $28; above the cap AWS gives no server rather
than a bigger bill. The account's budget alarm is $25 (bootstrap stack).

Not t4g.medium ($13-16): this account cannot use "unlimited" CPU credits, and in "standard"
mode every new spot server starts with no credits, gets 20% of each core, and k3s fails to
start. If AWS Support enables "unlimited", t4g.medium can come back (about $20 in total).

## Stopping every charge: the kill switch

```bash
terraform destroy
```

This deletes the server, the disks and the address, and the charges stop. **The data volume
goes with it**, and with it the cluster's Sealed Secrets key: after a new apply, re-seal
(`deploy/cluster/secrets/aws`, below) and restore from the nightly backup in S3 (step 6.5).
Stopping the
instance in the console is not enough: the disks and the address keep costing about $6 a
month. What remains after a destroy: the state and backup buckets (cents) and the domain.

## Getting on the server

No SSH. Session Manager, with the owner's AWS login:

```bash
aws ssm start-session --target "$(aws ec2 describe-instances \
  --filters Name=tag:project,Values=scheduling-agent Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)"
```

## kubectl and Argo CD

```bash
deploy/aws/kube.sh                      # leave running: a tunnel to the API, no open port
export KUBECONFIG=~/.kube/sa-aws
kubectl apply -f deploy/cluster/sealed-secrets/controller.yaml   # first time only
bash deploy/cluster/argocd/install.sh                            # first time only
kubectl apply -f deploy/cluster/argocd/root-aws.yaml             # first time only
```

Secrets are sealed with this cluster's own key, which lives on the data volume and so
survives a spot replacement:

```bash
KUBECONFIG=~/.kube/sa-aws OUT_DIR=deploy/cluster/secrets/aws deploy/k3d/seal-secrets.sh
```

The cloud runs the same images as k3d (the `deploy/k3d` branch, ADR-021) with
`deploy/cluster/environments/aws/values.yaml` on top: its public address, lower memory
reservations for one 4 GiB server, and gmail-poll suspended until the data moves (step 6.5),
so the two clusters never answer the same email twice.

## When spot takes the server back

The Auto Scaling group starts a new instance. Its boot script (`user-data.sh.tftpl`) takes the
Elastic IP, waits for the data volume to be free, attaches it and starts k3s under the same
node name, so the cluster continues where it stopped. Tested on 18.11 by terminating the
instance: a new one was up in 30 seconds and the cluster, with its objects, was back about
two minutes later.
