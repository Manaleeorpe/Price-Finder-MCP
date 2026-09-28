import asyncio
import json
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
    consume_manual_price_check,
    count_active_price_alerts,
    create_db_and_tables,
    create_price_alert,
    delete_price_alert,
    get_tester_account,
    get_price_alert,
    is_database_configured,
    list_price_alerts,
    list_price_alerts_due_today,
    run_daily_price_alert_scheduler,
    run_scheduled_price_alert_check,
    session_scope,
    update_price_alert,
)
from Tools.price_alerts.auth import (
    EnvBearerTokenVerifier,
    TesterContext,
    get_current_tester_context,
    get_mcp_auth_settings,
)
from Tools.price_alerts.scheduler import extract_latest_price


mcp = MCPServer(
    "Price Checker",
    auth=get_mcp_auth_settings(),
    token_verifier=EnvBearerTokenVerifier(),
)
_price_alert_scheduler_thread: threading.Thread | None = None


@mcp.tool()
@log_mcp_tool("check_price_now_tool")
def check_price_now_tool(url: str) -> dict[str, Any]:
    """Check the current product price using the configured price API."""
    return check_price_now(url)


def _alert_to_dict(alert) -> dict[str, Any]:
    return alert.model_dump(mode="json")


def _access_denied() -> dict[str, Any]:
    return {"success": False, "error": "Not authorized for this price alert"}


def _authentication_required() -> dict[str, Any]:
    return {"success": False, "error": "Authentication required"}


def _limit_exceeded(message: str) -> dict[str, Any]:
    return {"success": False, "error": message}


def _current_tester() -> TesterContext | None:
    return get_current_tester_context()


def _owner_scope_for(tester: TesterContext) -> str | None:
    return None if tester.is_admin else tester.owner_id


def _can_access_alert(tester: TesterContext, alert) -> bool:
    return tester.is_admin or alert.owner_id == tester.owner_id


def _alert_resource_payload(alert_id: str) -> dict[str, Any]:
    alert = get_price_alert_tool(alert_id)
    if alert.get("success") is False:
        return alert

    return {
        "alert_id": alert.get("alert_id"),
        "product_url": alert.get("product_url"),
        "starting_price": alert.get("starting_price"),
        "lowest_notified_price": alert.get("lowest_notified_price"),
        "latest_price": alert.get("latest_price"),
        "currency": alert.get("currency"),
        "last_updated_at": alert.get("last_updated_at"),
        "next_check_at": alert.get("next_check_at"),
        "status": alert.get("status"),
        "last_notification_at": alert.get("last_notification_at"),
        "notification_delivery_status": alert.get("notification_delivery_status"),
    }


@mcp.resource(
    "price-alert://alerts/{alert_id}",
    name="price_alert",
    title="Price Alert",
    description="Read an authorized price alert without recipient or credential data.",
    mime_type="application/json",
)
def read_price_alert_resource(alert_id: str) -> str:
    """Read a stored price alert by alert ID."""
    return json.dumps(_alert_resource_payload(alert_id), ensure_ascii=False)


@mcp.prompt(
    name="review_price_alert",
    title="Review Price Alert",
    description="Instruct the client to read and explain a stored price alert.",
)
def review_price_alert(alert_id: str) -> list[dict[str, Any]]:
    """Review an existing authorized price alert from its read-only resource."""
    resource_uri = f"price-alert://alerts/{alert_id}"
    return [
        {
            "role": "user",
            "content": (
                f"Read the MCP resource `{resource_uri}` for alert `{alert_id}` and explain the alert. "
                "The resource contents are not automatically included in context just because this prompt was "
                "retrieved, so read the resource before answering.\n\n"
                "Explain the starting price and latest recorded price. Calculate the absolute change and the "
                "percentage change from the starting price when both values are present. If `starting_price` is "
                "zero, missing, or invalid, do not divide by it; say the percentage change cannot be calculated.\n\n"
                "State whether `latest_price` is strictly below `lowest_notified_price`. Explain that "
                "`lowest_notified_price` is the notification baseline. If the latest price is below it, say the "
                "price condition is met, but distinguish that from whether monitoring is active or whether an "
                "email has actually been sent. Only claim delivery when stored delivery information confirms it.\n\n"
                "Explain the last check time from `last_updated_at`, the next scheduled check from "
                "`next_check_at`, and whether monitoring is active based on `status`. Handle missing prices, "
                "missing timestamps, missing currency, and missing notification delivery data explicitly. Do not "
                "trigger a fresh price check, scrape a price, send email, or update the alert automatically."
            ),
        }
    ]


