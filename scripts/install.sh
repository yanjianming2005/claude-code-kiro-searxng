#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${project_dir}/.env"
claude_env_file="${project_dir}/.claude-env"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "未找到 Docker。请先安装并启动 Docker Desktop。"
command -v python3 >/dev/null 2>&1 || fail "未找到 python3。"
command -v curl >/dev/null 2>&1 || fail "未找到 curl。"

if ! docker info >/dev/null 2>&1; then
  if [[ "$(uname -s)" == "Darwin" ]] && [[ -d /Applications/Docker.app ]]; then
    printf '正在启动 Docker Desktop...\n'
    open -a Docker
    for _ in $(seq 1 60); do
      docker info >/dev/null 2>&1 && break
      sleep 1
    done
  fi
fi
docker info >/dev/null 2>&1 || fail "Docker daemon 未运行。"
docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2。"

aws_cache_dir="${HOME}/.aws/sso/cache"
cli_dir="${HOME}/.local/share/kiro-cli"
mkdir -p "${aws_cache_dir}" "${cli_dir}" "${project_dir}/debug_logs"

creds_file="${aws_cache_dir}/kiro-auth-token.json"
cli_db="${cli_dir}/data.sqlite3"
creds_container=""
cli_db_container=""

if [[ -f "${creds_file}" ]]; then
  creds_container="/home/kiro/.aws/sso/cache/kiro-auth-token.json"
elif [[ -f "${cli_db}" ]]; then
  cli_db_container="/home/kiro/.local/share/kiro-cli/data.sqlite3"
else
  fail "未发现 Kiro 登录凭据。请先打开 Kiro 或运行 kiro-cli login 完成登录，再重新运行本脚本。"
fi

profile_arn=""
profile_candidates=(
  "${HOME}/Library/Application Support/Kiro/User/globalStorage/kiro.kiroagent/profile.json"
  "${HOME}/.config/Kiro/User/globalStorage/kiro.kiroagent/profile.json"
)
for profile_file in "${profile_candidates[@]}"; do
  if [[ -f "${profile_file}" ]]; then
    profile_arn="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print(d.get("arn") or d.get("profileArn") or "")' "${profile_file}")"
    [[ -n "${profile_arn}" ]] && break
  fi
done
if [[ -z "${profile_arn}" && -f "${creds_file}" ]]; then
  profile_arn="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print(d.get("profileArn") or d.get("profile_arn") or "")' "${creds_file}")"
fi

proxy_api_key="sk-local-$(openssl rand -hex 18)"
searxng_secret="$(openssl rand -hex 32)"
gateway_port="${GATEWAY_PORT:-8767}"
gateway_bind_host="${GATEWAY_BIND_HOST:-127.0.0.1}"
searxng_port="${SEARXNG_PORT:-8768}"
vpn_proxy_url=""
if command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 8118 >/dev/null 2>&1; then
  vpn_proxy_url="http://host.docker.internal:8118"
  printf '检测到本机 8118 代理，Gateway 将通过该代理访问 Kiro。\n'
fi

umask 077
{
  printf 'GATEWAY_PORT=%s\n' "${gateway_port}"
  printf 'GATEWAY_BIND_HOST=%s\n' "${gateway_bind_host}"
  printf 'SEARXNG_PORT=%s\n' "${searxng_port}"
  printf 'PROXY_API_KEY=%s\n' "${proxy_api_key}"
  printf 'SEARXNG_SECRET=%s\n' "${searxng_secret}"
  printf 'KIRO_AWS_CACHE_DIR="%s"\n' "${aws_cache_dir}"
  printf 'KIRO_CLI_DIR="%s"\n' "${cli_dir}"
  printf 'KIRO_CREDS_FILE_CONTAINER=%s\n' "${creds_container}"
  printf 'KIRO_CLI_DB_FILE_CONTAINER=%s\n' "${cli_db_container}"
  printf 'PROFILE_ARN=%s\n' "${profile_arn}"
  printf 'VPN_PROXY_URL=%s\n' "${vpn_proxy_url}"
  printf 'KIRO_REGION=us-east-1\n'
  printf 'LOG_LEVEL=INFO\n'
} > "${env_file}"

{
  printf 'export ANTHROPIC_BASE_URL="http://127.0.0.1:%s"\n' "${gateway_port}"
  printf 'export ANTHROPIC_API_KEY="%s"\n' "${proxy_api_key}"
  printf 'unset ANTHROPIC_AUTH_TOKEN\n'
  printf 'export ANTHROPIC_MODEL="claude-opus-5"\n'
  printf 'export ANTHROPIC_DEFAULT_OPUS_MODEL="claude-opus-5"\n'
  printf 'export ANTHROPIC_DEFAULT_SONNET_MODEL="claude-sonnet-5"\n'
  printf 'export ANTHROPIC_DEFAULT_HAIKU_MODEL="claude-haiku-4.5"\n'
  printf 'export CLAUDE_CODE_MAX_CONTEXT_TOKENS="1000000"\n'
  printf 'export CLAUDE_CODE_MAX_OUTPUT_TOKENS="128000"\n'
} > "${claude_env_file}"

printf '正在构建并启动 Gateway 与 SearXNG...\n'
docker compose --project-directory "${project_dir}" up -d --build
"${project_dir}/scripts/health-check.sh"

printf '\n安装完成。当前终端执行：\n\n'
printf '  source "%s"\n' "${claude_env_file}"
printf '  claude\n\n'
printf 'Gateway: http://127.0.0.1:%s\n' "${gateway_port}"
printf 'SearXNG: http://127.0.0.1:%s\n' "${searxng_port}"
