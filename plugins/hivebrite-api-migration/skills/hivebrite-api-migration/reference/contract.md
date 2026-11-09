# The stack change: identical for every integration

## Before → after

| | Legacy v1 / v2 / v3 | New stack |
|---|---|---|
| Token endpoint | `POST https://<community host>/api/oauth/token` | `POST https://auth.<zone>.hivebrite.com/oauth2/token` |
| Grant | `password`: admin email + password + client id/secret | `client_credentials`: Service App client id + secret, **plus `audience=partner`** |
| Token | opaque, 7-day TTL, refresh token | signed JWT, lifetime set on the Service App (up to 24 h; read `expires_in`), **no refresh token** |
| API base | `https://<community host>/api/admin/vX/` | `https://api.<zone>.hivebrite.com/admin/v3.1/` (and `/admin/v4/`) |
| Credentials | OAuth app under External Integrations | **Service App**: Back Office → Integrations → External Integrations → Service apps |
| Permissions | none: any token calls any endpoint | each call is checked against the credential admin's Back Office modules |
| Errors | `{"status": 404, "level": "warn", "errors": "..."}` | `{"error": {"code": "not_found", "message": "..."}}` + `X-Request-Id` header |
| Rate limit | 300 req/min, 15 5xx/min | about the same, but a 429 can come from the gateway as well, without `Retry-After` (see below) |

`<community host>` is `<community>.hivebrite.com`, or the community's own domain when it is white-label.

The community is no longer in the hostname: the API reads it from the token, which is bound to
the community where the Service App was created. One Service App per community.

The Service App acts as the admin who created it: that admin's Back Office permissions apply to every call,
and changes appear under that admin in the audit trail. Create it with the admin you want to see there.

