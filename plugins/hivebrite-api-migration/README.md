# Hivebrite Admin API migration skill

A skill for AI coding assistants that migrates code calling the Hivebrite Admin API v1, v2 or v3 to
v3.1, or straight to v4, in any language. The legacy versions stop working on **15 February 2027**.

It scans your repository for every legacy call, rewrites authentication and endpoints, applies the response
changes that fail silently, and proves the result: a re-scan that finds nothing left, a smoke test on your
sandbox, and a comparison of legacy and v3.1 response shapes. Full instructions:
[`SKILL.md`](skills/hivebrite-api-migration/SKILL.md).

## Install

It works in any coding assistant that reads Agent Skills and can edit files and run commands:
Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI and others. The
[main README](../../README.md#install) has the install command for each. For example:

```
/plugin marketplace add Hivebrite/agent-skills          # Claude Code
codex plugin marketplace add Hivebrite/agent-skills     # Codex, then /plugins
gemini skills install https://github.com/Hivebrite/agent-skills --path plugins/hivebrite-api-migration/skills/hivebrite-api-migration
```

Or copy the skill folder into the folder where your assistant reads skills (often `.agents/skills/`
in your project, or `~/.agents/skills/`):

```bash
git clone https://github.com/Hivebrite/agent-skills.git
cp -R agent-skills/plugins/hivebrite-api-migration/skills/hivebrite-api-migration ~/.agents/skills/
```

Each [release](https://github.com/Hivebrite/agent-skills/releases) also has the skill as a zip. An
assistant without skills support can follow [`SKILL.md`](skills/hivebrite-api-migration/SKILL.md) as
instructions: the scripts are plain Python and bash.

Then open your integration's repository and ask, for example:

> Migrate this integration to the new Hivebrite API, target v3.1, zone eu.

## Requirements

- A coding assistant that can edit files and run commands in your repository
- Python 3.8 or later (standard library only) and `curl`; `jq` only for the v4 successor lookup
- A Service App on a sandbox community, its client id and secret exported in your shell

No MCP server or other setup is needed. The skill never asks for, prints or stores a credential, and its
scripts only make read (GET) requests.

## Documentation and support

- Migration guide: [How to migrate your Admin API integration to the new API stack (v3.1+)](https://yourhivebrite.zendesk.com/hc/en-us/articles/29861483955868)
- With an AI assistant: [How to migrate your Admin API integration with an AI assistant](https://yourhivebrite.zendesk.com/hc/en-us/articles/31665193978140-How-to-migrate-your-Admin-API-integration-with-an-AI-assistant)
- API reference: [docs.hivebrite.com/partner/admin](https://docs.hivebrite.com/partner/admin)
- Questions and problems: open a ticket at [support.hivebrite.com](https://support.hivebrite.com) and include
  the `X-Request-Id` of any failing call. Issues on this repository are not monitored.

## License

[MIT](../../LICENSE)
