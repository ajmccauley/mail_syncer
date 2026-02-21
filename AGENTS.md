# Repository Guidelines

## Project Structure & Module Organization
This repository hosts a Python IMAP-to-IMAP sync service (Gmail -> Outlook.com) with DynamoDB-backed state.

- `src/`: application code.
- `src/main.py`: CLI entrypoint (`run-once`, `daemon`, token helper commands).
- `src/sync_engine.py`: orchestration for incremental sync and idempotency flow.
- `src/dynamodb_state.py`: watermark, UID records, and fail-safe state operations.
- `src/gmail_imap.py`, `src/outlook_imap.py`: provider-specific IMAP clients.
- `src/oauth_gmail.py`, `src/oauth_microsoft.py`: OAuth2 token refresh and auth helpers.
- `src/imap_utils.py`, `src/logging_utils.py`, `src/config.py`: shared utilities/config.
- `tests/`: `pytest` suite mirroring `src/` modules.
- Root docs/config: `README.md`, `.env.example`, `Dockerfile`, optional `docker-compose.yml`.

## Build, Test, and Development Commands
Use a local virtualenv and run modules from repo root.

- `python -m venv .venv && source .venv/bin/activate`: create and activate env.
- `pip install -r requirements.txt -r requirements-dev.txt`: install runtime/dev deps.
- `python -m src.main run-once --dry-run`: execute one sync cycle safely.
- `python -m src.main daemon`: start continuous sync loop.
- `pytest -q`: run tests.
- `ruff check src tests && ruff format src tests`: lint and format.

## Coding Style & Naming Conventions
- Python 3.11+; 4-space indentation; UTF-8 files.
- Follow PEP 8 with type hints on public functions and dataclass-based config objects where useful.
- Modules/files: `snake_case.py`; functions/variables: `snake_case`; classes: `PascalCase`; constants: `UPPER_SNAKE_CASE`.
- Keep IMAP/OAuth code side-effect-light and testable (inject clients, avoid global state).

## Testing Guidelines
- Framework: `pytest`.
- Test files: `tests/test_<module>.py`; test names: `test_<behavior>()`.
- Minimum focus areas:
- DynamoDB idempotency conditional-write behavior.
- UIDVALIDITY rollover/resync logic.
- RFC822 hashing and `Message-ID` extraction.
- Add regression tests for each bug fix before merging.

## Commit & Pull Request Guidelines
No existing commit history is available; use this convention going forward:

- Commit format: `type(scope): short summary` (example: `feat(sync): add UIDVALIDITY fallback window`).
- Keep commits focused and atomic; include tests/docs with behavior changes.
- PRs should include:
- clear problem statement and solution summary,
- linked issue/task,
- test evidence (`pytest` output),
- config or operational impact (env vars, IAM, DynamoDB schema changes).

## Security & Configuration Tips
- Never commit secrets (`*_REFRESH_TOKEN`, client secrets, AWS credentials).
- Use env vars or mounted secret files; keep `.env.example` non-sensitive.
- Fail safe on DynamoDB errors: do not perform IMAP actions when state backend is unavailable.
