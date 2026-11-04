#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
fe_bin="${FE_BIN:-fe}"
status=0

for case_dir in "$root"/cases/*; do
  case_name="$(basename "$case_dir")"
  actual="$(mktemp)"

  if "$fe_bin" check --color never "$case_dir" >"$actual" 2>&1; then
    echo "FAIL $case_name: compiled successfully"
    status=1
  elif ! diff -u "$case_dir/expected.stderr" "$actual"; then
    echo "FAIL $case_name: diagnostic changed"
    status=1
  else
    echo "PASS $case_name"
  fi

  rm -f "$actual"
done

exit "$status"
