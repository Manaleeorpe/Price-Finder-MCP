# Price Alert MCP Usage

## Read A Price Alert Resource

The MCP server exposes a read-only resource template:

```text
price-alert://alerts/{alert_id}
```

Example alert resource URI:

```text
price-alert://alerts/alert_123
```

The resource returns `application/json` with alert fields such as:

```json
{
  "alert_id": "alert_123",
  "product_url": "https://example.com/product",
  "starting_price": 100.0,
  "lowest_notified_price": 90.0,
  "latest_price": 95.0,
  "currency": null,
  "last_updated_at": "2026-09-27",
  "next_check_at": "2026-09-28",
  "status": "active",
  "last_notification_at": null,
  "notification_delivery_status": null
}
```

The resource does not include recipient email, tokens, or credentials. Reading it does not scrape prices, send email, update the database, or modify the alert.

Every MCP request must include a tester bearer token. The token determines the owner id, role, verified recipient email, active alert limit, and daily manual-check limit. `orpemanalee@gmail.com` is the admin recipient and can access all alerts. Other testers can only access alerts where `owner_id` matches their token-derived owner id.

## Retrieve The Review Prompt

The MCP server exposes this prompt:

```text
review_price_alert
```

Required argument:

```json
{
  "alert_id": "alert_123"
}
```

The prompt returns an instruction message that tells the AI client how to review the alert. The client must still read the resource, for example `price-alert://alerts/alert_123`, after retrieving the prompt. Prompt registration and prompt retrieval do not automatically place resource contents into model context.

The prompt is only a reusable instruction template. The MCP server does not run an LLM workflow, trigger a fresh price check, send email, or update the alert when the prompt is retrieved.
