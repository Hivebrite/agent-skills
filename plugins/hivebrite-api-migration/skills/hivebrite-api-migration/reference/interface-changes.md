# Interface changes: the only places where a path rewrite is not enough

## Who needs this file

- **v2 or v3 callers**: v3.1 serves the interface you already use. Skip to "v4-only endpoints".
- **v1 callers of `/educations`, `/topics` or `DELETE /users/{id}`**: apply the sections below.
  v3.1 serves the v2 interface for these, and there is no way to request the old one.

| v3.1 endpoint | Interface | What changes for a v1 caller |
|---|---|---|
| `GET /educations`, `GET /educations/{id}` | v2 | field names + `custom_attributes` shape |
| `PUT /educations/{id}` | v2 | field names in the response **and in the request body** (see the warning below) |
| `POST /educations` | v2 | `user_id` and `school` are required (422 without them) |
| `DELETE /educations/{id}` | v2 | nothing |
| `GET /topics`, `GET /topics/{id}` | v2 | root key + fields |
| `POST /topics`, `PUT /topics/{id}` | v2 | root key of the returned object |
| `DELETE /topics/{id}` | v2 | nothing |
| `DELETE /users/{id}` | v2 | `202 Accepted`, asynchronous |

Events (`/network_events` and sub-resources) and categories also serve a newer interface, but only
**add** fields, so existing parsing keeps working.

## Educations (flat `/educations` collection)

| v1 field | v2 field (v3.1) | Note |
|---|---|---|
| `school_name` | `school` | rename |
| `field_of_study_name` | `field_of_study` | rename |
| `field_of_study_id` | removed | resolve by name via `GET /admin/v3.1/settings/field_of_studies` |
| — | `user_id` | added |
| — | `extended_updated_at` | added; also moves when a custom attribute changes |

`custom_attributes` keeps its name but changes shape:

```jsonc
// v1
[{ "id": 42, "name": "class_of", "value": "1998", "type": "text" }]
// v2 (what v3.1 returns)
[{ "class_of": "1998" }]
```

Code that reads `entry["name"]` and `entry["value"]` silently gets nothing. Read by key:
`next((a["class_of"] for a in attrs if "class_of" in a), None)`.

⚠️ **Writes to the flat collection.** `PUT /admin/v3.1/educations/{id}` only accepts the v2 names
(`school`, `field_of_study`). A body that still sends `school_name` / `field_of_study_name` returns
**200 and leaves those fields unchanged**: no error. `POST /admin/v3.1/educations` requires `user_id`
and `school`, and answers 422 without them. Rename the fields in the request body as well as in the response parsing.

⚠️ **Looking an education up by your own id.** v1 let you pass your external id in the path with
`education_key=external_id` on `GET`, `PUT` and `DELETE /educations/{id}`. The flat collection on v3.1
has no `education_key`: it ignores the parameter and reads the path as a Hivebrite education id. The call
then returns 404, or **updates or deletes a different education** whose Hivebrite id happens to equal
your external id. The scan flags every `education_key`. Fix each call site one of two ways:
- call the per-user endpoint instead, which still accepts it:
  `PUT /admin/v3.1/users/{user_id}/educations/{external_id}?education_key=external_id`;
- or resolve the Hivebrite id first (`GET /admin/v3.1/educations?filter[user_id]=...`, match on `external_id`),
  then call the flat endpoint with that id.

**Custom attributes in a write keep the v1 shape** on every education endpoint: send
`[{"name": "class_of", "value": "1998"}]`, even though the flat collection now *returns* them keyed.

**Per-user education endpoints are unchanged.** `GET|POST|PUT|DELETE /users/{user_id}/educations…`
(including `_bulk`) only ever existed in v1, so they keep `school_name`, `field_of_study_name`,
`field_of_study_id` and the v1 `custom_attributes` shape, for both reads and writes. The same record
therefore reads differently on `/educations` and on `/users/{id}/educations`. Handle each call site
according to the endpoint it calls.

## Groups (`/topics`)

