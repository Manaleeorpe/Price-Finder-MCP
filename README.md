# Price Alert MCP

Use this MCP server to create and manage product price alerts from an AI client such as Codex, Claude Desktop, or MCP Inspector.

Currently supported website:

```text
Myntra
```

## MCP Server URL

Connect your MCP client with Streamable HTTP:

```text
https://price-checker-mcp-production.up.railway.app/mcp
```

Example server ID:

```text
price-checker-mcp
```

## Add A Price Alert

Use the MCP tool:

```text
create_price_alert_tool
```

Required inputs:

```json
{
  "product_url": "https://www.myntra.com/..."
}
```

MCP requests must include the tester bearer token. The server derives the owner id and verified recipient email from that token; the model cannot choose a recipient email.

```text
Authorization: Bearer replace-with-a-long-random-token
```

The tool will:

1. Check the current product price.
2. Create a price alert in Postgres.
3. Use the current price as the starting price.
4. Use the current price as the notification baseline.
5. Schedule the alert for future checks.

Example prompt to your MCP client:

```text
Create a price alert for this Myntra product:
https://www.myntra.com/...
Send notifications to you@example.com
```

## What Happens After An Alert Is Created

The scheduler checks due alerts automatically.

When the latest price becomes lower than the stored notification baseline, the system sends an email to the alert recipient and updates the baseline to the new lower price.

Scheduled checks run once per day at 10:00 AM IST. Each check writes an audit row to `price_alert_check_audit` with the alert id, checked timestamp, observed price when available, and any price lookup failure.

## Roles

Each tester has one bearer token configured in `TESTER_ACCOUNTS_JSON`. The owner id is derived from the token, and the verified recipient email is stored for that owner.

`orpemanalee@gmail.com` is the admin recipient and can list, read, update, delete, and manually check all alerts.

Every other tester is treated as a user and can only list, read, update, delete, and manually check alerts where `owner_id` matches their bearer token.

Example tester config:

```json
[
  {
    "token": "replace-with-a-long-random-token",
    "recipient_email": "you@example.com",
    "active_alert_limit": 5,
    "manual_check_daily_limit": 3
  }
]
```

## Useful MCP Tools

```text
create_price_alert_tool
list_price_alerts_tool
list_price_alerts_due_today_tool
run_scheduled_price_alert_check_tool
get_price_alert_tool
update_price_alert_tool
delete_price_alert_tool
check_price_now_tool
```

Use `run_scheduled_price_alert_check_tool` when you want to manually trigger the same due-alert check that normally runs at 10:00 AM IST. Admin checks all due alerts; regular users check only their own due alerts. Manual checks are limited per tester per day.

## Review An Alert

The MCP server also exposes a read-only alert resource:

```text
price-alert://alerts/{alert_id}
```

Example:

```text
price-alert://alerts/alert_123
```

And a reusable prompt:

```text
review_price_alert
```

Use this when you want the AI client to explain an alert's current status, price change, notification baseline, last check date, and next scheduled check.

The resource is read-only. Reading it does not check prices, send email, or update the alert.
