# Design

## System Overview

This project is a price-alert backend with two public surfaces over the same Postgres data:

1. A FastAPI REST service in `app.py`.
2. An MCP server in `server/server.py`.

Both services use shared business logic from `Tools/price_alerts`. Price scraping is delegated to an external price API through `Tools/price.py`; this project does not scrape product pages directly.

## Architecture

```text
MCP Client / Inspector
        |
        | Streamable HTTP
        v
Price Checker MCP service
server/server.py
        |
        | shared alert service functions
        v
Tools/price_alerts/models.py
        |
        v
Postgres


REST Client / Scheduler runtime
        |
        | HTTP
        v
Price Alert API service
app.py
        |
        | shared alert service functions
        v
Tools/price_alerts/models.py
        |
        v
Postgres


Scheduled alert check
Tools/price_alerts/scheduler.py
        |
        | calls
        v
Tools/price.py -> External price API
        |
        | optional notification
        v
Tools/price_alerts/sendMail.py -> Gmail SMTP
```

## Runtime Entry Points

`railway_start.py` selects the runtime role from `RAILWAY_SERVICE_ROLE`.

```text
RAILWAY_SERVICE_ROLE=api -> run FastAPI app
RAILWAY_SERVICE_ROLE=mcp -> run MCP server
```

The Railway `Procfile` runs:

```bash
python railway_start.py
```

## Data Model

The `price_alerts` table stores:

- `alert_id`
- `product_url`
- `recipient_email`
- `starting_price`
- `lowest_notified_price`
- `latest_price`
- `last_updated_at`
- `next_check_at`
- `status`

`recipient_email` is stored for notification delivery, but it is intentionally excluded from the MCP read-only resource.

`latest_price` and `last_updated_at` are updated by scheduled checks. `next_check_at` controls which alerts are due for the next scheduled run.

The `price_alert_check_audit` table stores one append-only row for each alert check:

- `audit_id`
- `alert_id`
- `product_url`
- `checked_at`
- `checked_on`
- `price`
- `success`
- `error`

This table is written every time a due alert is checked, including failed price lookups where `price` is unavailable.

## REST API

`app.py` exposes:

```text
GET /health
GET /price-alerts
GET /price-alerts/due-today
GET /price-alerts/{alert_id}
POST /price-alerts
PATCH /price-alerts/{alert_id}
DELETE /price-alerts/{alert_id}
```

FastAPI startup creates/migrates database tables when `DATABASE_URL` is configured. It also starts the scheduler when:

```env
PRICE_ALERT_SCHEDULER_ENABLED=true
```

## MCP Server

`server/server.py` uses the installed `mcp.server.MCPServer` SDK.

### Tools

Tools can perform actions:

```text
check_price_now_tool
create_price_alert_tool
get_price_alert_tool
list_price_alerts_tool
list_price_alerts_due_today_tool
run_scheduled_price_alert_check_tool
update_price_alert_tool
delete_price_alert_tool
```

`create_price_alert_tool` accepts `product_url` and `recipient_email`, calls `check_price_now_tool` internally, and uses the fetched current price as both `starting_price` and `lowest_notified_price`.

`run_scheduled_price_alert_check_tool` manually triggers the same due-alert check used by the daily 10:00 AM Asia/Kolkata scheduler.

### Resource

The MCP read-only resource template is:

```text
price-alert://alerts/{alert_id}
```

The MCP client connects to the Railway MCP server URL, then asks that server to read a resource URI such as:

```text
price-alert://alerts/alert_123
```

This resource returns sanitized JSON for a stored alert. It does not include recipient email, tokens, or credentials. It does not check current prices, send email, update Postgres, or mutate the alert.

### Prompt

The MCP prompt is:

```text
review_price_alert
```

It takes one required argument:

```json
{
  "alert_id": "alert_123"
}
```

The prompt is only an instruction template. It tells the MCP client or AI to read the alert resource and explain the stored alert state. Retrieving the prompt does not automatically inject resource contents into model context, call an LLM, check prices, send email, or update the database.

## Scheduler Flow

The scheduler lives in `Tools/price_alerts/scheduler.py`.

1. Wait until the next 10:00 AM Asia/Kolkata run.
2. Fetch alerts where `next_check_at` matches today's Asia/Kolkata date.
3. For each due alert:
   - call the configured price API through `check_price_now`
   - extract `latest_price`
   - insert a `price_alert_check_audit` row with the checked price or failure reason
   - update `latest_price`, `last_updated_at`, and `next_check_at`
   - if `latest_price < lowest_notified_price`, send an email
   - only after email succeeds, update `lowest_notified_price`
4. Repeat daily at 10:00 AM Asia/Kolkata.

Only one deployed service should run the scheduler. Running it from multiple services can duplicate price checks and notification emails.

## External Dependencies

```text
Postgres              alert persistence
External price API    current product price lookup
Gmail SMTP            notification email delivery
Railway               hosting
```

Required environment variables:

```env
DATABASE_URL=...
PRICE_API_BASE_URL=...
GMAIL_USER=...
GMAIL_APP_PASSWORD=...
```

For MCP deployment:

```env
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
```

## Error Handling Pattern

Existing MCP tools return structured dictionaries for expected failures, for example:

```json
{
  "success": false,
  "error": "Price alert not found: alert_123"
}
```

The read-only resource reuses `get_price_alert_tool` to preserve the same get-alert boundary and failure shape.

## Authentication And Ownership

The current codebase does not implement user authentication or explicit ownership checks for alert tools. The MCP resource preserves the current boundary by reusing `get_price_alert_tool` instead of adding a separate database query. If authentication is added later, it should be implemented in the shared service/tool boundary so tools and resources enforce the same rules.

## Deployment Topology

On Railway, this project is deployed as two services in the same project:

```text
price-alert-api      REST API and scheduler
price-checker-mcp    MCP server
```

See `DEPLOYMENT.md` for service IDs, URLs, and environment settings.
