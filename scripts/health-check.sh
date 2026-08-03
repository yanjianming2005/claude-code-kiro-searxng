#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${project_dir}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${project_dir}/.env"
  set +a
fi
gateway_url="http://127.0.0.1:${GATEWAY_PORT:-8767}"
searxng_url="http://127.0.0.1:${SEARXNG_PORT:-8768}"

for _ in $(seq 1 60); do
  if curl -fsS "${gateway_url}/health" >/dev/null 2>&1 && \
     curl -fsS "${searxng_url}/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS "${gateway_url}/health" >/dev/null || {
  docker compose --project-directory "${project_dir}" logs --tail=80 kiro-gateway
  exit 1
}
curl -fsS "${searxng_url}/healthz" >/dev/null || {
  docker compose --project-directory "${project_dir}" logs --tail=80 searxng
  exit 1
}

result_count="$(curl -fsS --get "${searxng_url}/search" \
  --data-urlencode 'q=深圳南山区二手房均价' \
  --data 'format=json' \
  --data 'language=zh-CN' \
  --data-urlencode 'engines=baidu,bing,360search,sogou' | \
  python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("results", [])))')"

[[ "${result_count}" -gt 0 ]] || {
  printf 'SearXNG 正常启动，但中文搜索没有返回结果。请检查网络。\n' >&2
  exit 1
}

printf 'OK: Gateway 健康，SearXNG 中文搜索返回 %s 条结果。\n' "${result_count}"
