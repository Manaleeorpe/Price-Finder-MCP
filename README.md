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
  "product_url": "https://www.myntra.com/...",
  "recipient_email": "you@example.com",
  "requester_email": "you@example.com"
}
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

`orpemanalee@gmail.com` is the admin user and can list, read, update, delete, and manually check all alerts.

Every other requester is treated as a user and can only list, read, update, delete, and manually check alerts where `recipient_email` matches their `requester_email`.

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

Most alert tools require `requester_email` for role scoping. Use `run_scheduled_price_alert_check_tool` when you want to manually trigger the same due-alert check that normally runs at 10:00 AM IST. Admin checks all due alerts; regular users check only their own due alerts.

## Review An Alert

The MCP server also exposes a read-only alert resource:

```text
price-alert://users/{requester_email}/alerts/{alert_id}
```

Example:

```text
price-alert://users/you@example.com/alerts/alert_123
```

And a reusable prompt:

```text
review_price_alert
```

Use this when you want the AI client to explain an alert's current status, price change, notification baseline, last check date, and next scheduled check.

The resource is read-only. Reading it does not check prices, send email, or update the alert.
