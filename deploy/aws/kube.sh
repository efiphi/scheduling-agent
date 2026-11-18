#!/usr/bin/env bash
# kubectl access to the cloud cluster, with no port open to the internet (ADR-023):
#   deploy/aws/kube.sh          # then: export KUBECONFIG=~/.kube/sa-aws
#
# The Kubernetes API listens on the server's port 6443, which the security group does not
# expose. Session Manager forwards it to localhost:16443 through the owner's AWS login, and
# the cluster's admin kubeconfig is copied over the same channel into a file only the owner
# can read. Nothing is printed.
#
# Leave this running while you use kubectl; Ctrl+C closes the tunnel.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-sa-admin}"
REGION=eu-central-1
LOCAL_PORT=16443
KUBECONFIG_FILE="$HOME/.kube/sa-aws"

instance=$(aws ec2 describe-instances --region "$REGION" \
  --filters Name=tag:project,Values=scheduling-agent Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
[[ "$instance" == i-* ]] || { echo "no running server (aws sso login --profile $AWS_PROFILE?)" >&2; exit 1; }

# The kubeconfig, read as root by Run Command. Its output is cut at 2,500 characters, so the
# file comes over base64-encoded, in chunks, straight into a file only the owner can read.
mkdir -p "$HOME/.kube"
umask 077
chunk() {  # chunk N -> characters N*2000+1 .. (N+1)*2000 of the base64 file
  local id
  id=$(aws ssm send-command --region "$REGION" --instance-ids "$instance" \
    --document-name AWS-RunShellScript \
    --parameters "commands=[\"base64 -w0 /etc/rancher/k3s/k3s.yaml | cut -c$(( $1 * 2000 + 1 ))-$(( ($1 + 1) * 2000 ))\"]" \
    --query Command.CommandId --output text)
  aws ssm wait command-executed --region "$REGION" --command-id "$id" --instance-id "$instance"
  aws ssm get-command-invocation --region "$REGION" --command-id "$id" --instance-id "$instance" \
    --query StandardOutputContent --output text | tr -d '\n'
}
encoded=""
for n in 0 1 2 3 4; do
  part=$(chunk "$n")
  [ -z "$part" ] && break
  encoded="$encoded$part"
done
printf '%s' "$encoded" | base64 -d \
  | sed "s#https://127.0.0.1:6443#https://127.0.0.1:${LOCAL_PORT}#" > "$KUBECONFIG_FILE"
grep -q "client-key-data" "$KUBECONFIG_FILE" || { echo "could not read the kubeconfig" >&2; exit 1; }
sed -i.bak 's/: default$/: sa-aws/' "$KUBECONFIG_FILE" && rm -f "$KUBECONFIG_FILE.bak"
echo "kubeconfig: $KUBECONFIG_FILE (context sa-aws). Tunnel on localhost:${LOCAL_PORT}..."

exec aws ssm start-session --region "$REGION" --target "$instance" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=6443,localPortNumber=${LOCAL_PORT}"
