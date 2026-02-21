# Gmail -> Outlook IMAP Sync (Python) Ordered TODO

Build a production-ready IMAP-to-IMAP sync app (no Gmail API, no Microsoft Graph) that copies new Gmail INBOX mail into Outlook.com folders with full RFC822 fidelity and strict idempotency.

## 1) Scope and routing model (first)
- [ ] Confirm multi-route scope: multiple Gmail sources -> multiple destination folders in one Outlook mailbox.
- [ ] Define route config object: `gmail_email`, `outlook_email`, `outlook_target_folder`, token refs, route options.
- [ ] Add config for many routes (JSON env var and/or mounted YAML/JSON file), e.g. `SYNC_ROUTES_JSON`.
- [ ] Keep Outlook mailbox shared across routes, but maintain state per route.

## 2) Project scaffolding
- [ ] Create files:
- [ ] `src/main.py`
- [ ] `src/config.py`
- [ ] `src/dynamodb_state.py`
- [ ] `src/gmail_imap.py`
- [ ] `src/outlook_imap.py`
- [ ] `src/oauth_gmail.py`
- [ ] `src/oauth_microsoft.py`
- [ ] `src/sync_engine.py`
- [ ] `src/imap_utils.py`
- [ ] `src/logging_utils.py`
- [ ] `src/lambda_handler.py` (Lambda entrypoint).
- [ ] Create `tests/`, `.env.example`, `README.md`.
- [ ] Create GitHub Actions workflow files in `.github/workflows/`.
- [ ] Create deployment artifacts for Lambda (SAM template, CDK, or Terraform module).

## 3) Safety gate (must block all work if failed)
- [ ] On each run, validate DynamoDB availability first.
- [ ] If DynamoDB unavailable (network/auth/throttle): do not connect to IMAP, do not copy, exit non-zero.

## 4) OAuth2 and token lifecycle
- [ ] Gmail IMAP auth via XOAUTH2.
- [ ] Outlook IMAP auth via XOAUTH2.
- [ ] Support refresh-token based headless operation.
- [ ] Add interactive helper CLI command for initial token acquisition/refresh.
- [ ] Keep refresh tokens only in env/secrets file (never committed).

## 5) DynamoDB schema and idempotency
- [ ] Use one table.
- [ ] PK per route: `ROUTE#<gmail_address>#DEST#<outlook_address>#FOLDER#<target_folder>`
- [ ] SK items:
- [ ] `WATERMARK` -> `uidvalidity`, `last_uid`, `updated_at`
- [ ] `UID#<uidvalidity>#<gmail_uid>` -> `status`, `copied_at`, `message_id_header`, `rfc822_sha256`, `ttl`
- [ ] `FAIL#<uidvalidity>#<gmail_uid>` -> `last_error`, `retry_count`, `updated_at`, `ttl`
- [ ] Use conditional writes: create UID record with `attribute_not_exists(SK)` before copy.
- [ ] Finalize UID record only after successful APPEND (`PENDING -> DONE`).

## 6) Gmail incremental read strategy
- [ ] Select INBOX, read `UIDVALIDITY`.
- [ ] If unchanged: fetch UIDs greater than `last_uid`; retrieve RFC822 for new messages.
- [ ] If changed: run fallback window (ex: 24h via `SEARCH SINCE`), dedupe by Message-ID and/or SHA256 stored in DynamoDB, then reset watermark.
- [ ] Never delete/move/label/modify Gmail messages.

## 7) Outlook destination write strategy
- [ ] Connect to Outlook IMAP once per run where possible; reuse across routes.
- [ ] Ensure each route target folder exists; create or fail clearly based on config.
- [ ] APPEND raw RFC822 as-is; default to unread unless configured.

## 8) Sync engine behavior
- [ ] Process routes independently within a single invocation.
- [ ] On per-message APPEND failure: record `FAIL#...`, continue with remaining messages.
- [ ] Add bounded retries with exponential backoff for transient IMAP/network errors.
- [ ] Add `--dry-run` to log candidate copies without APPEND.

## 9) Runtime and operations
- [ ] CLI modes:
- [ ] `run-once`
- [ ] `lambda` (event-driven handler for scheduled execution)
- [ ] EventBridge schedule every `5 minutes` to invoke Lambda.
- [ ] Ensure Lambda timeout/memory are sized for worst-case batch and IMAP latency.
- [ ] Ensure idempotent behavior across retries/re-invocations.
- [ ] Structured JSON logging with `run_id` per cycle.

## 10) Tests (pytest)
- [ ] DynamoDB idempotency conditional write/finalize behavior.
- [ ] UIDVALIDITY change and fallback resync logic.
- [ ] RFC822 SHA256 + Message-ID extraction.
- [ ] Multi-route isolation (state for one route does not affect another).

## 11) CI/CD automation (GitHub Actions -> AWS)
- [ ] Add workflow to run lint/tests on pull requests and pushes.
- [ ] Add deployment workflow to auto-deploy on push/commit to the deployment branch (ex: `main`).
- [ ] Use GitHub OIDC to assume AWS IAM role (prefer over long-lived AWS keys).
- [ ] Build/package Lambda artifact, then deploy via SAM/CDK/Terraform.
- [ ] Add environment protections (required reviewers for prod environment if needed).
- [ ] Ensure deployment is idempotent and includes rollback/failure visibility in logs.

## 12) Deployment artifacts and docs
- [ ] AWS Lambda deployment docs:
- [ ] EventBridge `rate(5 minutes)` -> Lambda trigger.
- [ ] DynamoDB table with TTL enabled.
- [ ] IAM least-privilege policy for DynamoDB + CloudWatch Logs + Secrets Manager/SSM (if used).
- [ ] VPC guidance only if required by networking policy (avoid VPC unless needed).
- [ ] Lambda package/dependency build steps (zip or Lambda layer).
- [ ] Optional DLQ/on-failure destination and CloudWatch alarm recommendations.
- [ ] README OAuth setup:
- [ ] Google Cloud app + IMAP scopes.
- [ ] Azure app registration for Outlook.com IMAP OAuth (`tenant=consumers`) permissions.
- [ ] Include full file tree, then code for each file.

## 13) Config checklist
- [ ] Base: `AWS_REGION`, `DYNAMODB_TABLE`, `SYNC_INTERVAL_SECONDS=300`, `LOG_LEVEL=INFO`
- [ ] Lambda: `AWS_LAMBDA_FUNCTION_NAME` (runtime-detected optional), timeout/memory/env configuration documented.
- [ ] Secret storage: define whether tokens come from env vars, AWS Secrets Manager, or SSM Parameter Store.
- [ ] GitHub Actions secrets/vars:
- [ ] `AWS_ROLE_ARN` (OIDC assume role target)
- [ ] `AWS_REGION`
- [ ] deployment environment name and branch mapping
- [ ] Outlook shared mailbox: `OUTLOOK_EMAIL`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` (if used), `MS_TENANT=consumers`, `MS_REFRESH_TOKEN`
- [ ] Route-level Gmail creds per source account (in route config): `GMAIL_EMAIL`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, plus `OUTLOOK_TARGET_FOLDER`
