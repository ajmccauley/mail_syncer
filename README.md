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

## First-Run OAuth Helpers
Use local interactive flows to obtain refresh tokens (not inside Lambda):

```bash
python -m src.main auth gmail --client-id "$GMAIL_CLIENT_ID" --client-secret "$GMAIL_CLIENT_SECRET"
python -m src.main auth microsoft --client-id "$MS_CLIENT_ID" --client-secret "$MS_CLIENT_SECRET" --tenant consumers
```

Optional direct write to Secrets Manager:

```bash
python -m src.main auth gmail --write-secret-id mail-syncer/routes --write-secret-key GMAIL_REFRESH_TOKEN
python -m src.main auth microsoft --write-secret-id mail-syncer/outlook --write-secret-key MS_REFRESH_TOKEN
```

Both commands print JSON containing the new refresh token and an `env_export` snippet.

## AWS Deployment
- GitHub Actions handles CI and deployment on `main` pushes.
- Deployment template: `infra/template.yaml`.
- Configure repository secrets/variables:
- `AWS_ROLE_ARN`
- `AWS_REGION`
- `DEPLOY_ENV` (example: `prod`)

## Configuration
Start with `.env.example` and set values from your secret manager.

For Lambda, prefer AWS Secrets Manager:
- Set `AWS_SECRETS_MANAGER_SECRET_IDS` to one or more secret IDs/ARNs.
- Each secret must be a JSON object. Keys are merged into runtime env.
- Explicit Lambda env vars override secret values.
