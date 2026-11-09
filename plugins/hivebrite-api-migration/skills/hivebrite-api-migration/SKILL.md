---
name: hivebrite-api-migration
description: Migrate code that calls the Hivebrite Admin API v1, v2 or v3 (switched off on 15 February 2027) to the new API stack, in any language. Scans the codebase for every legacy call, token request and refresh-token path, rewrites them to Service App authentication and the v3.1 or v4 endpoints, applies the response-shape changes that fail silently, lists the Back Office permissions to grant, and proves the result by re-scanning to zero legacy calls, running a sandbox smoke test and diffing legacy versus new response shapes. Two targets - "v3.1" (default, the smallest change that clears the deadline) or "v4" (move each endpoint straight to its v4 replacement where one exists). Use when asked to migrate a Hivebrite integration or script, "move to v3.1", "move to the new Hivebrite API", fix a 401 or 403 after switching, or plan a move to Admin API v4.
---

# Hivebrite Admin API migration (v1 / v2 / v3 → v3.1+)

Hivebrite Admin API **v1, v2 and v3 stop working on 15 February 2027**. The migration is mechanical:
the same handful of changes apply to every integration, whatever the language or HTTP client. This skill
makes it a pipeline: **scan → rewrite → re-scan to zero → smoke test → shape diff → report.**
The scripts do the finding and the proving; you do the rewriting, in the code's own idiom.

Source of truth, in this order:
1. the live contract at `https://docs.hivebrite.com/partner/admin/openapi.json`, which the scripts read directly
2. Hivebrite's guide *How to migrate your Admin API integration to the new API stack (v3.1+)*
3. `reference/` in this skill

If they disagree, the contract wins. Say so in the report.

The scripts download the contract themselves. If they can't (no network, a proxy, a sandbox), ask the user
to download it from https://docs.hivebrite.com/partner/admin ("Download OpenAPI Document") into the
repository, then pass it: `scan.py --spec openapi.json`, `v4_successors.sh -f openapi.json`. Without it,
`--target v4` can't be verified, and the endpoint lists in `reference/` are only a fallback that may be
out of date: say which one you used.

Requirements: `python3` (3.8+) and `curl`. `jq` is needed only for `scripts/v4_successors.sh`.

On Windows, or without Python, in this order:
1. **WSL or Git Bash**: every script runs as written.
2. **Python but no bash**: run the `.py` scripts with `py -3` instead of `python3`. Skip
   `v4_successors.sh`: `scan.py` already fills the v4 successor and sunset columns from the contract.
   Port `smoke-test.sh` to PowerShell (`Invoke-RestMethod`): same steps and exit codes, the client id and
   secret read from `$env:HB_CLIENT_ID` and `$env:HB_CLIENT_SECRET`, never from arguments, never printed.
3. **No Python**: ask the user to install it (python.org or `winget install Python.Python.3.12`, no admin
   rights needed). If they can't, do not port `scan.py`: search the code with `Select-String` or `grep` for
   the patterns in `reference/interface-changes.md` and the legacy prefixes `/api/admin/v1`, `/v2`,
   `/v3`, `oauth/token`, `grant_type`, and tell the user the inventory is a manual search, not a
   scan. `compare.py` can be ported like `smoke-test.sh`: GET requests only, key paths and types
   printed, never values.

Scope: code in a repository. An integration built on a platform such as Tray, Make or Workato has no
code to scan: point the user to the migration guide, and tell them to refresh each step's cached
response sample, or the field picker keeps offering `school_name` and `topics`.

## Target

| `--target` | Result |
|---|---|
| `v3.1` (default) | Same paths and parameters. Auth, host, prefix and a few response shapes change. The smallest diff that clears the deadline. |
| `v4` | Endpoints that have a v4 successor move to v4 now (read `reference/v4-mode.md`); the rest go to v3.1. One migration instead of two, since each v3.1 endpoint with a successor is deprecated and later removed (the API reference gives each removal date). |

