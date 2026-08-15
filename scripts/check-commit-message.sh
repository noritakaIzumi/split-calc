#!/usr/bin/env bash

set -eu

commit_message_file=${1:?"commit message file is required"}
subject=$(sed -n '1{s/\r$//;p;}' "$commit_message_file")
allowed_types='feat|fix|docs|test|refactor|perf|build|ci|chore|style|revert'
subject_pattern="^(${allowed_types})(\([a-z0-9][a-z0-9._/-]*\))?!?: [a-z0-9]"

fail() {
    printf '%s\n' "Invalid commit message: $1" >&2
    printf '%s\n' \
        'Expected: <type>[optional scope][optional !]: <description>' \
        'Example:  feat(cli): add monthly installment breakdown' >&2
    exit 1
}

if ! printf '%s\n' "$subject" | grep -Eq "$subject_pattern"; then
    fail 'the subject does not follow the required Conventional Commits format'
fi

if [ "${#subject}" -gt 72 ]; then
    fail 'the subject must be 72 characters or fewer'
fi

case $subject in
    *.) fail 'the subject must not end with a period' ;;
esac

has_breaking_marker=false
case $subject in
    *'!: '*) has_breaking_marker=true ;;
esac

has_breaking_footer=false
if grep -Eq '^BREAKING CHANGE: .+' "$commit_message_file"; then
    has_breaking_footer=true
fi

if [ "$has_breaking_marker" != "$has_breaking_footer" ]; then
    fail 'breaking changes require both ! in the subject and a BREAKING CHANGE: footer'
fi

