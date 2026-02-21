# mail_syncer

IMAP-to-IMAP sync service that copies new messages from one or more Gmail inboxes into folders in a single Outlook.com mailbox, with DynamoDB-backed idempotent state.

## Current Status
Foundation batch implemented:
- Multi-route configuration loading (`SYNC_ROUTES_JSON` or single-route fallback env vars).
- Lambda and local CLI entrypoints.
- DynamoDB fail-safe gate (abort before any IMAP action when unavailable).
- CI/CD and AWS SAM deployment scaffolding.

IMAP read/write workflows and full DynamoDB watermark/idempotency schema are still in progress.

## Local Development
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
python -m src.main run-once --dry-run
```

## AWS Deployment
- GitHub Actions handles CI and deployment on `main` pushes.
- Deployment template: `infra/template.yaml`.
- Configure repository secrets/variables:
- `AWS_ROLE_ARN`
- `AWS_REGION`
- `DEPLOY_ENV` (example: `prod`)

## Configuration
Start with `.env.example` and set values from your secret manager.

