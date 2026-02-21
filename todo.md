# Gmail -> Outlook IMAP Sync (Python) TODO

You are Codex CLI acting as a senior Python engineer. Build a production-ready Python app that syncs email FROM a Gmail inbox INTO a specific folder in an Outlook.com (consumer) IMAP mailbox. This must be IMAP-to-IMAP (no Gmail API, no Microsoft Graph).

## Core behavior
- [ ] Every 5 minutes, fetch NEW messages in Gmail INBOX and copy them into a target Outlook folder via IMAP APPEND.
- [ ] Do not delete, move, label, or modify Gmail messages.
- [ ] Preserve full fidelity by copying the raw RFC822 content (headers/body/attachments) as-is.
- [ ] Ensure idempotency: never create duplicates in Outlook across repeated runs or restarts.

## Critical safety requirement
- [ ] Store state ONLY in DynamoDB.
- [ ] If DynamoDB is unavailable for any reason (network/auth/throttle), FAIL SAFE:
- [ ] Do nothing (do not connect to IMAP, do not copy messages).
- [ ] Exit; next scheduled run retries.

## Auth (modern reality)
- [ ] Implement OAuth2 modern auth for BOTH providers:
- [ ] Gmail IMAP using SASL XOAUTH2.
- [ ] Outlook.com IMAP using OAuth2 (XOAUTH2).
- [ ] Token handling:
- [ ] Store refresh tokens in environment variables or secrets file (do not commit).
- [ ] Auto-refresh access tokens at runtime.
- [ ] Provide one-time interactive helper CLI command to obtain/refresh tokens locally (device code or local web callback).
- [ ] Support headless runtime using refresh tokens.

## State / DynamoDB schema
- [ ] Use a single DynamoDB table.
- [ ] Partition key (PK): `ACCOUNT#<gmail_address>#DEST#<outlook_address>`
- [ ] Sort key (SK):
- [ ] `WATERMARK` -> attributes: `uidvalidity`, `last_uid`, `updated_at`
- [ ] `UID#<uidvalidity>#<gmail_uid>` -> attributes: `copied_at`, `message_id_header` (optional), `rfc822_sha256`, `ttl`
- [ ] `FAIL#<uidvalidity>#<gmail_uid>` -> attributes: `last_error`, `retry_count`, `updated_at`, `ttl`
- [ ] Use conditional writes for idempotency:
- [ ] Before copying, `PutItem UID#...` with `ConditionExpression attribute_not_exists(SK)`; if condition fails, skip as duplicate.
- [ ] Only after successful APPEND should the `UID#` item be finalized (or use two-phase status `PENDING -> DONE`).

## Gmail IMAP incremental strategy
- [ ] Select INBOX and read UIDVALIDITY.
- [ ] If UIDVALIDITY differs from stored value:
- [ ] Fallback resync window (e.g., last 24h) by IMAP `SEARCH (SINCE ...)`.
- [ ] Dedupe using `Message-ID` header and/or RFC822 SHA256 in DynamoDB.
- [ ] Set new `uidvalidity` and `last_uid` appropriately.
- [ ] Normal run:
- [ ] SEARCH for UIDs greater than `last_uid` (or use UIDNEXT logic).
- [ ] FETCH RFC822 for each new UID.

## Outlook IMAP destination
- [ ] Connect to Outlook.com IMAP.
- [ ] Ensure target folder exists; if not, create it or fail with clear message (config option).
- [ ] APPEND RFC822 into that folder.
- [ ] Prefer leaving messages unread (do not set `\Seen`) unless configured.

## Scheduling / runtime
- [ ] Support run-once mode (single sync).
- [ ] Support daemon mode (loop every 300 seconds with graceful shutdown).
- [ ] Provide Dockerfile suitable for AWS ECS and Synology Container Manager.
- [ ] Provide AWS deployment docs:
- [ ] EventBridge schedule -> ECS task recommended.
- [ ] DynamoDB table + TTL + IAM least privilege policy.
- [ ] Provide Synology deployment docs:
- [ ] `docker run` / compose examples.
- [ ] How to supply secrets as env vars or mounted files.

## Observability / reliability
- [ ] Structured JSON logs with `run_id` per cycle.
- [ ] Retries with exponential backoff for transient IMAP/network failures (bounded retries).
- [ ] If individual message APPEND fails, record `FAIL#...` and continue with other messages.
- [ ] Provide `--dry-run` to log what would be copied.

## Project layout
- [ ] Create:
- [ ] `src/main.py` (CLI)
- [ ] `src/config.py`
- [ ] `src/dynamodb_state.py`
- [ ] `src/gmail_imap.py`
- [ ] `src/outlook_imap.py`
- [ ] `src/oauth_gmail.py`
- [ ] `src/oauth_microsoft.py`
- [ ] `src/sync_engine.py`
- [ ] `src/imap_utils.py`
- [ ] `src/logging_utils.py`
- [ ] `tests/` with pytest coverage for:
- [ ] DynamoDB idempotency logic
- [ ] UIDVALIDITY change behavior
- [ ] RFC822 hashing + Message-ID extraction

## Configuration env vars
- [ ] `GMAIL_EMAIL`
- [ ] `OUTLOOK_EMAIL`
- [ ] `OUTLOOK_TARGET_FOLDER`
- [ ] `AWS_REGION`
- [ ] `DYNAMODB_TABLE`
- [ ] `SYNC_INTERVAL_SECONDS=300`
- [ ] `LOG_LEVEL=INFO`
- [ ] Tokens:
- [ ] `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`
- [ ] `MS_CLIENT_ID`, `MS_CLIENT_SECRET` (if applicable), `MS_TENANT=consumers`, `MS_REFRESH_TOKEN`
- [ ] Provide `.env.example` and `README`.

## Deliverables
- [ ] Complete runnable codebase
- [ ] `Dockerfile` + optional `docker-compose.yml`
- [ ] `README` with step-by-step OAuth setup for:
- [ ] Google Cloud project + IMAP OAuth scopes
- [ ] Azure app registration for Outlook.com IMAP OAuth (`tenant=consumers`) and required permissions
- [ ] Start by printing the full file tree, then generate code for each file.
