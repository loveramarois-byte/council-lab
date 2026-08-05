#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

forbidden_path_pattern='traditional|lunar-javascript|iztro'
forbidden_content_pattern='traditional[_ -]?culture|TraditionalCulture|TRADITIONAL_|传统文化|传统研判|排盘|紫微|lunar-javascript|iztro'

path_matches="$(git ls-files | grep -Ei "$forbidden_path_pattern" || true)"
if [[ -n "$path_matches" ]]; then
  echo "Public scope check failed: private feature paths are tracked:" >&2
  echo "$path_matches" >&2
  exit 1
fi

if git grep -n -I -E "$forbidden_content_pattern" -- . \
  ':(exclude)scripts/check_public_scope.sh'; then
  echo "Public scope check failed: private feature content is tracked." >&2
  exit 1
fi

echo "Public scope check passed: decision-analysis files only."
