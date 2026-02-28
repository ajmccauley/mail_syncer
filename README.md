# mail_syncer

IMAP-to-IMAP sync service that copies new messages from one or more Gmail inboxes into folders in one Outlook.com mailbox, with DynamoDB-backed idempotent state.

## File Tree
```text
.
├── .env.example
├── .github/workflows/
│   ├── ci.yml
│   └── deploy.yml
├── infra/
│   └── template.yaml
├── scripts/
│   ├── check_latest_deploy.py
│   ├── create_dynamodb_table.sh
│   └── migrate_secrets_to_ssm.py
├── src/
│   ├── config.py
│   ├── dynamodb_state.py
│   ├── gmail_imap.py
│   ├── imap_utils.py
│   ├── lambda_handler.py
│   ├── logging_utils.py
│   ├── main.py
│   ├── oauth_gmail.py
│   ├── oauth_microsoft.py
│   ├── outlook_imap.py
│   ├── secrets_config.py
│   └── sync_engine.py
└── tests/
    ├── test_config.py
    ├── test_dynamodb_state.py
    ├── test_fail_safe.py
    ├── test_imap_utils.py
    ├── test_secrets_config.py
    └── test_sync_engine.py
```

## Local Development
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
python -m src.main run-once --dry-run
```

## Runtime Modes
- `python -m src.main run-once [--dry-run]`: one sync cycle.
- `python -m src.main lambda`: run Lambda-style cycle locally.

## First-Run OAuth Setup
Run these locally (not in Lambda), then store returned refresh tokens in AWS SSM Parameter Store (`SecureString`).

### Google (Gmail IMAP)
1. Google Cloud Console -> create OAuth client (`Web application`).
2. Add redirect URI: `http://127.0.0.1:8765/callback`.
3. Ensure scope includes `https://mail.google.com/`.
4. Run:
```bash
python -m src.main auth gmail \
  --client-id "$GMAIL_CLIENT_ID" \
  --client-secret "$GMAIL_CLIENT_SECRET"
```

### Microsoft (Outlook IMAP)
1. Azure App Registration (`tenant=consumers` for personal Outlook).
2. Redirect URI: `http://localhost:8766/callback`.
3. Delegated permission: `IMAP.AccessAsUser.All` (+ `offline_access` scope).
4. Run:
```bash
python -m src.main auth microsoft \
  --tenant consumers \
  --client-id "$MS_CLIENT_ID" \
  --client-secret "$MS_CLIENT_SECRET"
```

### Optional: write token directly to SSM Parameter Store
```bash
python -m src.main auth gmail --write-parameter-name /mail-syncer/routes --write-parameter-key GMAIL_REFRESH_TOKEN
python -m src.main auth microsoft --write-parameter-name /mail-syncer/outlook --write-parameter-key MS_REFRESH_TOKEN
```

Legacy fallback during migration:
```bash
python -m src.main auth gmail --write-secret-id mail-syncer/routes --write-secret-key GMAIL_REFRESH_TOKEN
python -m src.main auth microsoft --write-secret-id mail-syncer/outlook --write-secret-key MS_REFRESH_TOKEN
```

## Configuration
Start from `.env.example`.

Important variables:
- `AWS_REGION`
- `DYNAMODB_TABLE`
- `AWS_LAMBDA_FUNCTION_NAME` (optional, runtime-provided in Lambda)
- `OUTLOOK_EMAIL`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT`, `MS_REFRESH_TOKEN`
- `SYNC_ROUTES_JSON` (array of route objects with Gmail creds + destination folder)

Config-store loading:
- Set `AWS_SSM_PARAMETER_NAMES` to comma-separated SSM parameter names.
- Each parameter value must be a JSON object; keys are merged into env.
- Optional migration fallback: `AWS_SECRETS_MANAGER_SECRET_IDS` (legacy).
- Explicit env vars override loaded values.
- Parameter Store is the default to reduce recurring secret-storage cost for this workload.

Example:
```bash
AWS_SSM_PARAMETER_NAMES=/mail-syncer/outlook,/mail-syncer/routes
```

## AWS Lambda Deployment
Deployment is via **AWS SAM**, which generates and deploys **CloudFormation**.  
So the deploy path is: GitHub Action -> `sam build/deploy` -> CloudFormation stack updates.

### What gets created
- Lambda function (`src/lambda_handler.handler`)
- DynamoDB table with TTL (`ttl` attribute)
- EventBridge rule `rate(5 minutes)` to invoke Lambda

### Packaging and deploy commands
```bash
sam build --template-file infra/template.yaml
sam deploy \
  --stack-name mail-syncer-prod \
  --template-file .aws-sam/build/template.yaml \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --resolve-s3
