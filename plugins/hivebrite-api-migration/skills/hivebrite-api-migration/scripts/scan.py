#!/usr/bin/env python3
"""Inventory every Hivebrite legacy Admin API usage in a codebase, in any language.

Finds legacy base URLs, endpoint paths, the password-grant token call and refresh-token handling,
then maps each endpoint to its v3.1 path, flags the interface changes and v4-only moves, and (with
the live OpenAPI contract) the v4 successor and sunset date of each v3.1 endpoint.

It also inventories the calls already on v3.1. With `--target v4`, every endpoint (legacy or v3.1) that has
a v4 successor in the contract is reported as a move to make, and the scan is only clean once they are done.

Usage:
  scan.py <repo-dir> [--target v3.1|v4] [--base-var NAME ...] [--spec openapi.json | --no-spec] [--json out.json]

Exit code:
  0 = migrated: the new stack is in use (auth/api hosts, /admin/v3.1 or /admin/v4) and no legacy usage is left;
      with --target v4, also no v3.1 call whose v4 successor exists
  1 = legacy usage found, or (--target v4) v3.1 calls left to move to v4
  2 = usage error
  3 = no Hivebrite API usage recognised at all: wrong directory, or the base URL comes from somewhere the scan
      cannot see (pass --base-var). This never means "already migrated".
  4 = --target v4 without the contract: no legacy usage is left, but the v4 moves can't be checked. Download
      the contract and pass --spec.
Read-only: never edits files. Stdlib only (Python 3.8+).
"""
import argparse, json, os, re, sys, time, urllib.request

SPEC_URL = "https://docs.hivebrite.com/partner/admin/openapi.json"
# Only dependencies, caches and tool state: scripts in bin/ and code in build/, dist/, target/ or obj/
# are scanned, so a legacy call there can't hide behind a "MIGRATED" status.
SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "__pycache__", ".tox", ".next", "coverage",
             ".idea", ".gradle"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".zip", ".gz", ".tar", ".jar", ".class",
            ".so", ".dylib", ".dll", ".exe", ".woff", ".woff2", ".ttf", ".lock", ".min.js", ".map"}
MAX_BYTES = 2_000_000

# Resource roots that exist on the legacy Admin API (used to spot paths built from a base URL constant).
ROOTS = ("users|experiences|educations|network_events|topics|news|memberships|donations|mentoring|emailings|"
         "ventures|forums|posts|comments|payment_accounts|receipts|order_management|companies|"
         "business_opportunities|admins|roles|approvals|pages_customizable|notifications|push_notifications|"
         "audit_logs|versions|email_analytics_v2|external_link_protection|network|settings|sub_networks|"
         "user_data_fields|me|categories|media_center|current_locations|engagement_scoring")

RE_LEGACY_URL = re.compile(r"(?:https?://[A-Za-z0-9.\-]*hivebrite\.com)?/api/admin/v([123])\b(/[^\s'\"`?)\]>,;]*)?")
# The legacy prefix with a version that is not written out: `${host}/api/admin/${version}`, "/api/admin/" + v.
# The new stack has no /api prefix, so any other /api/admin is legacy.
RE_LEGACY_PREFIX = re.compile(r"/api/admin(?!/v[123]\b)\b")
# A resource path after a quote, an interpolated base (`${base}/`, `#{BASE}/`, `{Base}/`, `$base/`) or a
# printf placeholder (`%s/`).
RE_RESOURCE_LIT = re.compile(r"(?:['\"`]/?|\}/|\$\w+/|%s/)(" + ROOTS + r")(/[^'\"`\s?]*)?(?:\?[^'\"`]*)?['\"`]")
# A base-URL constant: NAME = "<host>/api/admin/v1", `${host}/api/admin/${version}`, f"{HOST}/api/admin/{V}",
# HOST + "/api/admin/". Group 2 is the version when it is written out, otherwise None. Group 3 is a resource
# path the constant already includes (GROUPS = ".../api/admin/v2/topics"): calls built from it append to it.
RE_BASE_DEF = re.compile(
    r"([A-Za-z_][\w.]*)['\"]?\s*(?:=|:|=>|:=)\s*(?:[\w.()\[\]]+\s*\+\s*)?[fFrRbB]?['\"`][^'\"`\n]*"
    r"/api/admin(?:/v([123])\b(/[A-Za-z0-9_/-]*[A-Za-z0-9_])?|/(?:\$\{[^}]*\}|\{[^}]*\}|#\{[^}]*\}|%s))?/?['\"`]")
