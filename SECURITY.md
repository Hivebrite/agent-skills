# Security

These skills run in your AI assistant with your access to your Hivebrite community, and some ship
scripts that run on your machine. We hold them to these rules:

- Scripts use only the language's standard library. They call Hivebrite hosts (`*.hivebrite.com`)
  and, when you set one, the legacy host of your community (`HB_LEGACY_HOST`, which can be your own
  domain): `compare.py` sends your legacy token there and nowhere else.
- No skill asks for, logs or stores a credential. Secrets are read from environment variables you
  set, never passed as arguments: scripts hand them to `curl` on its standard input, so they don't
  appear in the shell history or the process list.
- On the lines it reports, the scanner masks the quoted values of common credential keys
  (`"password": "..."`), on a best-effort basis: unquoted values, such as `password=...` in a form body,
  `curl -u id:...` or `?access_token=...`, still print. Don't run the scan on code with hard-coded
  secrets. Downloaded data goes to a cache directory only you can read.
- Every release is an immutable GitHub release, tagged `<plugin>--v<version>`. Pin one if you need
  a fixed version.

Install these skills only from `github.com/Hivebrite/agent-skills`. A copy from anywhere
else may have been changed.

## Reporting a vulnerability

Open a ticket at [support.hivebrite.com](https://support.hivebrite.com) with "Security" in the
subject. Don't open a public issue or pull request.
