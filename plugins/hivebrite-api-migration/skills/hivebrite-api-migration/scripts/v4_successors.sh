#!/usr/bin/env bash
# For each v3.1 path, report what the live Admin API contract says about it:
# deprecated or not, the v4 operation that replaces it, and its sunset date.
#
# Usage: v4_successors.sh [-f spec.json] /admin/v3.1/news /admin/v3.1/network_events/{id} ...
#   Paths may be given with or without the /admin/v3.1 prefix. A trailing * matches sub-paths.
# Needs curl and jq. Read-only; calls no Hivebrite API, only downloads the public contract.
set -euo pipefail
command -v jq >/dev/null || { echo "jq is required" >&2; exit 2; }
spec=""
if [ "${1:-}" = "-f" ]; then spec="$2"; shift 2; fi
if [ -z "$spec" ]; then
  # A per-user cache, readable only by its owner (shared with scan.py), not a shared temporary file.
  cache="${XDG_CACHE_HOME:-$HOME/.cache}/hivebrite-api-migration"
  mkdir -p "$cache" && chmod 700 "$cache"
  [ -O "$cache" ] || { echo "refusing to use $cache: owned by another user" >&2; exit 2; }
  spec="$cache/admin-openapi.json"
  if [ ! -s "$spec" ] || [ -n "$(find "$spec" -mmin +720 2>/dev/null)" ]; then
    curl -sSf -A "hivebrite-api-migration-skill" -o "$spec" https://docs.hivebrite.com/partner/admin/openapi.json
  fi
fi
[ "$#" -gt 0 ] || { echo "usage: v4_successors.sh [-f spec.json] <v3.1 path> ..." >&2; exit 2; }
printf '%-7s %-55s %-11s %-11s %s\n' METHOD "V3.1 PATH" DEPRECATED SUNSET "V4 SUCCESSOR"
for p in "$@"; do
  p="${p#/admin/v3.1}"; p="/admin/v3.1/${p#/}"
  jq -r --arg p "$p" '
    (.paths | to_entries | map(.key as $k | .value | to_entries[]
       | select(.value | type == "object" and has("operationId"))
       | {id: .value.operationId, m: (.key|ascii_upcase), path: $k}) | INDEX(.id)) as $ops
    | .paths | to_entries[]
    | select(if ($p|endswith("*")) then (.key|startswith($p|rtrimstr("*"))) else .key == $p end)
    | .key as $k | .value | to_entries[]
    | select(.key|test("^(get|post|put|patch|delete)$"))
    | .value as $o
    | ($o["x-successor"] // null) as $s
    | [ (.key|ascii_upcase), $k,
        (if $o.deprecated then ($o["x-deprecated-date"] // "yes") else "no" end),
        ($o["x-sunset-date"] // "-"),
        (if $s == null then "- (stays on v3.1)" else (($ops[$s] // {m:"?",path:$s}) | "\(.m) \(.path)") end)
      ] | @tsv' "$spec" | awk -F'\t' '{printf "%-7s %-55s %-11s %-11s %s\n",$1,$2,$3,$4,$5}'
  if ! jq -e --arg p "$p" '.paths | keys | any(. == $p or (($p|endswith("*")) and startswith($p|rtrimstr("*"))))' "$spec" >/dev/null; then
    printf '%-7s %-55s %s\n' "?" "$p" "not in the contract: check the path, or it is v4-only (see reference/interface-changes.md)"
  fi
done
