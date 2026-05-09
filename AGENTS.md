# MOC: agent operating contract

Use this file as the default working contract for any AI agent session in this repository.

## 1) Humanizer-first writing policy

Prioritize the `humanizer` skill for any human-facing text before final output. This includes documentation, README updates, code comments, PR descriptions, commit messages, issue replies, release notes, and terminal explanations.

Minimum bar for every text pass:
- remove AI-sounding filler and generic hype
- keep claims concrete and specific
- prefer direct sentences over ornamental phrasing
- keep the original meaning intact

## 2) coding practices

- Write modular code with clear boundaries and single-purpose modules.
- Keep functions focused; split long logic into helpers.
- Prefer explicit types on public Python APIs.
- Use comments sparingly, and only to explain intent or non-obvious tradeoffs.
- Keep behavior changes scoped; avoid unrelated edits.

## 3) use `uv` properly

Use `uv` as the default Python workflow tool:

- `uv sync` for environment setup and dependency resolution
- `uv add <package>` / `uv remove <package>` for dependency changes
- `uv run <command>` to run scripts, tests, linters, and build steps

Avoid direct `pip install` unless there is a hard blocker with `uv`.

## 4) project guardrails

- Treat this project as Windows-first unless explicitly changed.
- Keep the documented split clear: `qfi` handles indexing + HTTP backend, `qf` is the client/search interface.
- Preserve documented API and config contracts when making changes.
