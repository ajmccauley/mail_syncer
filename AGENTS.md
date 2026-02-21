# Repository Guidelines

## Project Structure & Module Organization
This repository hosts a Python IMAP-to-IMAP sync service (Gmail -> Outlook.com) with DynamoDB-backed state.

- `src/`: application code.
- `src/main.py`: local CLI entrypoint (`run-once`, token helper commands).
- `src/lambda_handler.py`: AWS Lambda entrypoint for scheduled sync.
- `src/sync_engine.py`: orchestration for incremental sync and idempotency flow.
- `src/dynamodb_state.py`: watermark, UID records, and fail-safe state operations.
- `src/gmail_imap.py`, `src/outlook_imap.py`: provider-specific IMAP clients.
- `src/oauth_gmail.py`, `src/oauth_microsoft.py`: OAuth2 token refresh and auth helpers.
- `src/imap_utils.py`, `src/logging_utils.py`, `src/config.py`: shared utilities/config.
- `tests/`: `pytest` suite mirroring `src/` modules.
- `.github/workflows/`: CI and deployment workflows.
- Root docs/config: `README.md`, `.env.example`, and infrastructure/deploy templates.

## Build, Test, and Development Commands
Use a local virtualenv and run modules from repo root.

- `python -m venv .venv && source .venv/bin/activate`: create and activate env.
- `pip install -r requirements.txt -r requirements-dev.txt`: install runtime/dev deps.
- `python -m src.main run-once --dry-run`: execute one sync cycle safely.
- `python -m src.main lambda`: run one Lambda-style cycle locally.
- `python -m src.main auth gmail` / `python -m src.main auth microsoft`: run interactive OAuth helpers.
- `pytest -q`: run tests.
- `ruff check src tests && ruff format src tests`: lint and format.
- `act -l` (optional): list local GitHub Actions jobs if using `act`.

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
- Multi-route isolation (multiple Gmail sources to multiple Outlook folders).
- Add regression tests for each bug fix before merging.

## Commit & Pull Request Guidelines
Use conventional commits:

- Commit format: `type(scope): short summary` (example: `feat(sync): add UIDVALIDITY fallback window`).
- Keep commits focused and atomic; include tests/docs with behavior changes.
- PRs should include:
- clear problem statement and solution summary,
- linked issue/task,
- test evidence (`pytest` output),
- config or operational impact (env vars, IAM, DynamoDB schema, workflow changes).

## Sync Behavior Notes
- Preserve Gmail source messages: no delete/move/label/modify operations.
- Route state is isolated by PK (`ROUTE#<gmail>#DEST#<outlook>#FOLDER#<folder>`).
- Maintain idempotency via DynamoDB conditional UID claim and finalize flow.
- Keep route-level failures isolated; do not abort the whole invocation when one route fails.
- Interactive OAuth token helper commands are implemented for local first-run provisioning.
- Use `--write-secret-id` and `--write-secret-key` to write refreshed tokens into Secrets Manager.

## CI/CD Deployment
- `main` branch pushes trigger automatic AWS deployment via GitHub Actions.
- Use GitHub OIDC to assume AWS role; do not store long-lived AWS keys in repo secrets.
- Required workflow stages: lint -> tests -> package -> deploy.
- Deployment must be idempotent and emit logs/artifacts for failure diagnosis.

## Security & Configuration Tips
- Never commit secrets (`*_REFRESH_TOKEN`, client secrets, AWS credentials).
- Use env vars, AWS Secrets Manager, or SSM Parameter Store; keep `.env.example` non-sensitive.
- `AWS_SECRETS_MANAGER_SECRET_IDS` supports comma-separated JSON secrets merged at runtime.
- Fail safe on DynamoDB errors: do not perform IMAP actions when state backend is unavailable.