# A call already on v3.1 (the new stack has no /api prefix), and a base-URL constant ending in /admin/v3.1.
RE_V31_URL = re.compile(r"(?<!/api)/admin/v3\.1(/[^\s'\"`?)\]>,;]+)")
RE_V31_BASE_DEF = re.compile(r"([A-Za-z_][\w.]*)['\"]?\s*(?:=|:|=>|:=)\s*[fFrRbB]?['\"`][^'\"`\n]*(?<!/api)/admin/v3\.1/?['\"`]")
# v1-v3 are switched off on this date; a v3.1 endpoint removed on or before it must move to v4 now.
LEGACY_SHUTDOWN = "2027-02-15"
# Positive evidence that the code is on the new stack.
RE_NEW_STACK = re.compile(r"\b(?:auth|api)\.(?:eu|us|apac|ch|preprod|sandbox\.us)\.hivebrite\.com\b|/admin/v(?:3\.1|4)/"
                          r"|audience\W{1,6}partner")
# The HTTP verb, also as the start of a method name (DeleteAsync, GetFromJsonAsync), but not of a word (getenv, postal).
RE_METHOD = re.compile(r"\b(?i:(get|post|put|patch|delete))(?![a-z])")
CHECKS = [
    ("legacy_token_endpoint", re.compile(r"/api/oauth/token\b"), "Token call → POST https://auth.<zone>.hivebrite.com/oauth2/token with client_credentials + audience=partner"),
    ("password_grant", re.compile(r"grant_type\W{1,6}password|['\"]password['\"]\s*[,)}]|\badmin_email\b"), "Remove admin email/password; use the Service App client id + secret"),
    ("refresh_token", re.compile(r"refresh_token"), "Delete the Hivebrite refresh-token logic; re-request a token before expires_in elapses"),
    ("body_status", re.compile(r"\[\s*['\"]status['\"]\s*\]|get\(\s*['\"]status['\"]|\b(?:body|data|json|payload)\.status\b"), "If this reads `status` from a response BODY: v3.1 has none, use the HTTP status + error.code"),
    ("education_key", re.compile(r"\beducation_key\b"),
     "v1 lookup by external id. On v3.1 the flat /educations endpoints ignore education_key and look up by Hivebrite id "
     "only, so this updates or deletes the wrong education, or 404s: see interface-changes.md. The per-user "
     "/users/{user_id}/educations endpoints still accept it."),
    ("old_field_name", re.compile(r"\b(school_name|field_of_study_name|field_of_study_id|paperclip_logo)\b|['\"]topics?['\"]\s*\]|\.topics?\b"), "Possible v1 field read; check against the endpoint actually called (see interface-changes.md)"),
]
# These two markers are legacy only next to legacy Hivebrite calls: in a file without any, they most likely
# belong to another provider (Salesforce, Google...) and are reported for a check, not counted as legacy.
CONTEXTUAL = {"password_grant", "refresh_token"}
BLOCKING = {"endpoint", "base_url", "legacy_token_endpoint", "password_grant", "refresh_token"}
V4_ONLY = {
    "push_notifications": "/admin/v4/push-notifications",
    "external_link_protection": "/admin/v4/network/external-link-protection/allowed-domains",
}


