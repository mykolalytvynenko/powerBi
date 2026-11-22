#!/usr/bin/env bash
# Розгортає або оновлює застосунок у k3s з поточного коміту. Docker не потрібен:
# код кладеться в ConfigMap, залежності ставить initContainer (див. k3s-mbviewer.yaml).
# Запускати на сервері:  sudo /opt/mbviewer/viewer/deploy/k3s-deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."                       # viewer/
NS=mbviewer
STAMP="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)-$(date +%Y%m%d%H%M%S)"

kubectl get namespace "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS"

if ! kubectl -n "$NS" get secret mbviewer-env >/dev/null 2>&1; then
  echo "Немає Secret mbviewer-env у namespace $NS. Заповніть /etc/mbviewer/mbviewer.env і виконайте:" >&2
  echo "  kubectl -n $NS create secret generic mbviewer-env --from-env-file=/etc/mbviewer/mbviewer.env" >&2
  exit 1
fi

configmap() {  # configmap <name> <--from-file=...>...
  local name="$1"; shift
  kubectl -n "$NS" create configmap "$name" "$@" --dry-run=client -o yaml | kubectl apply -f -
}

echo "== Код у ConfigMap"
configmap mbviewer-app       --from-file=app/ --from-file=requirements.txt
configmap mbviewer-templates --from-file=app/templates/
configmap mbviewer-static    --from-file=app/static/

echo "== Маніфест ($STAMP)"
sed "s|mbviewer/deployed: \"manual\"|mbviewer/deployed: \"${STAMP}\"|" deploy/k3s-mbviewer.yaml | kubectl apply -f -

kubectl -n "$NS" rollout status deployment/mbviewer --timeout=300s
kubectl -n "$NS" get pods,ingress,certificate
