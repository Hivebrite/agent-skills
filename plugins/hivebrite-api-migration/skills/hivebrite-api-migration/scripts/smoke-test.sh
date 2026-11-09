#!/usr/bin/env bash
# v3.1 smoke test: checks the new authentication and API access end to end,
# independent of the integration's own language/stack. Only `curl` is required.
#
# Usage:
#   export HB_ZONE=eu-sandbox HB_CLIENT_ID=... HB_CLIENT_SECRET=...
#   smoke-test.sh [read_path ...]
#
#   HB_ZONE    : eu | us | apac | ch | eu-sandbox | us-sandbox
#   The client id and secret are read only from the environment, and are handed to curl on its standard
#   input, so they never appear in the shell history or in the process list. So does the access token.
#   read_path  : zero or more READ-ONLY endpoints to GET (no leading /admin/v3.1/).
#                NONE   -> auth-only mode: token + aud + /me (+ a users read, informational).
#                PATHS  -> STRICT pre-flight: EVERY listed path must return 200 or exit 1.
#                          Run this after the Service App + config are in place and
#                          BEFORE switching the integration — pass the GET/list endpoint of each
#                          Back Office module the integration touches, so a 403 (missing permission)
#                          surfaces while nothing has been switched yet.
#
# Exit 0 = auth stack OK (+ every listed read path 200 in strict mode).
# Non-zero = a step failed. GET-only: never changes data. Nothing is written to disk.
# Run on a sandbox zone first.

set -u

zone="${HB_ZONE:-}"; client_id="${HB_CLIENT_ID:-}"; client_secret="${HB_CLIENT_SECRET:-}"

if [ -z "$zone" ] || [ -z "$client_id" ] || [ -z "$client_secret" ]; then
  echo "usage: HB_ZONE=<eu|us|apac|ch|eu-sandbox|us-sandbox> HB_CLIENT_ID=... HB_CLIENT_SECRET=... smoke-test.sh [read_path ...]" >&2
  exit 2
fi
paths=("$@"); strict=1
if [ "${#paths[@]}" -eq 0 ]; then paths=("users?per_page=1"); strict=0; fi
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found" >&2; exit 2; }

case "$zone" in
  eu)          AUTH="auth.eu.hivebrite.com";         API="api.eu.hivebrite.com" ;;
  us)          AUTH="auth.us.hivebrite.com";         API="api.us.hivebrite.com" ;;
  apac)        AUTH="auth.apac.hivebrite.com";       API="api.apac.hivebrite.com" ;;
  ch)          AUTH="auth.ch.hivebrite.com";         API="api.ch.hivebrite.com" ;;
  eu-sandbox)  AUTH="auth.preprod.hivebrite.com";    API="api.preprod.hivebrite.com" ;;
  us-sandbox)  AUTH="auth.sandbox.us.hivebrite.com"; API="api.sandbox.us.hivebrite.com" ;;
  *) echo "ERROR: unknown zone '$zone'" >&2; exit 2 ;;
esac

# curl reads its credentials from a config on standard input, never from its arguments.
curl_cfg_value() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
curl_basic() { printf 'user = "%s:%s"\n' "$(curl_cfg_value "$client_id")" "$(curl_cfg_value "$client_secret")" | curl -K - "$@"; }
curl_bearer() { printf 'header = "Authorization: Bearer %s"\n' "$(curl_cfg_value "$access_token")" | curl -K - "$@"; }

# Extract a top-level JSON string field without requiring jq.
json_field() { # $1=field $2=json
  if command -v jq >/dev/null 2>&1; then printf '%s' "$2" | jq -r ".$1 // empty" 2>/dev/null; return; fi
  printf '%s' "$2" | grep -o "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed -E "s/.*:[[:space:]]*\"([^\"]*)\"/\1/"
}

echo "zone=$zone  auth=$AUTH  api=$API"
echo "== 1) token: POST https://$AUTH/oauth2/token (client_credentials + audience=partner) =="
tok_resp="$(curl_basic -sS \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" -d "audience=partner" \
  "https://$AUTH/oauth2/token")"
access_token="$(json_field access_token "$tok_resp")"
if [ -z "$access_token" ]; then
  echo "FAIL: no access_token. Response:" >&2; echo "$tok_resp" >&2
  echo "hints: wrong AUTH host/path? missing audience=partner? bad client id/secret? wrong zone?" >&2
  exit 1
fi
echo "OK: got access_token (${#access_token} chars)"

# Decode the JWT payload to confirm aud=partner (the most common mistake). Best-effort.
payload="$(printf '%s' "$access_token" | cut -d. -f2)"
case $(( ${#payload} % 4 )) in 2) payload="${payload}==";; 3) payload="${payload}=";; esac
decoded="$(printf '%s' "$payload" | tr '_-' '/+' | base64 -d 2>/dev/null || true)"
if [ -n "$decoded" ]; then
  echo "$decoded" | grep -q '"partner"' && echo "OK: aud contains partner" \
    || echo "WARN: aud does not contain 'partner' — API calls will 401. Is audience=partner set?"
fi

echo "== 2) GET https://$API/admin/v3.1/me =="
me_body="$(curl_bearer -sS -o /dev/null -w '%{http_code}' "https://$API/admin/v3.1/me")"
if [ "$me_body" = "200" ]; then echo "OK: /me -> 200"
else echo "FAIL: /me -> $me_body (401=token/aud, 403=admin permissions, 404=wrong API host/prefix)" >&2; exit 1; fi

if [ "$strict" = 1 ]; then
  echo "== 3) STRICT pre-flight: GET each read endpoint (ALL must be 200) =="
else
  echo "== 3) read check (auth-only): GET https://$API/admin/v3.1/${paths[0]} =="
fi
fail=0
for p in "${paths[@]}"; do
  code="$(curl_bearer -sS -o /dev/null -w '%{http_code}' "https://$API/admin/v3.1/$p")"
  if [ "$code" = "200" ]; then echo "OK:   $p -> 200"; continue; fi
  if [ "$strict" = 1 ]; then
    echo "FAIL: $p -> $code (403=the admin lacks a Back Office module, see reference/contract.md; 404=wrong path or not on v3.1; 401=token/aud) — fix BEFORE switching" >&2
    fail=1
  else
    echo "NOTE: $p -> $code — auth stack itself is proven by /me; this is a module-permission/path signal only."
  fi
done
if [ "$fail" != 0 ]; then
  echo "== PRE-FLIGHT FAILED: a read endpoint the integration needs is not 200 — do NOT switch until fixed ==" >&2
  exit 1
fi
if [ "$strict" = 1 ]; then extra=" + all listed read endpoints 200"; else extra=""; fi
echo "== smoke test complete: token and API access verified$extra for zone '$zone' =="