**Switch an integration in one go.** A v3.1 token is refused on `/api/admin/v1/...` (401 "The access
token is invalid"), and a legacy token is refused on v3.1. Move the token helper and the base URL in
the same change; a half-migrated client fails on every call that still uses the other stack.

## Hosts

| Zone | Auth host (token) | API host (calls) |
|---|---|---|
| EU (default) | `auth.eu.hivebrite.com` | `api.eu.hivebrite.com` |
| US | `auth.us.hivebrite.com` | `api.us.hivebrite.com` |
| APAC | `auth.apac.hivebrite.com` | `api.apac.hivebrite.com` |
| CH | `auth.ch.hivebrite.com` | `api.ch.hivebrite.com` |
| EU sandbox | `auth.preprod.hivebrite.com` | `api.preprod.hivebrite.com` |
| US sandbox | `auth.sandbox.us.hivebrite.com` | `api.sandbox.us.hivebrite.com` |

The token goes to `auth.*`, never to `api.*`. `api.<zone>.hivebrite.com/auth/token` answers
`404 not_found`, the classic symptom of that mistake. Sandbox credentials are created in the sandbox
community's Back Office and do not work on production.

## Token exchange

```bash
curl -X POST "https://auth.eu.hivebrite.com/oauth2/token" \
  -u "$CLIENT_ID:$CLIENT_SECRET" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" -d "audience=partner"
# → {"access_token":"eyJ...","token_type":"bearer","expires_in":3599}
```

Then `Authorization: Bearer <access_token>` on every call, to v3.1 and v4 alike. Credentials may also
be sent as form fields instead of Basic auth.

The helper every call should go through, in pseudocode (write it in the repo's language):

```
get_token():
  if cached and now < cached.expires_at - 30s: return cached.token
  r = POST https://$AUTH_HOST/oauth2/token
        Authorization: Basic base64(client_id:client_secret)
        Content-Type: application/x-www-form-urlencoded
        body: grant_type=client_credentials&audience=partner
  cached = { token: r.access_token, expires_at: now + r.expires_in }
  return cached.token

request(method, path, ...):         # path like /admin/v3.1/users or /admin/v4/posts
  resp = HTTP(method, https://$API_HOST + path, Authorization: Bearer get_token(), ...)
  if resp.status == 401 and not retried: drop cache; retry once   # expired token
  if resp.status == 403: raise Forbidden(resp.error.code, X-Request-Id)  # missing Back Office module, do NOT retry
  if resp.status == 429 and retries left: sleep(seconds named in error.message, else 5 s doubling); retry
                                                                  # safe even for writes: refused before running
  if resp.status >= 400: raise ApiError(resp.status, resp.error.code, X-Request-Id)
  return resp
```

Token lifecycle: cache the token and fetch a new one about 30 s before `expires_in` elapses.
Delete any refresh-token storage or rotation code; do not port it.

## Path rule

Drop the community host and `/api/admin/vX/`, prepend `https://api.<zone>.hivebrite.com/admin/v3.1/`.
Every v1, v2 and v3 endpoint exists on v3.1 under the same resource path. Where an endpoint existed in
several versions, v3.1 serves the **most recent** interface: see `interface-changes.md`.

## Error codes (v3.1)

The gateway sets `error.code` from the HTTP status:

| HTTP | `error.code` | Meaning |
|---|---|---|
| 400 | `request_validation_failed` or `request_deserialization_failed` | malformed request, or a required parameter or body missing |
| 401 | `unauthorized` | token missing, expired or invalid, **or minted without `audience=partner`**, or a legacy token |
| 403 | `forbidden_permission` (a few reads: `forbidden`) | valid token, the admin lacks the Back Office permission (new on this stack) |
| 404 | `not_found` | no such resource, **or** wrong host or path |
| 405 | `method_not_allowed` | no such method on that path |
| 422 | `operation_validation_error` | refused by a business rule |
| 429 | `too_many_requests` | throttled: see below |
| 500 | `backend_processing_error` (or `gateway_processing_error`) | do not auto-retry non-idempotent calls |
| 502 to 504 | `external_service_unavailable` | upstream unavailable |

- **Branch on the HTTP status, then on `error.code`.** Treat a code you don't recognise by its status class.
- **`message` often holds the legacy error body as a JSON string**, e.g.
  `"{\"status\":404,\"level\":\"warn\",\"errors\":\"...\"}"`. It's fine to log it, or to parse it
  for a log line. Never branch on it: exact matches on the old error text stop matching.
- **An unknown id isn't always a 404.** A few endpoints answer 422 for it (`GET` and `DELETE /news/{id}`,
  `GET /mentoring/programs/{id}`, `POST /users/{id}/activate`). An endpoint that requires a body or a query
  parameter validates first and answers 400 for an unknown id sent without them. "If 404 then create" logic
  must use the status the endpoint really returns: check it on the sandbox.

v4 uses the same envelope with more specific codes (`post_not_found`, `forbidden_permission` +
`required_permission`, `request_validation_failed`).

## Throttling and retries

- A 429 comes either from Rails (a short body saying "try again after N seconds") or from the gateway (an
  empty body). **`Retry-After` does not reach the client**: wait the N seconds from the message when there
  is one, otherwise back off (5 s, doubling, capped at about a minute).
- A 429 is refused before the action runs, so it is safe to retry, writes included. Do not auto-retry a 5xx
  or a timeout on a write: most v3.1 writes have no idempotency key.
- All calls of a Service App share one budget. Retrying aggressively multiplies the load rather than the
  throughput: cap retries and spread bulk jobs over time. `full_profile=true` has a lower limit.

## Request details that changed

- **Bodies on DELETE:** send them with a `Content-Length` (buffer the body; don't stream it chunked).
  `DELETE /topics/users` with a chunked body arrives empty and answers 400 "users is missing".
- **Query values:** pass them to your HTTP client unencoded and let it encode once. A JSON value encoded
  twice (e.g. `advanced_search_query`) answers 422 "Invalid JSON".
- **Group rosters:** `POST /topics/users` takes `members` (or `prospects`); a body keyed `users` answers
  201 `[]` and adds no one. `DELETE /topics/users` takes `users: [{group_id, user_ids: [...]}]`.
  There is no `PUT /topics/users`: it is routed to `PUT /topics/{id}` with the id `users`.
- **Paging:** `X-Total` is a string (`-1` when there is nothing), and `email_analytics_v2/deliveries`
  sends no `X-Total`: walk until a short page. Keep `per_page` explicit (the default is 25).

## Back Office module per endpoint

| v3.1 endpoints | Back Office permission |
|---|---|
| `/users*`, `/experiences*`, `/educations*` | Community > Users (manage to write) |
| `/users/_bulk` | Community > Users **and** Community > Import, both manage |
| `/network_events*` | Events |
| `/topics*` | the admin's rights on each group, checked per group; `POST /topics/users` passes with Community > Users or the group's add-members right. `GET /topics` is open. |
| `/news*` | News (`GET /news` is open) |
| `/memberships/subscriptions*` | Memberships |
| `/donations/*` | Donations |
| `/mentoring/*` | Mentoring |
| `/emailings/*` | Campaigns (manage to send) |
| `/ventures*` | Ventures |
| `/forums/discussions*` | Forums |
| `/companies*` | Companies |
| `/receipts`, `/payment_accounts`, `/order_management/*` | Payments |
| `/admins`, `/roles` | Administrators |
| `/network/sub_networks*` | User settings |
| `/me`, `/network`, `/settings/*`, `/categories` | none |

For anything not listed, read the operation's security scope in the OpenAPI contract. To grant:
Back Office → Admins → the Service App's admin → Permissions tab → enable the module, then retry.
No new token is needed. An integration spanning many modules can use a Service App created by a
Super Admin.
