# imail — Apple Mail CLI (+ MCP)

imsg-style local Mail tool. **No himalaya.**

| Surface | Binary | When |
|---------|--------|------|
| **CLI (prefer)** | `imail` | accounts / list / send — saves tokens |
| **MCP** | `mcp-apple-mail` / `apple-mail` | full search/compose/organize in agents |

## Ours vs Patrick Freyer

| | `imail` (ours) | [patrickfreyer/apple-mail-mcp](https://github.com/patrickfreyer/apple-mail-mcp) (~179★) |
|--|------------------|----------------------------------------------------------------------------------------|
| Role | Thin CLI scaffold we own | Mature MCP (read/search/send/organize) |
| Prefer for | Quick list/send from shell | Agent tool-calling sessions |
| Verdict | Keep growing CLI | **Use for MCP** — don’t reinvent yet |

```bash
imail doctor
imail accounts
imail list --limit 20
imail send --to a@b.com --subject "Hi" --body "…"
```

Permissions: Automation → Mail for Terminal/Cursor.
