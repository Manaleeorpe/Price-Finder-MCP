import asyncio
import sys
import os
import threading
from pathlib import Path
from typing import Any

from mcp.server import MCPServer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Tools.json_logging import log_json, log_mcp_tool
from Tools.price import check_price_now
from Tools.price_alerts import (
    PriceAlertCreate,
    PriceAlertStatus,
    PriceAlertUpdate,
    create_db_and_tables,
    create_price_alert,
    delete_price_alert,
    get_price_alert,
    is_database_configured,
    list_price_alerts,
    list_price_alerts_due_today,
    run_daily_price_alert_scheduler,
    session_scope,
    update_price_alert,
)


mcp = MCPServer("Price Checker")
_price_alert_scheduler_thread: threading.Thread | None = None


@mcp.tool()
@log_mcp_tool("check_price_now_tool")
def check_price_now_tool(url: str) -> dict[str, Any]:
    """Check the current product price using the configured price API."""
    return check_price_now(url)


def _alert_to_dict(alert) -> dict[str, Any]:
    return alert.model_dump(mode="json")


@mcp.tool()
@log_mcp_tool("create_price_alert_tool")
def create_price_alert_tool(
    product_url: str,
    recipient_email: str,
    starting_price: int,
    lowest_notified_price: float,
    alert_id: str | None = None,
    status: PriceAlertStatus = PriceAlertStatus.active,
) -> dict[str, Any]:
    """Create a price alert in Postgres with next_check_at set to tomorrow."""
    alert = PriceAlertCreate(
        alert_id=alert_id,
        product_url=product_url,
        recipient_email=recipient_email,
        starting_price=starting_price,
        lowest_notified_price=lowest_notified_price,
        status=status,
    )
    with session_scope() as session:
        return _alert_to_dict(create_price_alert(session, alert))


@mcp.tool()
@log_mcp_tool("get_price_alert_tool")
def get_price_alert_tool(alert_id: str) -> dict[str, Any]:
    """Get a price alert by ID from Postgres."""
    with session_scope() as session:
        alert = get_price_alert(session, alert_id)
        if alert is None:
            return {"success": False, "error": f"Price alert not found: {alert_id}"}
        return _alert_to_dict(alert)


@mcp.tool()
@log_mcp_tool("list_price_alerts_tool")
def list_price_alerts_tool(
    status: PriceAlertStatus | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List price alerts from Postgres."""
    with session_scope() as session:
        return [_alert_to_dict(alert) for alert in list_price_alerts(session, status=status, limit=limit)]


@mcp.tool()
@log_mcp_tool("list_price_alerts_due_today_tool")
def list_price_alerts_due_today_tool(
    status: PriceAlertStatus | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List price alerts whose next_check_at is today."""
    with session_scope() as session:
        return [
            _alert_to_dict(alert)
            for alert in list_price_alerts_due_today(
                session,
                status=status,
                limit=limit,
            )
        ]


@mcp.tool()
@log_mcp_tool("update_price_alert_tool")
def update_price_alert_tool(
    alert_id: str,
    product_url: str | None = None,
    recipient_email: str | None = None,
    starting_price: int | None = None,
    lowest_notified_price: float | None = None,
    latest_price: float | None = None,
    last_updated_at: str | None = None,
    status: PriceAlertStatus | None = None,
    next_check_at: str | None = None,
) -> dict[str, Any]:
    """Update a price alert in Postgres."""
    alert_update = PriceAlertUpdate(
        product_url=product_url,
        recipient_email=recipient_email,
        starting_price=starting_price,
        lowest_notified_price=lowest_notified_price,
        latest_price=latest_price,
        last_updated_at=last_updated_at,
        status=status,
        next_check_at=next_check_at,
    )
    with session_scope() as session:
        alert = update_price_alert(session, alert_id, alert_update)
        if alert is None:
            return {"success": False, "error": f"Price alert not found: {alert_id}"}
        return _alert_to_dict(alert)


@mcp.tool()
@log_mcp_tool("delete_price_alert_tool")
def delete_price_alert_tool(alert_id: str) -> dict[str, Any]:
    """Delete a price alert from Postgres."""
    with session_scope() as session:
        deleted = delete_price_alert(session, alert_id)
        if not deleted:
            return {"success": False, "error": f"Price alert not found: {alert_id}"}
        return {"deleted": True, "alert_id": alert_id}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _run_scheduler_thread() -> None:
    try:
        asyncio.run(run_daily_price_alert_scheduler())
    except Exception as error:
        log_json(
            "price_alerts.scheduler.thread_failed",
            error={"type": error.__class__.__name__, "message": str(error)},
        )


def _prepare_database_and_scheduler() -> None:
    global _price_alert_scheduler_thread

    if not is_database_configured():
        return

    create_db_and_tables()
    if not _env_bool("PRICE_ALERT_SCHEDULER_ENABLED", False):
        return

    if _price_alert_scheduler_thread is not None and _price_alert_scheduler_thread.is_alive():
        return

    _price_alert_scheduler_thread = threading.Thread(
        target=_run_scheduler_thread,
        name="price-alert-scheduler",
        daemon=True,
    )
    _price_alert_scheduler_thread.start()


def run_mcp():
    """Run the MCP server with environment-configurable transport settings."""
    _prepare_database_and_scheduler()

    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run(transport=transport)
        return

    options = {
        "transport": transport,
        "host": os.getenv("MCP_HOST", "127.0.0.1"),
        "port": int(os.getenv("MCP_PORT", os.getenv("PORT", "8000"))),
    }
    if transport == "streamable-http":
        options["stateless_http"] = _env_bool("MCP_STATELESS_HTTP", True)

    mcp.run(**options)


if __name__ == "__main__":
    run_mcp()
