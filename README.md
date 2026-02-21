# mail_syncer

IMAP-to-IMAP sync service that copies new messages from one or more Gmail inboxes into folders in a single Outlook.com mailbox, with DynamoDB-backed idempotent state.

## Current Status
Implemented:
- Multi-route configuration loading (`SYNC_ROUTES_JSON` or single-route fallback env vars).
- Lambda and local CLI entrypoints.
- DynamoDB fail-safe gate (abort before any IMAP action when unavailable).
- Real Gmail/Outlook IMAP clients with XOAUTH2 authentication.
- Incremental sync engine:
- route-by-route processing in a single invocation,
- UIDVALIDITY-aware fetch strategy (`UID > last_uid` and fallback `SINCE` window),
- per-message APPEND with continue-on-failure behavior.
- DynamoDB state schema operations:
- `WATERMARK`,
- conditional `UID#...` claim/finalize flow,
- `FAIL#...` retry tracking,
- fingerprint dedupe support for UIDVALIDITY changes.
- CI/CD and AWS SAM deployment scaffolding.

Still in progress:
- interactive OAuth helper commands,
- production hardening/docs completion (IAM examples, OAuth setup walkthroughs).

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
