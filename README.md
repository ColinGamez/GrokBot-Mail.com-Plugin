# GrokBot Mail.com Plugin

> **Status: archived.** Mail.com gates POP3/IMAP (and forwarding-out) behind
> Premium, and exposes no public API — so this connector can't reach a free
> mailbox. Kept here for reference / revival if that ever changes. It works
> as-is against any standard IMAP/SMTP host (e.g. Gmail) via env vars.

Mail.com connector for GrokBot, as an MCP server. Mail.com has no public REST API,
so this wraps the official mailbox protocols:

- IMAP `imap.mail.com:993` (SSL)
- SMTP `smtp.mail.com:587` (STARTTLS, or `465` SSL)

Tools: `check_connection`, `list_folders`, `folder_stats`, `list_emails`, `search_emails`,
`read_email`, `download_attachment`, `send_email`, `reply_email`, `mark_read`, `delete_email`.
Plus a `mail-support` skill for project/support triage.

## 1. Enable IMAP in mail.com

In the webmailer, click the gear icon (bottom-left, under the folder list)
-> Settings -> POP3 & IMAP -> Enable access via POP3 and IMAP -> Save.
Login elsewhere is your full address (e.g. `ColinKenny@programmer.net`).

## 2. Run locally

```powershell
pip install -r requirements.txt
copy .env.example .env   # fill in MAILCOM_EMAIL + MAILCOM_PASSWORD
python server.py         # stdio mode
```

Self-host HTTP mode:

```powershell
$env:MCP_TRANSPORT="streamable-http"; $env:MCP_PORT="8000"; python server.py
# endpoint: http://localhost:8000/mcp
```

Or Docker: `docker build -t mailcom-mcp .; docker run -p 8000:8000 --env-file .env mailcom-mcp`

## 3. Add to GrokBot (personal use, easiest)

GrokBot runs on a cloud computer — add the server in chat, not a config file.
Push this repo to GitHub first, then tell your bot:

```text
Add a custom MCP server called mailcom that runs:
python /path/to/server.py
with env vars MAILCOM_EMAIL and MAILCOM_PASSWORD (ask me for them as secrets).
```

Or if you self-host: `Add a custom MCP server called mailcom at https://your-host/mcp`.

Then: Settings -> Plugins -> Yours -> `mailcom`, attach with `@mailcom` in chat.

Your bot was right: connectors are just MCP servers packaged as plugins —
`plugin.json` + `mcp.json`/`​.mcp.json` + `skills/` is that packaging here.

## 4. Publish to marketplace (optional)

1. Push this repo public.
2. Submit at `cursor.com/marketplace/publish` (Agent Plugins layout).
3. Review is manual; updates re-reviewed.

## Security notes

- Never commit `.env` or real credentials (see `.gitignore`).
- Sending/deleting are side effects — the skill requires confirmation first.
- Prefer `mark_read` over `delete_email`.
