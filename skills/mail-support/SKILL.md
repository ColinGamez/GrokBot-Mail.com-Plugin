# Mail.com support triage

Use the `mailcom` MCP tools for anything involving the user's mail.com mailbox.
The mailbox is used for projects + support, so prefer careful, reversible actions.

## Workflow

1. Start with `folder_stats("INBOX")` for counts, `list_folders` if you don't
   know the layout, then `list_emails` (unread first:
   `list_emails(folder="INBOX", unread_only=true)`).
2. For support triage, `search_emails` by sender/subject keywords or date window.
   Dates use `DD-Mon-YYYY`, e.g. `since="29-Sep-2026"`.
3. Always `read_email` before replying, summarizing, or marking handled.
   Use `download_attachment` for logs/screenshots (base64, capped).
4. Draft support replies with `reply_email`. Keep the original thread;
   quote briefly. Do NOT send without user approval unless the user
   explicitly allowed auto-reply for that category.
5. `mark_read` only after the item is actually handled or summarized.
6. Never `delete_email` unless the user asked for deletion.

## Safety

- Credentials come from server env vars (`MAILCOM_EMAIL` / `MAILCOM_PASSWORD`).
  Never ask for them in plain chat after setup; never print them.
- Sending is a side effect: confirm recipient + subject + body first.
- Truncate long threads when summarizing; cite UID + subject + date.
