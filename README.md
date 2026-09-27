# Price Alert MCP Server

This project provides a price-alert backend with:

- a FastAPI REST API
- an MCP server for AI clients
- a scheduled daily alert checker
- Postgres persistence
- email notifications for price drops

The project is designed so MCP clients can create alerts, list alerts, inspect saved alert state, and retrieve a reusable prompt for reviewing alerts.

## Main Components

```text
app.py                         FastAPI REST API and scheduler startup
server/server.py               MCP server
Tools/price.py                 external price API client
Tools/price_alerts/models.py   alert models and database operations
Tools/price_alerts/scheduler.py scheduled price checks and notification logic
Tools/price_alerts/sendMail.py Gmail SMTP email sender
railway_start.py               Railway role-based entrypoint
```

## Environment Variables

Create a `.env` file for local development:

```env
DATABASE_URL=postgresql://...
PRICE_API_BASE_URL=https://your-price-api.example.com
GMAIL_USER=your-gmail@gmail.com
GMAIL_APP_PASSWORD=your-gmail-app-password
```

Optional MCP/server variables:

```env
MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=8000
PRICE_ALERT_SCHEDULER_ENABLED=false
```

Only one running service should have:

```env
PRICE_ALERT_SCHEDULER_ENABLED=true
```

Otherwise multiple services can process the same due alerts and send duplicate emails.

## Install And Run Locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the REST API:

```bash
uvicorn app:app --reload
```

Run the MCP server:

```bash
python -m server.main
```

By default the MCP server uses streamable HTTP on:

```text
http://127.0.0.1:8000/mcp
```

If the REST API is already using port `8000`, set a different MCP port:

```bash
set MCP_PORT=8001
python -m server.main
```

## MCP Client Configuration

For the deployed Railway MCP server, use:

```text
https://price-checker-mcp-production.up.railway.app/mcp
```

Example `mcp.json` style entry:

```json
{
  "mcpServers": {
    "price-checker-mcp": {
      "url": "https://price-checker-mcp-production.up.railway.app/mcp"
    }
  }
}
```

Use transport:

```text
Streamable HTTP
```

## MCP Tools

The MCP server exposes these tools:

```text
check_price_now_tool
create_price_alert_tool
get_price_alert_tool
list_price_alerts_tool
list_price_alerts_due_today_tool
update_price_alert_tool
delete_price_alert_tool
```

### Create Alert

`create_price_alert_tool` only needs:

```json
{
  "product_url": "https://example.com/product",
  "recipient_email": "user@example.com"
}
```

The tool calls `check_price_now_tool` internally and uses the current price as:

```text
starting_price
lowest_notified_price
```

## MCP Resource

The MCP server exposes a read-only resource template:

```text
price-alert://alerts/{alert_id}
```

Example:

```text
price-alert://alerts/alert_123
```

This is not a browser URL and not a Railway URL. It is an MCP resource URI. The MCP client connects to the MCP server URL, then asks that server to read this resource URI.

The resource returns `application/json` with stored alert data, excluding sensitive fields like recipient email.

Reading the resource does not:

- check the current price
- scrape a page
- send email
- update Postgres
- change the alert

## MCP Prompt

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

The prompt returns instructions for an AI client to review a saved alert. The client must still read the alert resource separately:

```text
price-alert://alerts/alert_123
```

Prompt retrieval does not automatically place resource contents into model context and does not execute an LLM workflow on the server.

## Scheduled Price Checks

The scheduler:

1. finds alerts where `next_check_at` is today
2. calls the price API for each product URL
3. updates `latest_price`, `last_updated_at`, and `next_check_at`
4. sends email if the latest price is below `lowest_notified_price`
5. updates `lowest_notified_price` only after email succeeds

To test the scheduled job manually:

```bash
python -c "from Tools.price_alerts.scheduler import run_scheduled_price_alert_check; print(run_scheduled_price_alert_check())"
```

## Railway Deployment

This repo is deployed as two Railway services:

```text
price-alert-api      REST API and scheduler
price-checker-mcp    MCP server
```

Both services use `python railway_start.py`, with different `RAILWAY_SERVICE_ROLE` values.

See `DEPLOYMENT.md` for the current Railway service URLs and environment settings.

## Tests

Run the MCP resource and prompt tests:

```bash
python -m unittest tests.test_mcp_alert_resource_prompt
```

Run a compile check:

```bash
python -m compileall app.py server Tools tests railway_start.py
```

## More Documentation

- `DESIGN.md` explains architecture and data flow.
- `DEPLOYMENT.md` records Railway service details.
- `MCP_USAGE.md` focuses on resource and prompt usage.
