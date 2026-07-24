# imail — Apple Mail CLI (+ MCP)

**imsg-style** local Mail tool. Name family: `imsg` · `imail` · `inotes` · `wa`.

| Surface | Binary | When |
|---------|--------|------|
| **CLI (prefer)** | `imail` | accounts / list / send — saves tokens |
| **MCP** | `mcp-apple-mail` (`apple-mail`) | full search/compose/organize in agents |

```bash
imail doctor
imail accounts
imail list --limit 20
imail send --to a@b.com --subject "Hi" --body "…"
```

MCP stopgap: [patrickfreyer/apple-mail-mcp](https://github.com/patrickfreyer/apple-mail-mcp) (~179★).  
This repo is the CLI we own and grow.

No himalaya. Mail.app only. Permissions: Automation → Mail.
