#!/bin/bash
# .envrc と .envrc.sample のキー差分をチェックする
set -euo pipefail

SAMPLE=".envrc.sample"
ENVRC=".envrc"

if [ ! -f "$SAMPLE" ]; then
  echo "エラー: $SAMPLE が見つかりません"
  exit 1
fi

if [ ! -f "$ENVRC" ]; then
  echo "エラー: $ENVRC が見つかりません"
  echo "  make cp を実行してください"
  exit 1
fi

extract_keys() {
  grep -E '^\s*export\s+[A-Za-z_][A-Za-z0-9_]*' "$1" \
    | sed -E 's/^[[:space:]]*export[[:space:]]+([A-Za-z_][A-Za-z0-9_]*).*/\1/' \
    | sort -u
}

sample_keys=$(extract_keys "$SAMPLE")
envrc_keys=$(extract_keys "$ENVRC")

missing=$(comm -23 <(echo "$sample_keys") <(echo "$envrc_keys"))
extra=$(comm -13 <(echo "$sample_keys") <(echo "$envrc_keys"))

has_diff=0

if [ -n "$missing" ]; then
  echo "$ENVRC に不足しているキー（$SAMPLE にあるが $ENVRC にない）:"
  echo "$missing" | sed 's/^/  /'
  has_diff=1
fi

if [ -n "$extra" ]; then
  echo "$ENVRC にある追加キー（$SAMPLE にない）:"
  echo "$extra" | sed 's/^/  /'
  has_diff=1
fi

if [ "$has_diff" -eq 0 ]; then
  echo "OK: $ENVRC と $SAMPLE のキーは一致しています"
else
  exit 1
fi
