# WhatsPilot — Code Optimization Report

Date: August 6, 2026

Full pass over the backend (FastAPI/SQLite) and frontend (dashboard.html, settings.html) looking for performance issues, dead/duplicate code, and correctness bugs. All fixes below were verified with `python3 -m py_compile`, the full pytest suite (170 tests passing), and a JS syntax check.

## Fixes implemented

**N+1 query in `analytics/customer_stats.py` — `get_customer_stats()`.** This function runs on every dashboard load, every search keystroke, and every 60-second automation tick. It previously ran two extra queries per customer (latest message, lead record), so a business with 50 customers meant 100+ queries per call. Both are now batched with `WHERE ... IN (...)` lookups before the loop, dropping the query count from `2 + 2N` to a constant ~4 regardless of customer count.

**Unsafe, dead-code duplicate route in `api/automation.py`.** Two endpoints existed for enabling/disabling a rule: a validated `PATCH /automation/rules/{id}/enabled` that nothing in the frontend called, and a `PUT` version (the one `dashboard.html`'s `toggleRule()` actually calls) that took a raw unvalidated dict body — a missing `enabled` key would throw an unhandled `KeyError` → 500, and toggling a nonexistent rule silently no-op'd instead of returning 404. Consolidated to one `PUT` route with `EnableRuleRequest` validation and a proper 404 check; removed the dead `PATCH` route.

**Duplicate `deleteRule()` function in `dashboard.html`.** Two full definitions existed under the same name — a leftover plain version (alert-based, no animation) from before the rule-editor redesign, and the current one with the fade-out delete animation. JS silently let the second declaration win, so the first was 100% dead code that just added confusion. Removed the stale one.

**No debounce on the dashboard search box.** `customerSearch`'s `onkeyup` fired a full server round trip (customer list query + an unindexed `LOWER(content) LIKE '%q%'` scan over conversation history) on every keystroke. Added a 300ms debounce (`debouncedSearchCustomers()`) so a burst of typing collapses into one request after the user pauses — standard search UX, and meaningfully less DB load for fast typers or pasted queries.

**`print()` instead of `logging` in the automation engine.** `automation/runner.py` (runs every 60s via APScheduler) and `automation/evaluator.py` wrote verbose debug output straight to stdout via `print()`, inconsistent with the rest of the app's `logging.getLogger(__name__)` pattern (e.g. `automation/jobs.py`). Converted both to `logger.info()`/`logger.debug()`/`logger.exception()`, so automation output can now be filtered/leveled/redirected like everything else instead of always printing.

## Flagged, not changed

**`automation/database.py` vs `automation/manager.py`.** Both modules define their own `create_rule`, `update_rule`, `delete_rule` (near-identical implementations). Production code (the API layer) only uses `manager.py`'s versions; `database.py`'s versions are used exclusively by `tests/test_reminders.py`, which imports them directly. This is genuine duplication, but removing it means rewriting that test file's imports — left as-is since it's moderate-risk for no runtime benefit (dead code only in the sense of "not called by the app," but still exercised by tests). Worth cleaning up in a future pass if `test_reminders.py` gets reworked anyway.

## Checked and found clean

- No unpooled `sqlite3.connect()` calls anywhere in application code — everything goes through `database/db.py`'s connection pool.
- All routes in `api/customer.py` and `api/automation.py` correctly wrap blocking DB calls in `run_in_threadpool`.
- No other duplicate function definitions across `dashboard.html`, `settings.html`, `analytics.html`, or `followups.html`.
- CSS selector reuse in `dashboard.html` is low and consistent with earlier CSS cleanup work (shared badge/status classes styled once, not copy-pasted blocks).
- `automation/runner.py`'s hardcoded business ID (`+14155238886`) is not a bug — the app is intentionally single-tenant, and that value is the sole business ID used consistently everywhere.

## Verification

- `python3 -m pytest tests/ -q` → 170 passed.
- `python3 -m py_compile` on every changed Python file → clean.
- `node --check` on the extracted `dashboard.html` script block → clean.

---

# Round 2 — August 7, 2026

Follow-up pass after the multi-tenancy (Phase 1), business registry (Phase 2), and admin login (Phase 3) work — covering the new/changed backend modules (`crm/customer_mapping.py`, `automation/runner.py`, `automation/evaluator.py`, `api/businesses.py`, `auth.py`, `middleware.py`, `main.py`) and templates (`businesses.html`, `login.html`, `dashboard.html`'s header). Verified with `python3 -m py_compile`, the full pytest suite (271 tests passing, up from 268), a JS syntax check on every template's script block, and a live run against a throwaway copy of the real production databases.

## Fixes implemented

**Pooled-connection leak in `crm/customer_mapping.py` — `get_customers()`.** `conn.close()` was written *after* the function's `return` statement, making it unreachable dead code - every call permanently checked a connection out of `database/db.py`'s 5-connection pool and never returned it. `_ConnectionPool.get()` blocks once every connection is checked out and none are free, so the 6th call in a row (without some other code returning a connection first) would have hung forever rather than erroring visibly. Moved `conn.close()` before the `return`. Added a regression test that calls it 20 times in a row.

**N+1 query multiplied across businesses in the automation engine.** `evaluate_rule()` (`automation/evaluator.py`) called `get_customer_stats()` - itself ~4 queries - internally, once per rule. `automation/runner.py` runs every rule for every active business every 60 seconds, so with up to 5 rules per business this refetched the *same* business's customer list up to 5 times per tick; multiplied across every active business once Phase 1 made the runner loop over all of them (not just one hardcoded business), this scaled linearly with tenant count for no reason. `evaluate_rule()` now takes an optional `customers` param; `runner.py` fetches it once per business and reuses it across that business's rules. Verified live against real data: `get_customer_stats` now runs exactly once per active business per tick, regardless of rule count.

**Two round trips instead of one in `set_business_status()`/`delete_business()`.** Both did a `SELECT ... WHERE user_id = ?` existence check before the `UPDATE`/`DELETE`, then a second query to actually make the change. Replaced with a single `UPDATE`/`DELETE` and a check on `cursor.rowcount`, which already says whether a matching row existed. (`register_business()` keeps its upfront check - it has to know *before* generating a `business_id` whether this is a genuinely new business, which an after-the-fact rowcount can't distinguish from "just inserted".)

**Fail fast on missing admin/session config.** `main.py` now raises a clear `RuntimeError` at startup if `SESSION_SECRET_KEY`, `ADMIN_USERNAME`, or `ADMIN_PASSWORD_HASH` aren't set, instead of starting successfully and only failing later - Starlette's `SessionMiddleware` accepts `secret_key=None` with no error at construction time, so a forgotten env var would previously have surfaced as a confusing crash on the first login attempt rather than an immediate, actionable one at boot.

**`print()` instead of `logging` in five more places.** Consistent with Round 1's fix to `automation/runner.py`/`automation/evaluator.py`, converted the remaining stragglers: `automation/executor.py` (runs every automation tick - action execution and failures are now `logger.debug`/`logger.exception` instead of invisible-to-log-filtering `print()`), `automation/actions/create_reminder.py`, `automation/scheduler.py` (already imported `logger` in the same file but didn't use it for its job-listing output), and `ai/lead_ai.py` (runs on every incoming WhatsApp message - a swallowed AI error used to just vanish into stdout with no traceback; now `logger.exception()` captures it properly). Also removed a `print()` in `automation/service.py` that duplicated information `add_job()` already logs one line earlier.

## Flagged, not changed

**`automation/database.py` vs `automation/manager.py` duplication has gotten more expensive.** Round 1 flagged this as low-value to fix. Since then, Phase 1 made both modules independently business_id-aware (each has its own migration-adjacent logic), so the duplication now carries real risk of the two copies drifting out of sync rather than just being redundant code. Still deferred - unifying them means reworking `tests/test_reminders.py`'s imports and is a bigger, riskier change than fits a routine optimization pass, but this is worth scheduling deliberately rather than revisiting opportunistically.

**No index on `leads.status`.** `get_rule_performance()` and `get_won_revenue_trend()` both filter `leads` by `status = 'Closed Won'` with a full table scan. `customer_phone` is the primary key (indexed automatically), but `status` isn't. Fine at current data volumes; worth adding if a business's lead count grows into the thousands.

**`customer_numbers.status`/`business_id` have no index.** Same reasoning as above but lower priority still - this table is sized by number of *businesses*, not customers, so it'll stay small even as the product scales.

**`print()` in ingestion scripts (`crawler.py`, `website_ingest.py`, `incremental_ingest.py`, `website_manager.py`).** These read as intentional progress narration for a background/manual job rather than swallowed errors on a hot path, unlike the automation-engine cases above - left as-is to keep this round's scope to genuine bugs and hot-path code.

## Checked and found clean

- No duplicate JS function names in `dashboard.html` (94 function definitions, all unique).
- `node --check` clean on every template's extracted script block, including the three added/changed since Round 1 (`businesses.html`, `login.html`, `dashboard.html`).
- `tests/conftest.py`'s `isolated_db` fixture's init-function list matches `main.py`'s exactly - nothing missing.
- All new API routes (`api/businesses.py`, `api/auth.py`) correctly wrap blocking calls in `run_in_threadpool`.
- `automation_rules.business_id` and `automation_rule_executions.business_id` (added in Phase 1) are both properly indexed.

## Verification

- `python3 -m pytest tests/ -q` → 271 passed (3 new regression tests: pooled-connection leak, `evaluate_rule(customers=...)` skips the internal fetch, runner calls `get_customer_stats` exactly once per business).
- `python3 -m py_compile` on every changed Python file → clean.
- `node --check` on every template's extracted script block → clean.
- Live run against a throwaway copy of the real production databases: confirmed `get_customer_stats` is called exactly once per active business regardless of rule count, `register_business`/`set_business_status`/`delete_business` behave identically to before for both existing and missing `user_id`, and the app's admin/session config validates cleanly at import time.

---

# Round 3 — August 7, 2026

Follow-up pass after the business-owner OTP login work (Phase 3 completion) — covering the new modules (`verify.py`), new routes (`api/auth.py`'s `/business-login` set), the tenant-isolation retrofit across 8 API files, and the two new templates (`business_login.html`, `business_login_verify.html`). Verified with `python3 -m py_compile` on every changed file, the full pytest suite (315 tests passing, up from 271), and a real login performed live by the user against a configured Twilio Verify Service SID.

## Fixes implemented

**Blocking DB calls not wrapped in `run_in_threadpool` — `auth.py`'s `enforce_tenant_access_for_customer()` and `resolve_dashboard_user_id()`.** Both ran a synchronous sqlite3 query directly inside a function called from `async def` route handlers, violating this codebase's own established convention (every other blocking DB call goes through `run_in_threadpool` — see e.g. `api/dashboard.py`'s module docstring). Left as-is, each of these would block FastAPI's event loop for the duration of the query on every customer-detail page load or dashboard/analytics/settings page render. Fixed by making both `async def` and wrapping their DB-touching branches in `await run_in_threadpool(...)`. `enforce_tenant_access_for_customer()`'s two sequential queries (business lookup, then customer lookup) were also combined into one via a new single-query JOIN, `get_owning_business_user_id()`. Updated all 13 call sites across `api/customer.py` (9), `api/ai.py` (1), and `api/misc.py` (3) to `await` the now-async functions.

**Dead no-op JS in `settings.html`'s `window.onload`.** Read `#userId`'s value straight back out of the input and wrote it right back in — a leftover from before the field was server-rendered from the session. Harmless but confusing, and it shadowed the fact that `#userId` used to be hardcoded to the Sandbox number in this same handler (a real bug from an earlier round, already fixed). Removed, with a comment explaining where the value now comes from.

## Flagged, not changed

**No index on `customer_numbers.whatsapp_number` / `owner_whatsapp_number`.** `get_business_by_login_number()` (used on every business-login attempt) filters on both columns with a full table scan. Same reasoning as Round 2's note on this table: `customer_numbers` is sized by number of *businesses*, not customers, so it stays small even as the product scales — low priority.

## Checked and found clean

- `verify.py` and `api/auth.py`'s `/business-login` routes correctly wrap every Twilio call and DB lookup in `run_in_threadpool`; the OTP-pending phone number is tracked server-side in the session (not a client-supplied hidden field), so `/business-login/verify` can't be reached with a phone number that was never actually sent a code.
- No unpooled `sqlite3.connect()` calls introduced anywhere this session — everything goes through `database/db.py`'s pool.
- `templates/business_login.html` and `templates/business_login_verify.html` have no JS at all and no dead code.
- `templates/businesses.html`'s new "View Dashboard" button and the removal of the old `updateOwnerNumberWarning()` warning banner (superseded by the SMS-only OTP design) left no orphaned CSS, functions, or call sites.
- `twilio==9.10.9` (already in `requirements.txt`) covers the Verify API used by `verify.py` — no new dependency needed.

## Verification

- `python3 -m pytest tests/ -q` → 315 passed (44 new tests: `test_verify.py`'s 8 fake-Twilio-client tests, plus new coverage in `test_auth.py`, `test_businesses.py`, `test_tenant_isolation.py` for the login-number lookup, tenant-isolation retrofit, and async fixes).
- `python3 -m py_compile` on every changed/added Python file → clean.
- Live verification: user registered a new business (`+919962824442`), configured a real `TWILIO_VERIFY_SERVICE_SID`, and successfully logged in end-to-end through `/business-login` → SMS OTP → `/business-login/verify`.

# Round 4 — August 9, 2026

Pre-GitHub-push pass covering everything added since Round 3: the rate-limiting work (`rate_limit.py`, its wiring into `api/auth.py`'s three login-adjacent routes, and the new tests), `render.yaml`, and the env-var-driven DB/vector-store path overrides in `database/db.py` and `config.py`.

## Fixes implemented

**`rate_limit.py`'s `is_rate_limited()` auto-vivified a dict entry for every key it was ever asked about, and never removed expired/emptied ones.** Because it read via `_attempts[key]` (a `defaultdict(deque)`), simply *checking* whether a brand-new IP or phone number was rate-limited created a permanent empty-deque entry for it — and once a key's attempts all aged out of the window, the now-empty deque stayed in the dict forever. Over a long-lived process this grows `_attempts` by roughly one entry per unique visitor/phone number ever seen, unbounded. Fixed by switching to `_attempts.get(key)` (returning `False` immediately with no dict mutation if the key was never recorded), and deleting the dict entry once trimming leaves its deque empty. `record_attempt()` is unaffected — it only ever creates an entry for a key that just made a real attempt, so its growth is already bounded by actual usage, not lookups.

**No index on `customer_numbers.whatsapp_number` / `owner_whatsapp_number`.** Round 3 flagged this same gap and left it on the grounds that the table is small (one row per business, not per customer) — still true, but the two queries that hit it are on genuinely hot paths (`get_customer_by_number()` on every inbound webhook message, `get_business_by_login_number()` on every business-login attempt, called twice per successful login), and the fix is a one-line, zero-risk addition. Added `idx_customer_numbers_whatsapp_number` and `idx_customer_numbers_owner_whatsapp_number` to `init_customer_mapping()`. Applies automatically on next server start (existing `CREATE INDEX IF NOT EXISTS` pattern — no migration script needed).

## Checked and found clean

- `render.yaml` cross-checked against every `os.getenv()` call in `config.py` — all required env vars present, secrets correctly marked `sync: false`, `SESSION_SECRET_KEY` correctly uses `generateValue: true` rather than being left for manual entry.
- `database/db.py`'s `CRM_DB_PATH`/`CONVERSATION_DB_PATH` and `config.py`'s `CHROMA_DB_PATH` overrides default to the original hardcoded paths when unset, so local dev behavior is unchanged — verified no other code reads these paths independently (would have silently bypassed the override).
- `api/auth.py`'s rate-limit wiring: all three routes check `is_rate_limited()` before the sensitive work and call `record_attempt()` only after a request that was actually let through, in both the success and failure branch — no path double-counts or skips recording.
- `templates/login.html`, `templates/business_login.html`, `templates/business_login_verify.html` — all three use the same `{% if error == "ratelimited" %}` pattern with no leftover boolean-style error checks.
- `tests/conftest.py`'s autouse `_reset_rate_limits` fixture correctly resets `rate_limit`'s module-level state before and after every test — confirmed no cross-test leakage by running the full suite in default (non-`-p no:randomly`) order.
- No other module-level mutable dict/cache with unbounded-growth risk found elsewhere in the codebase (checked `automation/rule_stats.py`, `unread_manager.py`, and the connection pool in `database/db.py`, all of which key on a small, bounded set of business/customer IDs already present in the DB, not arbitrary attacker-controlled input like an IP or phone number).

## Verification

- `python3 -m pytest -q` → 325 passed, no regressions.
- `python3 -m py_compile` on `rate_limit.py` and `crm/customer_mapping.py` → clean.
- New indexes use the existing `CREATE INDEX IF NOT EXISTS` idempotent pattern already proven safe by every other index in this codebase — will apply automatically the next time the local server or production restarts, no manual migration step required.
