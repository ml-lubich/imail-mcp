# mailapp — Apple Mail CLI (+ MCP later)

Local macOS CLI for **Mail.app** — like [`imsg`](https://github.com/) for Messages.

Uses **Mail.app + AppleScript** (not IMAP/himalaya). Works with every account already in Mail (Exchange, Gmail, iCloud, …).

## Status

Scaffold for our own Polaris-friendly agent tool. For production MCP today we also wire the popular community server:

- [`patrickfreyer/apple-mail-mcp`](https://github.com/patrickfreyer/apple-mail-mcp) (~179★) → `mcp-apple-mail`

This repo is the thin CLI we control and will grow (send/list/search/organize).

## Install

```bash
# symlink
ln -sfn "$(pwd)/mailapp" ~/.local/bin/mailapp
chmod +x mailapp
```

## Usage

```bash
mailapp accounts
mailapp list --account Exchange --limit 20
mailapp send --from mlubich@polariswireless.com --to someone@example.com --subject "Hi" --body "Hello"
mailapp doctor
```

**No digests.** Agents paste in chat; only send when the user asks.

## Permissions

System Settings → Privacy & Security → **Automation**: allow Terminal/Cursor to control Mail.
Full Disk Access may be needed for some search paths later.

## License

MIT
