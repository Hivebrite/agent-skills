# Changelog

### 1.0.2

First release.

- `scan.py` inventories every legacy Admin API call in a repository, in any language, with its v3.1 path,
  the interface change it needs, and its v4 successor and sunset date from the live API reference.
- Rewrites to Service App authentication (`client_credentials`, `audience=partner`) and the v3.1 or v4 endpoints.
- Applies the v1 interface changes on educations, groups (`/topics`) and user deletion, and moves push
  notifications, allowed domains and audit logs to v4.
- Verification on a sandbox: re-scan to zero, `smoke-test.sh`, and `compare.py` to diff legacy and v3.1
  response shapes.