| v1 | v2 (v3.1) |
|---|---|
| root `topics` / `topic` | root `groups` / `group` |
| `category`, `category_id` | `categories` (array) |
| `followings` | removed |
| `partners[].paperclip_logo` | `partners[].logo` |
| `experts[].user` (object) | `experts[].user_id` |

The path stays `/topics`. Check the root key first: `response.topics` is now undefined, which breaks
every downstream mapping at once. Unchanged: `GET /topics/categories` (root `topic_categories`).

### Group followers: deprecated, move to the group membership endpoints

`POST` and `DELETE /topics/{topic_id}/followers` still answer on v3.1 but are deprecated with no
successor. A v1 "follower" is a group member (`GET /topics/users` lists them under `status=members`),
so move them to:

| v1 | v3.1 replacement | What changes |
|---|---|---|
| `POST /topics/{id}/followers` `user_ids[]` | `POST /admin/v3.1/topics/users` with `{"members": [{"group_id": 12, "user_ids": [42, 43]}]}` | confirmed members now receive the group's "you've been added" email: v1 added them silently, and there is no option to turn it off |
| `DELETE /topics/{id}/followers?user_ids[]=` | `DELETE /admin/v3.1/topics/users` with the body `{"users": [{"group_id": 12, "user_ids": [42]}]}` | the membership is deleted, where v1 marked it `unfollowed`: the member no longer appears under `status=left` |

Use `members`, not `prospects`: a prospect is a pending request to join, not a follower. Tell the user
about the email before switching an integration that adds people in bulk.

## Deleting a user

`DELETE /admin/v3.1/users/{id}` → `202 Accepted`: the deletion is queued. The body is a short
message ("Request succesfully received, the user will be deleted shortly"), sent as a JSON string.
- Accept 202 as success. The API reference lists 204, so accept that too, and treat any 2xx as done.
- Don't depend on the body.
- A read straight afterwards may still find the user; treat the 202 as the confirmation.

## v4-only endpoints: moved in both targets

| Legacy | New | Notes |
|---|---|---|
| `v1/push_notifications` | `POST /admin/v4/push-notifications` | JSON body (not form-encoded); **200** not 201; per-user `success` map: a member with no device is `success: false` for that member, not a 422; admin needs the push notifications permission |
| `v3/external_link_protection/allowed_domains` | `/admin/v4/network/external-link-protection/allowed-domains` | no v3.1 path exists |
| `v2/network_events/waitlist` | `GET /admin/v4/admin-events/{id}/waitlist` | no v3.1 path. v2 listed every event's waiting list, filtered by `event_id`; v4 lists one event's, filtered by `ticket_id`, with `limit`/`offset` paging. Rebuild `waitlist/summary` from `pagination.total`, per event and per `ticket_id`. A community with the waiting list turned off answers 422 `waitlist_disabled` (403 on v2). |
| `v3/audit_logs/logs` | `GET /admin/v4/audit-logs` | the contract sunsets `/admin/v3.1/audit_logs/logs` on **2027-02-15**, the same day as v1–v3. Cursor paging (`after` / `before`, `page_size` ≤ 100, no total count); lowercase `action` values; new `event_type` vocabulary (`standard`, `custom_action`). An unknown `event_types` / `resource_types` value is refused with 400, while an unknown `actions`, `actor_types` or `surfaces` value returns an **empty page**, so verify the values when a query finds nothing. |

v3.1 and v4 share the host and the token; only the path prefix differs.

## Checklist

1. Search for `/educations`, `/topics`, `DELETE /users/`, `push_notifications`, `allowed_domains`, `audit_logs`.
2. For each match, note the version called today. Only v1 callers of the first three have field work.
3. Educations: v2 names in reads **and** flat-collection writes; keyed `custom_attributes` lookup when
   reading; no `education_key` on the flat collection (use the per-user endpoint or the Hivebrite id).
4. Groups: root key `groups`; `category` → `categories[0]`.
5. User deletion: accept 202 (and 204); don't depend on the body.
6. Push notifications, allowed domains, the events waiting list and audit logs: v4.
7. Group followers: `POST|DELETE /topics/users` (`members` / `users`), and warn about the email.
8. `scripts/compare.py` on every GET endpoint: no key that the code reads may be "only in legacy".