Both targets move the **v4-only** endpoints: push notifications, allowed domains, and audit logs
(the contract sunsets v3.1 audit logs on 15 Feb 2027).
If the user gave no target, ask once; default to `v3.1`. When the scan reports endpoints that are
already deprecated on v3.1 (the scan prints their removal date; events, news and organizations are among
them), say so while choosing: on `v3.1` those modules need a second migration before their removal date, so recommend `v4`
for them.

## Pipeline

### 1. Scan
```bash
inventory="$(mktemp -d)/hb-inventory.json"   # private to the user, not a shared path
python3 scripts/scan.py <repo> --target <v3.1|v4> --json "$inventory"
```
The scan prints a table: each endpoint call site (file:line, version, method, legacy path), its target
path, the interface change it needs, its v4 successor and sunset date. It also lists the calls already
on v3.1. The `change` column says what each one needs: **V1→V2** (field changes), **V4-ONLY** (no v3.1
path), **V4-REQUIRED** (the v3.1 endpoint is removed with v1-v3), **V4-MOVE** (`--target v4` and a
successor exists), **CHECK** (version unknown). It also lists every base URL,
token call, password grant, refresh-token use, body `status` read and v1 field read it finds.
- It auto-detects base-URL constants (`BASE = "https://x.hivebrite.com/api/admin/v1"`) and follows
  paths built from them. If the base URL comes from an env var or config file the scan cannot see,
  pass `--base-var NAME`.
- Rows marked *(probable)* are paths assembled from a constant. Confirm each one by reading the code.
- Also grep for anything the scan may miss (`hivebrite`, the community hostname) and add it to the inventory.
- Rows marked **CHECK** have an API version the scan can't read (it comes from configuration). Find
  the version in the config; the change applies only if it is v1.
- Lines marked **(check)** are a refresh token or password in a file with no legacy Hivebrite call:
  usually another provider's auth (Salesforce, Google...). Leave them alone unless they serve Hivebrite.

The exit code says where the code stands:
- **1**: legacy usage found, or calls left to move to v4. This is the normal start. Code already on
  v3.1 can still get 1: an endpoint marked V4-REQUIRED, or any successor under `--target v4`.
- **0**: the new stack is in use, nothing legacy is left and, with `--target v4`, nothing left to move to
  v4. The code is already migrated: say so and stop.
- **4**: `--target v4` without the contract: nothing legacy is left, but the v4 moves can't be checked.
  Get the contract (below) and re-run with `--spec`.
- **3**: no Hivebrite API usage recognised. This never means migrated. Check the directory, find
  where the base URL and token call are defined, and re-run with `--base-var NAME`.

Show the user the inventory and the plan (target, files to change, Back Office modules) before
editing.

