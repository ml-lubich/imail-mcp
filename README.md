# imail — Apple Mail CLI (+ MCP)

**Package brand:** `imail-mcp` · **CLI:** `imail` · **PyPI today:** `pip install mac-imail` (target PyPI name `imail-mcp` when PyPI new-project limit clears).


**imsg-style** local Mail tool. Name family: `imsg` · `imail` · `inotes` · `wa`.

## Install

```bash
pip install -e ".[dev]"   # from repo root
# or (future) brew install imail
```

After install, the `imail` command is on your PATH (via pip entry point). The old bash script is preserved as `imail.bash.bak` for reference.

## CLI-first vs MCP

| Surface | Binary | When |
|---------|--------|------|
| **CLI (prefer)** | `imail` | accounts / list / send / organize — saves tokens |
| **MCP** | `mcp-apple-mail` (`apple-mail`) | full search/compose/organize in agents |

No himalaya. Mail.app only. Permissions: **Automation → Mail**.

## Account walls

Work (Polaris/Exchange) and personal (Google, metropol, lupfr) must **never** mix. Auto-send **must** pass `--from` on the correct wall.

```bash
imail walls
```

Configuration lives in `accounts.json` at repo root.

## Commands

```bash
imail -h
imail doctor
imail accounts
imail list --limit 20
imail list --account Exchange --mailbox INBOX --json
imail organize --account polaris --limit 100
imail send --from mlubich@polariswireless.com --to a@b.com \
  --subject "Hi" --body "Hello"
imail version
```

Legacy wrapper (same as `imail organize`):

```bash
python3 organize-all.py --account google --limit 200
```

## Agent introspection

Agents can discover the full command catalog as JSON:

```bash
imail agent schema
imail agent guide
imail agent -h
```

Example schema excerpt:

```json
{
  "version": "0.1.0",
  "tool": "imail",
  "walls": { "work": { ... }, "personal": { ... } },
  "commands": [ { "name": "list", "help": "...", "params": [...] } ]
}
```

MCP stopgap: [patrickfreyer/apple-mail-mcp](https://github.com/patrickfreyer/apple-mail-mcp) (~179★).  
This repo is the CLI we own and grow.

## Development

```bash
cd ~/dev/imail
python3 -m pip install -e ".[dev]"
pytest -q
```
