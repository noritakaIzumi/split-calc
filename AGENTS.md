# Repository instructions

## Commit messages

Use Conventional Commits for every commit:

```text
<type>[optional scope][optional !]: <description>
```

- Use one of these lowercase types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`, `style`, or `revert`.
- Write the description in the imperative mood, keep it concise, and do not end it with a period.
- Add a scope only when it makes the affected area clearer, for example `feat(cli): ...`.
- Use `!` and a `BREAKING CHANGE:` footer for backward-incompatible changes.
- Use the commit body to explain motivation or non-obvious behavior when necessary.
- Keep each commit focused on one logical change.

Example:

```text
feat(cli): add monthly installment breakdown
```

## Tests

Run the complete test suite from the repository root with:

```console
uv run python -m unittest -v
scripts/test-check-commit-message.sh
```

When asked to run the project tests, run both commands unless the request specifies a narrower scope.
