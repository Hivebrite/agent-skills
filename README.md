# Hivebrite agent skills

Official Hivebrite skills for AI assistants. A skill teaches your assistant what the documentation
can't: which calls look successful but do nothing, which endpoint to move to, and how to prove the
result.

The skills use the open [Agent Skills](https://agentskills.io) format (`SKILL.md`), so they work in
Claude, Codex, Cursor, GitHub Copilot, Gemini CLI and any other assistant that reads it.

| Plugin | For | What it needs |
|---|---|---|
| [`hivebrite-api-migration`](plugins/hivebrite-api-migration) | Developers whose integrations call Admin API v1, v2 or v3 | A coding assistant that can edit files and run commands |

Install only the plugins you need. Your assistant reads every installed skill's description at the
start of each session, so each extra plugin costs tokens even when you don't use it.

## Install

### Claude Code and Claude Cowork

```
/plugin marketplace add Hivebrite/agent-skills
/plugin install hivebrite-api-migration@hivebrite
```

Replace `hivebrite-api-migration` with the plugin you want. To get new versions, run
`/plugin marketplace update hivebrite`. `claude plugin details hivebrite-api-migration` shows how many
tokens the plugin adds to each session.

### Claude.ai and Claude Desktop

Download the plugin's zip from the [latest release](https://github.com/Hivebrite/agent-skills/releases)
and upload each skill folder in **Settings → Capabilities → Skills**.

### OpenAI Codex

```
codex plugin marketplace add Hivebrite/agent-skills
```

Then open `/plugins` and install the plugin you want.

### GitHub Copilot (CLI and VS Code)

```
copilot plugin marketplace add Hivebrite/agent-skills
copilot plugin install hivebrite-api-migration@hivebrite
```

In VS Code, add the marketplace with `/plugin marketplace add Hivebrite/agent-skills`.

### Cursor

Add this repository as a plugin marketplace (**Dashboard → Plugins & MCPs → Add Marketplace →
Import from Repo**), then install the plugin from the Customize panel.

### Gemini CLI and other assistants

Install a single skill straight from this repository:

```
gemini skills install https://github.com/Hivebrite/agent-skills --path plugins/hivebrite-api-migration/skills/hivebrite-api-migration
```

For any other assistant, copy the skill folders from `plugins/<plugin>/skills/` into the folder
where it reads skills (often `.agents/skills/` in your project or `~/.agents/skills/`).

### Support levels

| Assistant | Level |
|---|---|
| Claude Code, Claude Cowork, claude.ai | **Tested.** Every release is checked here. |
| Codex, Cursor, GitHub Copilot, Gemini CLI | **Best effort.** The manifests follow each vendor's published format, but releases are not tested in these tools. |
| Anything else that reads `SKILL.md` | Copy the folder. |

Releases are tagged per plugin (`hivebrite-api-migration--v1.0.2`). To pin a version, install from a tag
instead of `main`.

## The plugins

### `hivebrite-api-migration`

Moves code that calls Admin API v1, v2 or v3 to v3.1 or v4 before those versions stop working on
**15 February 2027**. See [its README](plugins/hivebrite-api-migration/README.md).

More plugins will follow, for community admins and members using the Hivebrite connectors, and for
developers building on the partner API.

## Documentation and support

- Knowledge Base: [support.hivebrite.com](https://support.hivebrite.com)
- Release notes, API release notes and the API migration guide:
  [yourhivebrite.zendesk.com](https://yourhivebrite.zendesk.com/hc/en-us)
- API reference: [docs.hivebrite.com/partner/admin](https://docs.hivebrite.com/partner/admin)
- Questions and problems: open a ticket at [support.hivebrite.com](https://support.hivebrite.com).
  Issues on this repository are not monitored.
- Security: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