def norm(path):
    """Template a concrete or interpolated path: /users/123, /users/${id}, /users/:id, /users/" + id -> /users/{}"""
    path = re.sub(r"\?.*$", "", path).rstrip("/")
    segs = []
    for s in path.split("/"):
        if not s:
            continue
        if re.fullmatch(r"\d+|\{[^}]*\}|\$\{[^}]*\}|:[A-Za-z_]\w*|%[sd]|<[^>]*>|#\{[^}]*\}|\[[^\]]*\]", s) or re.search(r"[{}$+]", s):
            segs.append("{}")
        else:
            segs.append(s)
    return "/" + "/".join(segs)


# Values printed or written by the scan are masked: the lines it reports (token calls, password grants,
# refresh tokens) are the ones most likely to hold a hard-coded credential.
SECRET_KEY = r"[\w.-]*(?:pass(?:word|wd)?|secret|token|api[_-]?key|auth(?:orization)?|credential)[\w.-]*"
RE_SECRET_KV = re.compile(r"(?i)(" + SECRET_KEY + r"[\"']?\s*(?:=>|:=|[:=])\s*)([\"'])((?:\\.|(?!\2).)*)\2")
RE_SECRET_SCHEME = re.compile(r"(?i)\b(Bearer|Basic|Token)\s+[A-Za-z0-9._~+/=-]{8,}")
RE_URL_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@'\"]+:[^/\s@'\"]+@")
RE_ENV_NAME = re.compile(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+")
RE_TOKEN_LIKE = re.compile(r"([\"'])(?=[^\"'\s/]*\d)(?=[^\"'\s/]*[A-Za-z])[A-Za-z0-9_+=.-]{24,}\1")


def redact(line):
    def kv(m):
        value = m.group(3)
        if not value or value.startswith(("http://", "https://", "/", "${", "#{", "{{", "%")) or RE_ENV_NAME.fullmatch(value):
            return m.group(0)  # a URL, a path, a placeholder or an environment variable name
        return m.group(1) + m.group(2) + "***" + m.group(2)
    line = RE_SECRET_KV.sub(kv, line)
    line = RE_SECRET_SCHEME.sub(lambda m: m.group(1) + " ***", line)
    line = RE_URL_USERINFO.sub(lambda m: m.group(1) + "***@", line)
    return RE_TOKEN_LIKE.sub(lambda m: m.group(1) + "***" + m.group(1), line)


def snippet(line):
    return redact(line.strip())[:200]


def cache_path():
    """A per-user cache directory, readable only by its owner, instead of a shared temporary file."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    d = os.path.join(base, "hivebrite-api-migration")
    os.makedirs(d, mode=0o700, exist_ok=True)
    st = os.stat(d)
    if hasattr(os, "getuid") and (st.st_uid != os.getuid() or st.st_mode & 0o077):
        os.chmod(d, 0o700) if st.st_uid == os.getuid() else sys.exit(f"refusing to use {d}: owned by another user")
    return os.path.join(d, "admin-openapi.json")


def load_spec(path, allow_download):
    if path:
        return json.load(open(path))
    if not allow_download:
        return None
    cache = cache_path()
    if not os.path.exists(cache) or time.time() - os.path.getmtime(cache) > 12 * 3600:
        try:
            req = urllib.request.Request(SPEC_URL, headers={"User-Agent": "hivebrite-api-migration-skill"})
            with urllib.request.urlopen(req, timeout=60) as r, open(cache, "wb") as f:
                f.write(r.read())
        except Exception as e:  # offline is fine: the scan still works, without v4 data
            print(f"note: could not download the contract ({e}); v4 columns left empty", file=sys.stderr)
            return None
    return json.load(open(cache))


def index_spec(spec):
    if not spec:
        return {}, {}
    ops, by_tpl = {}, {}
    for p, item in spec.get("paths", {}).items():
        for m, op in item.items():
            if isinstance(op, dict) and "operationId" in op:
                ops[op["operationId"]] = (m.upper(), p)
    for p, item in spec.get("paths", {}).items():
        if not p.startswith("/admin/v3.1/"):
            continue
        for m, op in item.items():
            if not isinstance(op, dict) or m not in ("get", "post", "put", "patch", "delete"):
                continue
            succ = op.get("x-successor")
            by_tpl.setdefault(norm(p), {})[m.upper()] = {
                "deprecated": op.get("x-deprecated-date") if op.get("deprecated") else None,
                "sunset": op.get("x-sunset-date"),
                "successor": " ".join(ops.get(succ, ("?", succ))) if succ else None,
            }
    return ops, by_tpl


def interface_note(version, method, rpath):
    root = rpath.strip("/").split("/")[0] if rpath.strip("/") else ""
    if root in V4_ONLY:
        return "V4-ONLY", f"No v3.1 path: move to {V4_ONLY[root]}"
    t = norm(rpath)
    if t.startswith("/network_events/waitlist"):
        return "V4-ONLY", ("No v3.1 path: list each event's waiting list with GET /admin/v4/admin-events/{id}/waitlist "
                           "(ticket_id filters; pagination.total counts waiters, also per ticket for the summary)")
    if t.startswith("/topics/{}/followers"):
        return "MOVE", ("Deprecated on v3.1, no successor: add with POST /admin/v3.1/topics/users {members}, remove with "
                        "DELETE /admin/v3.1/topics/users {users}. Adding now emails confirmed members; removing deletes "
                        "the membership instead of marking it left (interface-changes.md)")
    if root == "audit_logs":
        return "V4-REQUIRED", "v3.1 audit logs sunset with v1–v3: use GET /admin/v4/audit-logs"
    if version not in ("1", "?"):
        return "", ""
    # version "?": the version is not written out (it comes from config), so the change may or may not apply
    tag = "V1→V2" if version == "1" else "CHECK"
    unknown = "" if version == "1" else "API version not written out: if this calls v1, "
    t = norm(rpath)
    if t.startswith("/educations") and "customizable_attributes" not in t:
        return tag, unknown + "Educations: school/field_of_study names, keyed custom_attributes; flat PUT needs v2 names in the body"
    if t.startswith("/topics") and not (t.startswith("/topics/categories") or t.endswith("/followers")):
        return tag, unknown + "Groups: root key groups/group, categories[] instead of category"
    if t == "/users/{}" and (method in ("DELETE", "?")):
        return tag if method == "DELETE" else "CHECK", unknown + "DELETE /users/{id}: 202 Accepted, asynchronous; don't depend on the body"
    return "", ""


def walk(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for fn in files:
            if any(fn.endswith(e) for e in SKIP_EXT):
                continue
            fp = os.path.join(d, fn)
            try:
                if os.path.getsize(fp) > MAX_BYTES:
                    continue
                yield fp, open(fp, encoding="utf-8", errors="strict").read()
            except (UnicodeDecodeError, OSError):
                continue


def scan(root, base_vars=()):
    """Returns (hits, number of files showing the new stack)."""
    hits = []
    files = list(walk(root))
    new_stack_files = sum(1 for _, t in files if RE_NEW_STACK.search(t))
    # pre-pass: legacy versions used anywhere, for paths built from a base-URL constant defined elsewhere
    repo_versions = {v for _, t in files for v, _ in RE_LEGACY_URL.findall(t)}
    # base-URL constants, e.g. HIVEBRITE_BASE = "https://x.hivebrite.com/api/admin/v1" -> {"HIVEBRITE_BASE": "1"};
    # "?" when the version comes from somewhere else
    base_defs, base_suffix = {}, {}
    for _, t in files:
        for name, v, suffix in RE_BASE_DEF.findall(t):
            base_defs[name.split(".")[-1]] = v or "?"
            if suffix:
                base_suffix[name.split(".")[-1]] = suffix
    base_vars = list(base_vars) + [b for b in base_defs if b not in base_vars]
    v31_bases = {name.split(".")[-1] for _, t in files for name in RE_V31_BASE_DEF.findall(t)}
    for fp, text in files:
        if text:
            uses_base = any(re.search(r"\b" + re.escape(b) + r"\b", text) for b in base_vars)
            uses_v31_base = any(re.search(r"\b" + re.escape(b) + r"\b", text) for b in v31_bases)
            if ("hivebrite" not in text.lower() and "/api/admin" not in text and "/api/oauth/token" not in text
                    and "/admin/v3.1" not in text and not uses_base and not uses_v31_base):
                continue
            used = {base_defs[b] for b in base_defs if re.search(r"\b" + re.escape(b) + r"\b", text)}
            versions_in_file = {v for v, _ in RE_LEGACY_URL.findall(text)} | used or repo_versions
            legacy_file = bool(RE_LEGACY_URL.search(text) or RE_LEGACY_PREFIX.search(text) or used
                               or CHECKS[0][1].search(text))
            for n, line in enumerate(text.splitlines(), 1):
                rel = os.path.relpath(fp, root)
                m = RE_METHOD.search(line)
                method = m.group(1).upper() if m else "?"
                found_url = False
                for mm in RE_LEGACY_URL.finditer(line):
                    found_url = True
                    hits.append(dict(kind="endpoint" if mm.group(2) else "base_url", file=rel, line=n, version=mm.group(1),
                                     method=method, path=mm.group(2) or "", text=snippet(line)))
                if not found_url and RE_LEGACY_PREFIX.search(line):
                    found_url = True
                    hits.append(dict(kind="base_url", file=rel, line=n, version="?", method=method, path="",
                                     text=snippet(line)))
                # a base-URL constant named on this line decides the version of the path built from it
                line_bases = [b for b in base_vars if re.search(r"\b" + re.escape(b) + r"\b", line)]
                line_versions = {base_defs[b] for b in line_bases if b in base_defs}
                if not found_url and versions_in_file:
                    for mm in RE_RESOURCE_LIT.finditer(line):
                        # a bare "users" literal is a path only next to a base constant; otherwise it is a JSON key
                        if "/" not in mm.group(0)[:mm.start(1) - mm.start(0)] and not line_bases:
                            continue
                        rp = "/" + mm.group(1) + (mm.group(2) or "")
                        # a constant that already includes a resource (GROUPS = .../v2/topics) prefixes the path
                        prefix = next((base_suffix[b] for b in line_bases if b in base_suffix), "")
                        if prefix and not rp.startswith(prefix):
                            rp = prefix + rp
                        vs = line_versions or versions_in_file
                        v = next(iter(vs)) if len(vs) == 1 else "?"
                        hits.append(dict(kind="endpoint(probable)", file=rel, line=n, version=v, method=method, path=rp,
                                         text=snippet(line)))
                # calls already on the new stack: literal /admin/v3.1/... paths, or paths built from a v3.1 base
                if not found_url:
                    current = [mm.group(1) for mm in RE_V31_URL.finditer(line)]
                    for cp in current:
                        hits.append(dict(kind="current", file=rel, line=n, version="3.1", method=method, path=cp,
                                         text=snippet(line)))
                    if not current and not line_bases and any(re.search(r"\b" + re.escape(b) + r"\b", line) for b in v31_bases):
                        for mm in RE_RESOURCE_LIT.finditer(line):
                            hits.append(dict(kind="current(probable)", file=rel, line=n, version="3.1", method=method,
                                             path="/" + mm.group(1) + (mm.group(2) or ""), text=snippet(line)))
                for kind, rx, advice in CHECKS:
                    if rx.search(line):
                        if kind in CONTEXTUAL and not legacy_file:
                            kind, advice = kind + "(check)", (
                                "No legacy Hivebrite call in this file: probably another provider's auth. "
                                "Leave it unless it serves Hivebrite.")
                        hits.append(dict(kind=kind, file=rel, line=n, version="", method="", path="", advice=advice,
                                         text=snippet(line)))
    return hits, new_stack_files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--spec")
    ap.add_argument("--no-spec", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--target", choices=("v3.1", "v4"), default="v3.1",
                    help="v4: endpoints with a v4 successor must move to it, legacy and v3.1 calls alike")
    ap.add_argument("--base-var", action="append", default=[],
                    help="name of a constant/env var holding the legacy base URL; files using it are scanned too (repeatable)")
    a = ap.parse_args()
    if not os.path.isdir(a.root):
        print("not a directory: " + a.root, file=sys.stderr); return 2
    _, by_tpl = index_spec(load_spec(a.spec, not a.no_spec))
    seen, hits = set(), []
    raw, new_stack_files = scan(a.root, a.base_var)
    for h in raw:
        key = (h["kind"].split("(")[0], h["file"], h["line"], h["path"])
        if key not in seen:
            seen.add(key); hits.append(h)
    eps = [h for h in hits if h["kind"].startswith("endpoint")]
    cur = [h for h in hits if h["kind"].startswith("current")]

    def plan_v4(h):
        """Point an endpoint at its v4 successor when the target asks for it, or when v3.1 dies with v1-v3."""
        succ = h.get("successor")
        if not succ or ":" in succ:          # no successor, or several methods (ambiguous): stays as is
            return
        if h.get("sunset") and h["sunset"] <= LEGACY_SHUTDOWN:
            h["change"], h["note"] = "V4-REQUIRED", f"v3.1 endpoint removed on {h['sunset']}, with v1-v3: move to v4"
        elif a.target == "v4":
            h["change"], h["note"] = "V4-MOVE", "has a v4 successor: move to it (reference/v4-mode.md)"
        else:
            return
        h["target"] = succ.split(" ", 1)[-1]

    for h in cur:
        h["target"], h["change"], h["note"] = "/admin/v3.1" + h["path"], "", ""
        info = by_tpl.get(norm(h["target"]), {})
        pick = info.get(h["method"]) or (next(iter(info.values())) if len(info) == 1 else None)
        if pick:
            h["successor"], h["sunset"], h["deprecated"] = pick["successor"], pick["sunset"], pick["deprecated"]
        plan_v4(h)
    for h in eps:
        tag, note = interface_note(h["version"], h["method"], h["path"])
        h["target"] = "/admin/v3.1" + h["path"]
        h["change"], h["note"] = tag, note
        info = by_tpl.get(norm(h["target"]), {})
        pick = info.get(h["method"]) or (next(iter(info.values())) if len(info) == 1 else None)
        if tag in ("V4-ONLY", "V4-REQUIRED"):
            root = h["path"].strip("/").split("/")[0]
            h["target"] = (V4_ONLY[root] if root in V4_ONLY else "/admin/v4/admin-events/{id}/waitlist"
                           if root == "network_events" else "/admin/v4/audit-logs")
        elif tag == "MOVE":
            h["target"] = "/admin/v3.1/topics/users"
        if pick:
            h["successor"], h["sunset"], h["deprecated"] = pick["successor"], pick["sunset"], pick["deprecated"]
        elif info:
            h["successor"] = ", ".join(f"{m}: {v['successor'] or '-'}" for m, v in info.items())
        elif by_tpl and tag not in ("V4-ONLY", "V4-REQUIRED"):
            h["note"] = (h["note"] + "; " if h["note"] else "") + "path not found in the v3.1 contract: check it"
        if tag not in ("V4-ONLY", "V4-REQUIRED", "MOVE"):
            plan_v4(h)
    if a.json:
        json.dump(hits, open(a.json, "w"), indent=2)

    print("## Endpoints\n")
    print("| file:line | ver | method | legacy path | target | change | v4 successor | sunset |")
    print("|---|---|---|---|---|---|---|---|")
    for h in sorted(eps, key=lambda x: (x["file"], x["line"])):
        prob = " (probable)" if "probable" in h["kind"] else ""
        h = {k: (v.replace("|", "\\|") if isinstance(v, str) else v) for k, v in h.items()}
        print(f"| {h['file']}:{h['line']} | v{h['version']} | {h['method']} | `{h['path']}`{prob} | `{h['target']}` | "
              f"{h.get('change','')} {h.get('note','')} | {h.get('successor') or '-'} | {h.get('sunset') or '-'} |")
    if cur:
        print("\n## Calls already on v3.1\n")
        print("| file:line | method | path | target | change | v4 successor | sunset |")
        print("|---|---|---|---|---|---|---|")
        for h in sorted(cur, key=lambda x: (x["file"], x["line"])):
            prob = " (probable)" if "probable" in h["kind"] else ""
            print(f"| {h['file']}:{h['line']} | {h['method']} | `{h['path']}`{prob} | `{h['target']}` | "
                  f"{h.get('change','')} {h.get('note','')} | {h.get('successor') or '-'} | {h.get('sunset') or '-'} |")
    if a.target == "v4" and not by_tpl:
        print("\nNote: no contract loaded, so v4 successors are unknown and no v4 move can be planned. Run without --no-spec.")
    print("\n## Base URLs, auth and error handling\n")
    for h in sorted([x for x in hits if not x["kind"].startswith("endpoint")], key=lambda x: (x["file"], x["line"])):
        adv = h.get("advice") or "Base URL → https://api.<zone>.hivebrite.com/admin/v3.1 (from configuration)"
        print(f"- `{h['file']}:{h['line']}` **{h['kind']}**: {adv}\n  `{h['text']}`")
    blocking = [h for h in hits if h["kind"] in BLOCKING]
    roots = sorted({h["path"].strip("/").split("/")[0] for h in eps if h["path"]})
    print(f"\n## Summary\n\n{len(eps)} endpoint sites, {len({(h['method'], norm(h['path'])) for h in eps})} distinct endpoints, "
          f"versions {sorted({h['version'] for h in eps if h['version']})}, resources: {', '.join(roots) or '-'}")
    print(f"Interface changes: {sum(1 for h in eps if h.get('change'))} sites. Legacy markers left: {len(blocking)}. "
          f"To check by hand: {sum(1 for h in hits if h['kind'].endswith('(check)'))}.")
    soon = sorted({h["sunset"] for h in eps + cur if h.get("sunset")})
    if soon:
        print(f"Endpoints in this inventory are already deprecated on v3.1, removed on {', '.join(soon)}: "
              "decide the target (v3.1 or v4) for those before rewriting.")
    v4_left = [h for h in cur if h.get("change") in ("V4-MOVE", "V4-REQUIRED")]
    if blocking:
        print("\nStatus: LEGACY USAGE FOUND.")
        return 1
    if v4_left:
        print(f"\nStatus: V4 MOVES LEFT. {len(v4_left)} call(s) on v3.1 must move to their v4 successor"
              + (" (required: removed with v1-v3)." if any(h["change"] == "V4-REQUIRED" for h in v4_left) else "."))
        return 1
    if a.target == "v4" and not by_tpl and (new_stack_files or cur):
        print("\nStatus: UNVERIFIED. No legacy usage is left, but without the contract the v4 moves can't be checked. "
              "Download it (docs.hivebrite.com/partner/admin, \"Download OpenAPI Document\") and re-run with --spec FILE.")
        return 4
    if new_stack_files:
        print(f"\nStatus: MIGRATED. The new stack is used in {new_stack_files} file(s) and no legacy usage is left.")
        return 0
    print("\nStatus: NO HIVEBRITE API USAGE RECOGNISED. This does not mean the code is migrated: check the directory, "
          "and pass --base-var NAME if the base URL comes from configuration the scan cannot see.")
    return 3


if __name__ == "__main__":
    sys.exit(main())
