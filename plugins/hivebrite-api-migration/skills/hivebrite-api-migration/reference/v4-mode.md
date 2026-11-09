# `--target v4`: moving endpoints straight to their v4 replacement

v4 is where the Admin API develops: new capability lands there only, and each v3.1 endpoint it
replaces is deprecated, then removed on the date the API reference gives for it (`x-sunset-date`). In `--target v4`, every endpoint that **has** a v4
successor moves now; everything else lands on v3.1. The result is one migration instead of two.

## Find the successors mechanically

Do not rely on a hand-written list: the contract is updated every release. `scripts/scan.py --target v4`
already marks every call with a successor as V4-MOVE, legacy and v3.1 calls alike, with the v4 path as its
target. To look up paths that aren't in the code yet, run:

```bash
scripts/v4_successors.sh /admin/v3.1/network_events /admin/v3.1/news /admin/v3.1/companies ...
```

For each path and method it prints `deprecated`, `x-successor` (resolved to the v4 method + path),
`x-deprecated-date` and `x-sunset-date`. No successor means the endpoint stays on v3.1, even in
v4 mode. A sunset date on or before 15 Feb 2027 means v4 is **required**, not optional.

Then read the successor operation in the contract (request schema, response schema, error codes)
before writing any code. Extract only the operations you need with `jq`; the full contract is several MB:

```bash
spec="$(mktemp -d)/hb-admin.json"
curl -s https://docs.hivebrite.com/partner/admin/openapi.json -o "$spec"
jq '.paths["/admin/v4/news"].post' "$spec"
```

## v4 is a redesign, not a re-mount

Expect real code changes per endpoint:

| Module (v3.1 → v4) | Watch for |
|---|---|
| Events: `network_events` → `admin-events` + sub-resources | registrations replace RSVPs; registration questions replace event custom fields; tickets, bookings, attendees and registrations are listed per event or across all events; publish, unpublish and cancel are separate calls |
| News: `news`, `news/categories` → `news`, `news-categories` | `published_at` replaces `published`; files are uploaded first; `locale` picks the translation returned rather than filtering |
| Forums: `forums/discussions` → `forum-discussions`, `forum-categories` | `on_behalf_of_user_id` replaces `user_id`; deleting keeps the replies; reaction and comment counts are on each discussion |
| Organizations: `companies`, `categories` → `organizations`, `organization-categories` | cursor paging; `search` matches part of a name, `name[]` exact names; `jurisdiction` replaces `juridiction` |
| Media Center: `media_center/folders`, `/files` → `media-folders`, `media-files` | UUID ids; moves are a PATCH of `parent_id`; download links come with every read; files up to 1 GB |
| Posts, comments: `posts`, `comments` → `posts`, `comments` | files via presigned upload (below); post scheduling and bulk comments are v4-only |
| Audit logs: `audit_logs/logs` → `audit-logs` | see `interface-changes.md`; required, not optional |

Not on v4 yet, so keep v3.1 for:
- linking events to a news post
- the industries list (`GET /admin/v3.1/settings/industries`)
- members' Media Center portfolios
- categories for emailings, donations and portfolios

The contract is authoritative: re-check with the script.

## Shared v4 conventions

- **Files**: `POST /admin/v4/uploads/presign` → `PUT` the bytes to the returned URL → reference the
  upload by its `blob_id` in the create or update call. That is two extra calls per file, done before
  the batch that uses them, and it replaces multipart uploads on every v4 resource that takes a file:
  posts, comments, events, news, organizations, forum discussions and the Media Center. Uploads are
  virus-scanned before they are served, so a file link can be empty for a few seconds after the write;
  file links expire (`expires_at`), so read the record again rather than storing them.
- **Bulk**: most v4 writes have a `/bulk` variant. Batches of about 100 items keep responses quick
  and count as one request against the 300/min limit.
- **Paging**: cursor (`after` / `before`, `page_size`) on the newer resources. There is no total
  count; walk until `has_more: false`.
- **Retries**: v4 writes are safe to retry. Read the contract for the idempotency header an operation supports.
- **Refusals**: 403 `forbidden_permission` names `required_permission`; 403 `forbidden_entitlement`
  means the community does not have the feature. When a list has `meta.scoped_by_permission: true`,
  an empty page does not prove there is no data.
- **Lists lag writes**: a new record can take a moment to appear in list endpoints. Read by id to confirm.

## Order of work

1. Do the v3.1 stack change first (contract, step 2 of SKILL.md). v4 calls need it too.
2. Move v4-required endpoints (push notifications, allowed domains, audit logs).
3. Then one module at a time: implement the v4 call next to the v3.1 one, diff the results on
   sandbox, switch, and remove the v3.1 call.
4. Report what is still on v3.1, and the sunset date of anything deprecated.
