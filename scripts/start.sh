#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker compose --project-directory "${project_dir}" up -d
"${project_dir}/scripts/health-check.sh"