```

### One-time GitHub setup (required)
1. In repository **Settings -> Secrets and variables -> Actions**:
   - Secret: `AWS_ROLE_ARN` (OIDC-assumable deploy role in your AWS account).
   - Fallback supported: repository/environment variable `AWS_ROLE_ARN`.
   - Variables:
     - `AWS_REGION` (example: `us-west-2`)
     - `DEPLOY_ENV` (example: `prod`)
     - `AWS_SSM_PARAMETER_NAMES` (example: `/mail-syncer/routes,/mail-syncer/outlook`)
       - Set value only (no `KEY=` prefix).
   - Optional runtime tuning variables:
     - `STACK_NAME` (override default `mail-syncer-${DEPLOY_ENV}`)
     - `SCHEDULE_EXPRESSION` (example: `rate(5 minutes)`)
     - `LAMBDA_MEMORY_SIZE` (example: `512`)
     - `LAMBDA_TIMEOUT_SECONDS` (example: `120`)
     - `LOG_LEVEL` (example: `INFO`)
     - `SYNC_INTERVAL_SECONDS` (example: `300`)
2. In **Settings -> Environments -> production**, add reviewers if you want approval gates.
3. Ensure IAM role in `AWS_ROLE_ARN` trusts GitHub OIDC and allows CloudFormation/SAM/Lambda/DynamoDB/EventBridge/Logs/SSM actions for this stack.

### IAM notes
Least privilege for runtime should include:
- DynamoDB: `DescribeTable`, `GetItem`, `PutItem`, `UpdateItem`, `Query`
- CloudWatch Logs write permissions
- SSM Parameter Store: `ssm:GetParameter`, `ssm:GetParameters` for only required parameter ARNs

### VPC guidance
Do not attach Lambda to a VPC unless your org/network policy requires it. IMAP endpoints are public and VPC networking adds NAT complexity and latency.

### Optional reliability hardening
- Add Lambda DLQ (SQS) or on-failure destination.
- Add CloudWatch alarms:
- Lambda `Errors > 0`
- Lambda duration near timeout
- DynamoDB throttles/read-write errors

## GitHub Actions CI/CD
- `ci.yml`: lint + tests on PRs/pushes.
- `deploy.yml`: deploy on `main` pushes and manual dispatch.
- Add `[skip deploy]` to a commit message to skip deploy on push while still running CI.
- AWS auth uses GitHub OIDC with `AWS_ROLE_ARN`.
- Deploy uses `--no-fail-on-empty-changeset` for idempotent re-runs.
- Deployment logs are uploaded as workflow artifacts.
- Deploy workflow validates template, builds SAM artifacts, then deploys CloudFormation stack.

Required repo configuration:
- Secret: `AWS_ROLE_ARN`
- Variables: `AWS_REGION`, `DEPLOY_ENV`, `AWS_SSM_PARAMETER_NAMES`
- Environment protection: configure required reviewers on GitHub `production` environment if needed.
- Migration note: deploy workflow temporarily falls back to legacy `AWS_SECRETS_MANAGER_SECRET_IDS` if `AWS_SSM_PARAMETER_NAMES` is unset.

## Migration: Secrets Manager -> Parameter Store
Use this script to copy existing JSON secrets into SSM SecureString parameters.

```bash
python3 scripts/migrate_secrets_to_ssm.py \
  --region us-west-2 \
  --mapping mail-syncer/routes=/mail-syncer/routes \
  --mapping mail-syncer/outlook=/mail-syncer/outlook \
  --overwrite
```

Branch/environment mapping:
- `main` push -> `production` environment (default `DEPLOY_ENV=prod`)
- manual dispatch can override target deploy environment through workflow inputs.

## Deploy Log Checker Tool
You can check the latest deploy run and inspect failures locally.

Prerequisites:
- GitHub CLI installed (`gh`)
- Authenticated: `gh auth login`

Command:
```bash
python3 scripts/check_latest_deploy.py
```

Useful options:
```bash
python3 scripts/check_latest_deploy.py --run-id 123456789
python3 scripts/check_latest_deploy.py --tail-lines 200
python3 scripts/check_latest_deploy.py --full-log
```

Exit codes:
- `0`: latest deploy succeeded
- `2`: deploy run exists but did not succeed
- `3`: tooling/auth/retrieval error
