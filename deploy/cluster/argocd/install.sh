#!/usr/bin/env bash
# Install Argo CD into the cluster (step 2.5). Run once per cluster; after that Argo CD
# keeps everything else in sync from this repository (deploy/cluster/argocd/apps/).
#   deploy/cluster/argocd/install.sh
#
# The upstream manifest is 1.9 MB, so it is not copied into the repo. Instead it is fetched
# by commit SHA (a tag can move, a commit cannot) and checked against a pinned SHA-256
# before anything is applied; on any mismatch nothing is installed. Its images, pinned
# upstream only by tag, are pinned here by digest (T20).
set -euo pipefail

VERSION=v3.5.5
COMMIT=a5038b0e2bbac1715754380ae0084df8e3d5b48c  # the v3.5.5 tag
SHA256=90dc9094bf4c5964afd9c0e35d735e1c2fcbbda4f8e36799c092d9864ed65f50
URL="https://raw.githubusercontent.com/argoproj/argo-cd/${COMMIT}/manifests/install.yaml"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
curl -fsSL -o "$workdir/install.yaml" "$URL"
echo "${SHA256}  $workdir/install.yaml" | shasum -a 256 -c - >/dev/null \
  || { echo "checksum mismatch for Argo CD ${VERSION}; nothing installed" >&2; exit 1; }

sed -i.bak \
  -e "s|quay.io/argoproj/argocd:${VERSION}$|quay.io/argoproj/argocd:${VERSION}@sha256:13db7b10db23283b1b36f855046602e18539a8a8204c9f6f039e8896c8897518|" \
  -e "s|ghcr.io/dexidp/dex:v2.45.1$|ghcr.io/dexidp/dex:v2.45.1@sha256:8499afd690c437f52301efd2b05b2455da5bd2dfc20332cd697dc9937f808462|" \
  -e "s|public.ecr.aws/docker/library/redis:8.2.3-alpine$|public.ecr.aws/docker/library/redis:8.2.3-alpine@sha256:08ad0b1d280850169a790dba1393ff7a90aef951fc19632cf4d3ce4f78e679ba|" \
  "$workdir/install.yaml"
if grep -E '^\s+image:' "$workdir/install.yaml" | grep -vq '@sha256:'; then
  echo "an Argo CD image is not pinned by digest; nothing installed" >&2; exit 1
fi

kubectl get namespace argocd >/dev/null 2>&1 || kubectl create namespace argocd >/dev/null
# Server-side apply: Argo CD's CRDs are too large for the annotation client-side apply keeps.
kubectl apply --server-side --force-conflicts -n argocd -f "$workdir/install.yaml" >/dev/null
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s
kubectl -n argocd rollout status deploy/argocd-repo-server --timeout=300s
kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=300s
echo "Argo CD ${VERSION} installed. Next: kubectl apply -f deploy/cluster/argocd/root.yaml"
