#!/usr/bin/env python3
"""Call the same read endpoints on the legacy API and on v3.1, and diff the response SHAPES.

This is the check that catches the silent breakages: a key your code reads that the v3.1 response no
longer has (school_name -> school, topics -> groups, custom_attributes entries) returns no error,
just empty values. Only GET requests are made. Values are never printed, only key paths and types.

Credentials come from the environment, never from arguments (they would land in shell history):
  HB_ZONE             eu | us | apac | ch | eu-sandbox | us-sandbox   (use a sandbox first)
  HB_CLIENT_ID        Service App client id
  HB_CLIENT_SECRET    Service App client secret
  HB_LEGACY_HOST      the host the legacy calls use today: https://acme.hivebrite.com, or the community's
                      own domain for a white-label community (https://community.example.org)
  HB_LEGACY_TOKEN     a current legacy access token (from your existing password-grant call)

Usage:
  compare.py /api/admin/v1/educations?per_page=5 /api/admin/v2/topics?per_page=5 /api/admin/v1/users/123 ...

Exit code: 0 = shapes identical for every path, 1 = differences found (read them), 2 = setup error.
"""
import base64, json, os, sys, urllib.error, urllib.parse, urllib.request

HOSTS = {"eu": ("auth.eu.hivebrite.com", "api.eu.hivebrite.com"), "us": ("auth.us.hivebrite.com", "api.us.hivebrite.com"),
         "apac": ("auth.apac.hivebrite.com", "api.apac.hivebrite.com"), "ch": ("auth.ch.hivebrite.com", "api.ch.hivebrite.com"),
         "eu-sandbox": ("auth.preprod.hivebrite.com", "api.preprod.hivebrite.com"),
         "us-sandbox": ("auth.sandbox.us.hivebrite.com", "api.sandbox.us.hivebrite.com")}
UA = {"User-Agent": "hivebrite-api-migration-skill"}


def need(k):
    v = os.environ.get(k)
    if not v:
        sys.exit(f"missing environment variable {k} (see the header of this script)")
    return v


def call(url, headers, data=None):
    req = urllib.request.Request(url, data=data, headers={**UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            return r.status, r.headers.get("X-Request-Id", ""), body
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("X-Request-Id", ""), e.read()


def token(auth_host, cid, secret):
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    st, rid, body = call(f"https://{auth_host}/oauth2/token",
                         {"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"},
                         b"grant_type=client_credentials&audience=partner")
    if st != 200:
        sys.exit(f"token request failed: HTTP {st} (X-Request-Id {rid}); check zone, client id/secret")
    return json.loads(body)["access_token"]


def shape(v, prefix="", out=None):
    """Flatten JSON into {key_path: type}. Arrays collapse to [] using the union of their first 20 items."""
    out = {} if out is None else out
    if isinstance(v, dict):
        if not v:
            out[prefix or "$"] = "object"
        for k, x in v.items():
            shape(x, f"{prefix}.{k}" if prefix else k, out)
    elif isinstance(v, list):
        out[prefix + "[]"] = "array"
        for x in v[:20]:
            shape(x, prefix + "[]", out)
    else:
        out[prefix or "$"] = type(v).__name__ if v is not None else "null"
    return out


def main(paths):
    if not paths:
        print(__doc__); return 2
    zone = need("HB_ZONE")
    if zone not in HOSTS:
        sys.exit("HB_ZONE must be one of " + ", ".join(HOSTS))
    auth, api = HOSTS[zone]
    new_tok = token(auth, need("HB_CLIENT_ID"), need("HB_CLIENT_SECRET"))
    legacy_host, legacy_tok = need("HB_LEGACY_HOST").rstrip("/"), need("HB_LEGACY_TOKEN")
    if not legacy_host.startswith("https://"):
        sys.exit("HB_LEGACY_HOST must start with https://: the legacy token is sent to it")
    # The legacy token goes only to this host: show it, so a typo in a white-label domain is caught.
    print(f"legacy host: {legacy_host} (receives HB_LEGACY_TOKEN)", file=sys.stderr)
    differences = False
    for p in paths:
        if not p.startswith("/api/admin/v"):
            print(f"skip {p}: give the legacy path, e.g. /api/admin/v1/users?per_page=5"); continue
        v31 = "/admin/v3.1/" + p.split("/", 4)[4]
        st_l, rid_l, b_l = call(legacy_host + p, {"Authorization": "Bearer " + legacy_tok})
        st_n, rid_n, b_n = call(f"https://{api}{v31}", {"Authorization": "Bearer " + new_tok})
        print(f"\n### GET {p}  →  {v31}\nlegacy HTTP {st_l} · v3.1 HTTP {st_n} (X-Request-Id {rid_n})")
        if st_n == 403:
            print("v3.1 403: the Service App's admin lacks the Back Office module for this endpoint (reference/contract.md)")
        if st_l != 200 or st_n != 200:
            differences = True; continue
        try:
            s_l, s_n = shape(json.loads(b_l)), shape(json.loads(b_n))
        except ValueError:
            print("non-JSON body on one side: compare by hand"); differences = True; continue
        gone = sorted(set(s_l) - set(s_n)); new = sorted(set(s_n) - set(s_l))
        typed = sorted(k for k in set(s_l) & set(s_n) if s_l[k] != s_n[k] and "null" not in (s_l[k], s_n[k]))
        roots_l = {k.split(".")[0].split("[")[0] for k in s_l}; roots_n = {k.split(".")[0].split("[")[0] for k in s_n}
        if roots_l != roots_n:
            print(f"ROOT KEY CHANGED: {sorted(roots_l)} → {sorted(roots_n)}  (every mapping that reads the old root returns nothing)")
        if gone:
            print("Only in legacy (code reading these gets nothing on v3.1):\n  " + "\n  ".join(gone[:60]))
        if new:
            print("Only in v3.1:\n  " + "\n  ".join(new[:60]))
        if typed:
            print("Type changed:\n  " + "\n  ".join(f"{k}: {s_l[k]} → {s_n[k]}" for k in typed[:40]))
        if gone or typed or roots_l != roots_n:
            differences = True
        elif not new:
            print("identical shape")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
