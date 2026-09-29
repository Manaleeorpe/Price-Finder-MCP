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

`requester_email` is used for simple access scoping. If it is `orpemanalee@gmail.com`, the request is treated as admin. Otherwise it can only create/access alerts for the same `recipient_email`.

The tool will check the current product price, create a price alert in Postgres, use the current price as the starting price, and schedule future checks.

## Scheduler

Scheduled checks run once per day at 10:00 AM IST. Each check writes an audit row to `price_alert_check_audit` with the alert id, checked timestamp, observed price when available, and any lookup failure.

When the latest price becomes lower than the stored notification baseline, the system sends an email to the alert recipient and updates the baseline to the new lower price.

## Roles

Simple email scoping is used:

- `orpemanalee@gmail.com` is admin and can list, read, update, delete, and manually check all alerts.
- Any other requester can only list, read, update, delete, and manually check alerts where `recipient_email` matches `requester_email`.

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

Use `run_scheduled_price_alert_check_tool` when you want to manually trigger the same due-alert check that normally runs at 10:00 AM IST. Admin checks all due alerts; regular users check only their own due alerts.

## Review An Alert

The MCP server exposes a read-only alert resource:

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

The resource is read-only. Reading it does not check prices, send email, or update the alert.