### 2. Rewrite: the stack change (every integration)
Exact rules in `reference/contract.md`. Make one change per concern, in the code's existing style:
1. **Config**: introduce `HIVEBRITE_AUTH_HOST` and `HIVEBRITE_API_HOST` (or the repo's equivalent),
   plus the client id and secret read from the environment or secret store. Sandbox versus production
   becomes a config switch.
2. **Token**: `POST https://$AUTH_HOST/oauth2/token`, HTTP Basic `client_id:client_secret`, form body
   `grant_type=client_credentials&audience=partner`. Remove admin email, password and scope.
   Without `audience=partner`, every call returns 401.
3. **Token lifecycle**: delete refresh-token code. Cache the token and fetch a new one about 30 s before
   `expires_in` runs out. Write one small helper, then route every call through it.
4. **Base URL**: `https://<community>.hivebrite.com/api/admin/vX/`, or the community's own domain for a
   white-label community, → `https://$API_HOST/admin/v3.1/`. The new hosts are the same for every community.
   Change it where it is defined; rewrite literals only where the path is hard-coded.
5. **Errors**:
   - take the status from the HTTP response, never from a body `status` field (v3.1 has none)
   - branch on `error.code`, never on `error.message`
   - add a distinct **403** branch: a missing Back Office permission, not an expired token, so do not
     refresh-and-retry on 403
   - on **429**, wait and retry: `Retry-After` doesn't reach the client, so use the seconds named in the
     message or back off; never auto-retry a 5xx on a write
   - `error.message` often holds the legacy error body as a JSON string: log it, never branch on it
   - log `X-Request-Id`
6. **One switch**: a v3.1 token is refused on the legacy API and the other way round, so the token
   helper and the base URL move in the same change.

### 3. Rewrite: interface changes (only the rows that need them)
For every row whose `change` column is set, apply `reference/interface-changes.md`:
- **V1→V2** (`/educations`, `/topics`, `DELETE /users/{id}` called on v1): rename the fields that are
  read, use the keyed `custom_attributes` lookup, use the `groups` root key, and accept 202 without depending on the body.
  On the flat `PUT /educations/{id}`, rename the fields in the **request body** too: a v1-shaped body
  returns 200 and silently drops them. And the flat collection ignores `education_key`: a v1 call that
  looks an education up by external id can update or delete the wrong one (`interface-changes.md`).
- **V4-ONLY / V4-REQUIRED**: move to the v4 endpoint shown.
- With `--target v4`: every row with a successor, following `reference/v4-mode.md`, one module at a time.

Follow each changed response through the code: a renamed key breaks every place that reads it, not
only the line that makes the call. Search for each old field name.

### 4. Re-scan to zero
Run `scripts/scan.py` again, with the same `--target`. **Done means exit code 0**: no legacy URL, token call, password grant or
refresh token is left, and the new stack is in use. Exit 3 here means the rewrite removed the calls the
scan could see without it recognising the new ones: read the code before calling it done. Any remaining *old_field_name* or *body_status* lines must each be justified:
they belong to an endpoint that kept its v1 interface, such as the per-user educations, or they read
something other than a Hivebrite response. Fix or explain each one.

### 5. Prove it, on a sandbox first
```bash
export HB_ZONE=eu-sandbox HB_CLIENT_ID=... HB_CLIENT_SECRET=...      # user sets these; never echo them
scripts/smoke-test.sh users?per_page=1 <one read path per module the code touches>
export HB_LEGACY_HOST=https://<legacy host> HB_LEGACY_TOKEN=...   # <community>.hivebrite.com, or its own domain if white-label
python3 scripts/compare.py /api/admin/v1/educations?per_page=5 /api/admin/v2/topics?per_page=5 ...
```
- **smoke-test**: token → `/me` → every listed read path must return 200. A 403 names a missing
  Back Office module: give the user the exact module to enable (`reference/contract.md`).
- **compare.py**: calls each GET on legacy and on v3.1 and prints key paths that disappeared, appeared,
  or changed type, plus any root-key change. Run it on every GET endpoint in the inventory. Any key
  "only in legacy" that the code reads is a bug the rewrite missed.
- Then run the integration's own tests or a dry run against the sandbox.
- Production only when the user says go.

The user exports the credentials in their own shell. Never ask for a secret in the conversation,
never print one, never write one to a file.

### 6. Report
- inventory before → after (scan output)
- the diff summary per concern
- the Back Office module checklist
- smoke-test and compare results, with `X-Request-Id`s and no tokens
- everything still on v3.1 that is deprecated, with its sunset date
- any place where `reference/` disagreed with the live contract

## Guardrails
- Minimal, reviewable diff in the repository's own style. This is a migration, not a refactor.
- Sandbox before production; no deploy, release or production run without an explicit go.
- Secrets live in the environment or a secret manager, never in code, args, logs or chat.
- GET-only verification: the scripts never write to Hivebrite. Test writes by hand, on a sandbox record.
- If something fails and the reason is unclear, stop and give the user the `X-Request-Id` for a ticket
  at support.hivebrite.com rather than retrying.
