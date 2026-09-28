# Deployment Services

Deploy this project as two separate services.

## 1. Price Alert API

Runs the REST API and can run the daily price alert scheduler.

Railway service:

```text
Project: price finder backend
Service: price-alert-api
Service ID: fbc80710-d511-427a-a06b-a784190022cb
URL: https://price-alert-api-production.up.railway.app
```

Start command:

```bash
python railway_start.py
```

Recommended scheduler setting:

```env
RAILWAY_SERVICE_ROLE=api
PRICE_ALERT_SCHEDULER_ENABLED=true
```

Public endpoints include:

```text
GET /health
GET /price-alerts
GET /price-alerts/due-today
POST /price-alerts
POST /price-alerts/run-scheduled-check
PATCH /price-alerts/{alert_id}
DELETE /price-alerts/{alert_id}
```

## 2. Price Checker MCP

Runs the MCP tools service.

Railway service:

```text
Project: price finder backend
Service: price-checker-mcp
Service ID: 7da5c3f7-5fcc-4b7f-b42c-528a3a78b7a6
URL: https://price-checker-mcp-production.up.railway.app/mcp
```

Start command:

```bash
python railway_start.py
```

Recommended MCP settings:

```env
RAILWAY_SERVICE_ROLE=mcp
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
PRICE_ALERT_SCHEDULER_ENABLED=false
```

`MCP_PORT` is optional. If it is not set, the MCP service uses the platform `PORT` variable.

Set `PRICE_ALERT_SCHEDULER_ENABLED=true` on this service only if you want the MCP service to run the scheduler instead of the REST API service.

## Shared Environment Variables

Both services need:

```env
DATABASE_URL=...
PRICE_API_BASE_URL=...
GMAIL_USER=...
GMAIL_APP_PASSWORD=...
TESTER_ACCOUNTS_JSON=...
```

Only one deployed service should have `PRICE_ALERT_SCHEDULER_ENABLED=true`, otherwise both services can process the same due alerts and send duplicate emails.

The scheduler waits for 10:00 AM IST (`Asia/Kolkata`) and writes one `price_alert_check_audit` row per checked alert.

`TESTER_ACCOUNTS_JSON` is a JSON array. Each entry needs one bearer `token`, a verified `recipient_email`, and optional `active_alert_limit` and `manual_check_daily_limit`.
