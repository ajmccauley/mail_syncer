# Gmail -> Outlook IMAP Sync (Python) Ordered TODO

Build a production-ready IMAP-to-IMAP sync app (no Gmail API, no Microsoft Graph) that copies new Gmail INBOX mail into Outlook.com folders with full RFC822 fidelity and strict idempotency.

## 1) Scope and routing model (first)
- [x] Confirm multi-route scope: multiple Gmail sources -> multiple destination folders in one Outlook mailbox.
- [x] Define route config object: `gmail_email`, `outlook_email`, `outlook_target_folder`, token refs, route options.
- [x] Add config for many routes (JSON env var and/or mounted YAML/JSON file), e.g. `SYNC_ROUTES_JSON`.
- [x] Keep Outlook mailbox shared across routes, but maintain state per route.

## 2) Project scaffolding
- [x] Create files:
- [x] `src/main.py`
- [x] `src/config.py`
- [x] `src/dynamodb_state.py`
- [x] `src/gmail_imap.py`
- [x] `src/outlook_imap.py`
- [x] `src/oauth_gmail.py`
- [x] `src/oauth_microsoft.py`
- [x] `src/sync_engine.py`
- [x] `src/imap_utils.py`
- [x] `src/logging_utils.py`
- [x] `src/lambda_handler.py` (Lambda entrypoint).
- [x] Create `tests/`, `.env.example`, `README.md`.
- [x] Create GitHub Actions workflow files in `.github/workflows/`.
- [x] Create deployment artifacts for Lambda (SAM template, CDK, or Terraform module).

## 3) Safety gate (must block all work if failed)
- [x] On each run, validate DynamoDB availability first.
- [x] If DynamoDB unavailable (network/auth/throttle): do not connect to IMAP, do not copy, exit non-zero.

## 4) OAuth2 and token lifecycle
- [x] Gmail IMAP auth via XOAUTH2.
- [x] Outlook IMAP auth via XOAUTH2.
- [x] Support refresh-token based headless operation.
- [x] Add interactive helper CLI command for initial token acquisition/refresh.
- [x] Keep refresh tokens only in env/secrets file (never committed).

## 5) DynamoDB schema and idempotency
- [x] Use one table.
- [x] PK per route: `ROUTE#<gmail_address>#DEST#<outlook_address>#FOLDER#<target_folder>`
- [x] SK items:
- [x] `WATERMARK` -> `uidvalidity`, `last_uid`, `updated_at`
- [x] `UID#<uidvalidity>#<gmail_uid>` -> `status`, `copied_at`, `message_id_header`, `rfc822_sha256`, `ttl`
- [x] `FAIL#<uidvalidity>#<gmail_uid>` -> `last_error`, `retry_count`, `updated_at`, `ttl`
- [x] Use conditional writes: create UID record with `attribute_not_exists(SK)` before copy.
- [x] Finalize UID record only after successful APPEND (`PENDING -> DONE`).

## 6) Gmail incremental read strategy
- [x] Select INBOX, read `UIDVALIDITY`.
- [x] If unchanged: fetch UIDs greater than `last_uid`; retrieve RFC822 for new messages.
- [x] If changed: run fallback window (ex: 24h via `SEARCH SINCE`), dedupe by Message-ID and/or SHA256 stored in DynamoDB, then reset watermark.
- [x] Never delete/move/label/modify Gmail messages.

## 7) Outlook destination write strategy
- [x] Connect to Outlook IMAP once per run where possible; reuse across routes.
- [x] Ensure each route target folder exists; create or fail clearly based on config.
- [x] APPEND raw RFC822 as-is; default to unread unless configured.

## 8) Sync engine behavior
- [x] Process routes independently within a single invocation.
- [x] On per-message APPEND failure: record `FAIL#...`, continue with remaining messages.
- [x] Add bounded retries with exponential backoff for transient IMAP/network errors.
- [x] Add `--dry-run` to log candidate copies without APPEND.

## 9) Runtime and operations
- [ ] CLI modes:
- [x] `run-once`
- [x] `lambda` (event-driven handler for scheduled execution)
- [x] EventBridge schedule every `5 minutes` to invoke Lambda.
- [x] Ensure Lambda timeout/memory are sized for worst-case batch and IMAP latency.
- [x] Ensure idempotent behavior across retries/re-invocations.
- [x] Structured JSON logging with `run_id` per cycle.

## 10) Tests (pytest)
- [x] DynamoDB idempotency conditional write/finalize behavior.
- [x] UIDVALIDITY change and fallback resync logic.
- [x] RFC822 SHA256 + Message-ID extraction.
- [ ] Multi-route isolation (state for one route does not affect another).

## 11) CI/CD automation (GitHub Actions -> AWS)
- [x] Add workflow to run lint/tests on pull requests and pushes.
- [x] Add deployment workflow to auto-deploy on push/commit to the deployment branch (ex: `main`).
- [x] Use GitHub OIDC to assume AWS IAM role (prefer over long-lived AWS keys).
- [x] Build/package Lambda artifact, then deploy via SAM/CDK/Terraform.
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
- [x] Base: `AWS_REGION`, `DYNAMODB_TABLE`, `SYNC_INTERVAL_SECONDS=300`, `LOG_LEVEL=INFO`
- [ ] Lambda: `AWS_LAMBDA_FUNCTION_NAME` (runtime-detected optional), timeout/memory/env configuration documented.
- [x] Secret storage: define whether tokens come from env vars, AWS Secrets Manager, or SSM Parameter Store.
- [ ] GitHub Actions secrets/vars:
- [x] `AWS_ROLE_ARN` (OIDC assume role target)
- [x] `AWS_REGION`
- [ ] deployment environment name and branch mapping
- [x] Outlook shared mailbox: `OUTLOOK_EMAIL`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` (if used), `MS_TENANT=consumers`, `MS_REFRESH_TOKEN`
- [x] Route-level Gmail creds per source account (in route config): `GMAIL_EMAIL`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, plus `OUTLOOK_TARGET_FOLDER`
