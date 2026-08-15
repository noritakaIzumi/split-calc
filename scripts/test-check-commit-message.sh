#!/usr/bin/env bash

set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
checker="$repo_root/scripts/check-commit-message.sh"
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT

assert_valid() {
    printf '%b\n' "$1" >"$test_dir/message"
    "$checker" "$test_dir/message"
}

assert_invalid() {
    printf '%b\n' "$1" >"$test_dir/message"
    if "$checker" "$test_dir/message" >/dev/null 2>&1; then
        printf 'Expected message to be rejected: %s\n' "$1" >&2
        exit 1
    fi
}

assert_valid 'feat(cli): add monthly installment breakdown'
assert_valid 'fix: handle interrupted input'
assert_valid 'feat(api)!: remove legacy output\n\nBREAKING CHANGE: clients must use the new output'

assert_invalid 'added monthly installment breakdown'
assert_invalid 'feature: add monthly installment breakdown'
assert_invalid 'Feat: add monthly installment breakdown'
assert_invalid 'feat(CLI): add monthly installment breakdown'
assert_invalid 'feat: Add monthly installment breakdown'
assert_invalid 'feat: add monthly installment breakdown.'
assert_invalid 'feat!: remove legacy output'
assert_invalid 'feat: remove legacy output\n\nBREAKING CHANGE: clients must use the new output'
assert_invalid 'feat: add a subject that is deliberately much longer than seventy-two characters total'

printf '%s\n' 'Commit message checks passed.'