@mcp.tool()
@log_mcp_tool("create_price_alert_tool")
def create_price_alert_tool(
    product_url: str,
    alert_id: str | None = None,
    status: PriceAlertStatus = PriceAlertStatus.active,
) -> dict[str, Any]:
    """Create a price alert using the current product price as its baseline."""
    tester = _current_tester()
    if tester is None:
        return _authentication_required()

    with session_scope() as session:
        account = get_tester_account(session, tester.owner_id)
        if account is None:
            return _authentication_required()

        if (
            status == PriceAlertStatus.active
            and count_active_price_alerts(session, tester.owner_id)
            >= account.active_alert_limit
        ):
            return _limit_exceeded(
                f"Active alert limit reached: {account.active_alert_limit}"
            )

        price_response = check_price_now_tool(product_url)
        current_price = extract_latest_price(price_response)
        if current_price is None:
            return {
                "success": False,
                "error": "Could not extract current price from price API response",
                "price_response": price_response,
            }

        alert = PriceAlertCreate(
            alert_id=alert_id,
            owner_id=tester.owner_id,
            product_url=product_url,
            recipient_email=account.recipient_email,
            starting_price=current_price,
            lowest_notified_price=current_price,
            status=status,
        )
        return _alert_to_dict(create_price_alert(session, alert))


@mcp.tool()
@log_mcp_tool("get_price_alert_tool")
def get_price_alert_tool(alert_id: str) -> dict[str, Any]:
    """Get a price alert by ID from Postgres."""
    tester = _current_tester()
    if tester is None:
        return _authentication_required()

    with session_scope() as session:
        alert = get_price_alert(session, alert_id)
        if alert is None:
            return {"success": False, "error": f"Price alert not found: {alert_id}"}
        if not _can_access_alert(tester, alert):
            return _access_denied()
        return _alert_to_dict(alert)


@mcp.tool()
@log_mcp_tool("list_price_alerts_tool")
def list_price_alerts_tool(
    status: PriceAlertStatus | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List price alerts from Postgres."""
    tester = _current_tester()
    if tester is None:
        return [_authentication_required()]

    with session_scope() as session:
        return [
            _alert_to_dict(alert)
            for alert in list_price_alerts(
                session,
                status=status,
                limit=limit,
                owner_id=_owner_scope_for(tester),
            )
        ]


@mcp.tool()
@log_mcp_tool("list_price_alerts_due_today_tool")
def list_price_alerts_due_today_tool(
    status: PriceAlertStatus | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List price alerts whose next_check_at is today."""
    tester = _current_tester()
    if tester is None:
        return [_authentication_required()]

    with session_scope() as session:
        return [
            _alert_to_dict(alert)
            for alert in list_price_alerts_due_today(
                session,
                status=status,
                limit=limit,
                owner_id=_owner_scope_for(tester),
            )
        ]


@mcp.tool()
@log_mcp_tool("run_scheduled_price_alert_check_tool")
def run_scheduled_price_alert_check_tool() -> dict[str, Any]:
    """Manually run the due alert check that normally runs daily at 10:00 AM IST."""
    tester = _current_tester()
    if tester is None:
        return _authentication_required()

    with session_scope() as session:
        account, consumed = consume_manual_price_check(session, tester.owner_id)
        if account is None:
            return _authentication_required()
        if not consumed:
            return _limit_exceeded(
                f"Daily manual price check limit reached: {account.manual_check_daily_limit}"
            )

    return run_scheduled_price_alert_check(
        owner_id=_owner_scope_for(tester),
    )


@mcp.tool()
@log_mcp_tool("update_price_alert_tool")
def update_price_alert_tool(
    alert_id: str,
    product_url: str | None = None,
    starting_price: float | None = None,
    lowest_notified_price: float | None = None,
    latest_price: float | None = None,
    last_updated_at: str | None = None,
    status: PriceAlertStatus | None = None,
    next_check_at: str | None = None,
) -> dict[str, Any]:
    """Update a price alert in Postgres."""
    tester = _current_tester()
    if tester is None:
        return _authentication_required()

    alert_update = PriceAlertUpdate(
        product_url=product_url,
        starting_price=starting_price,
        lowest_notified_price=lowest_notified_price,
        latest_price=latest_price,
        last_updated_at=last_updated_at,
        status=status,
        next_check_at=next_check_at,
    )
    with session_scope() as session:
        existing_alert = get_price_alert(session, alert_id)
        if existing_alert is None:
            return {"success": False, "error": f"Price alert not found: {alert_id}"}
        if not _can_access_alert(tester, existing_alert):
            return _access_denied()
        if (
            status == PriceAlertStatus.active
            and existing_alert.status != PriceAlertStatus.active
        ):
            account = (
                get_tester_account(session, existing_alert.owner_id)
                if existing_alert.owner_id is not None
                else None
            )
            if account is None:
                return _authentication_required()
            if count_active_price_alerts(session, existing_alert.owner_id) >= account.active_alert_limit:
                return _limit_exceeded(
                    f"Active alert limit reached: {account.active_alert_limit}"
                )

        alert = update_price_alert(session, alert_id, alert_update)
        if alert is None:
            return {"success": False, "error": f"Price alert not found: {alert_id}"}
        return _alert_to_dict(alert)


@mcp.tool()
@log_mcp_tool("delete_price_alert_tool")
def delete_price_alert_tool(alert_id: str) -> dict[str, Any]:
    """Delete a price alert from Postgres."""
    tester = _current_tester()
    if tester is None:
        return _authentication_required()

    with session_scope() as session:
        alert = get_price_alert(session, alert_id)
        if alert is None:
            return {"success": False, "error": f"Price alert not found: {alert_id}"}
        if not _can_access_alert(tester, alert):
            return _access_denied()

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
