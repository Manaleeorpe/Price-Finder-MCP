# Design

## System Overview

This project is a price-alert backend with two public surfaces over the same Postgres data:

1. A FastAPI REST service in `app.py`.
2. An MCP server in `server/server.py`.

Both services use shared business logic from `Tools/price_alerts`. Price scraping is delegated to an external price API through `Tools/price.py`; this project does not scrape product pages directly.

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

`recipient_email` is used for both notification delivery and simple user scoping. It is intentionally excluded from the MCP read-only resource payload.

The `price_alert_check_audit` table stores one append-only row for each alert check:

- `audit_id`
- `alert_id`
- `product_url`
- `checked_at`
- `checked_on`
- `price`
- `success`
- `error`

## Access Scoping

The current codebase uses caller-supplied `requester_email` as the identity boundary.

- `orpemanalee@gmail.com` is admin and can see, update, delete, and manually check all alerts.
- Every other requester is scoped to alerts where `recipient_email` matches `requester_email`.

This is simple email-based filtering. A future login system could replace caller-supplied `requester_email` while preserving the same recipient-email scoping behavior.

## REST API

`app.py` exposes:

```text
GET /health
GET /price-alerts
GET /price-alerts/due-today
GET /price-alerts/{alert_id}
POST /price-alerts
POST /price-alerts/run-scheduled-check
PATCH /price-alerts/{alert_id}
DELETE /price-alerts/{alert_id}
```

Alert REST endpoints require `requester_email` as a query parameter.

## MCP Server

Tools:

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

`create_price_alert_tool` accepts `product_url`, `recipient_email`, and `requester_email`, calls `check_price_now_tool` internally, and uses the fetched current price as both `starting_price` and `lowest_notified_price`.

Most alert tools require `requester_email` for scoping. Admin can access all alerts; regular users are scoped to matching `recipient_email`.

Resource:

```text
price-alert://users/{requester_email}/alerts/{alert_id}
```

Prompt:

```text
review_price_alert
```

Required arguments:

```json
{
  "requester_email": "you@example.com",
  "alert_id": "alert_123"
}
```

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

Only one deployed service should run the scheduler. Running it from multiple services can duplicate price checks and notification emails.

## Required Environment

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
