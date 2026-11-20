#!/usr/bin/env bash
# Збирає образ з поточного коміту, імпортує його в k3s і оновлює Deployment.
# Запускати на сервері з кореня клону:  sudo viewer/deploy/k3s-deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."                       # viewer/
TAG="$(git rev-parse --short HEAD)"
IMAGE="mbviewer:${TAG}"
NS=mbviewer

if ! kubectl -n "$NS" get secret mbviewer-env >/dev/null 2>&1; then
  echo "Немає Secret mbviewer-env у namespace $NS. Спершу:" >&2
  echo "  kubectl create namespace $NS" >&2
  echo "  kubectl -n $NS create secret generic mbviewer-env --from-env-file=/etc/mbviewer/mbviewer.env" >&2
  exit 1
fi

echo "== Збираю $IMAGE"
docker build -t "$IMAGE" .

echo "== Імпортую образ у k3s"
docker save "$IMAGE" | k3s ctr images import -

echo "== Застосовую маніфест"
sed "s|image: mbviewer:local.*|image: ${IMAGE}|" deploy/k3s-mbviewer.yaml | kubectl apply -f -

kubectl -n "$NS" rollout status deployment/mbviewer --timeout=120s
kubectl -n "$NS" get pods,ingress
