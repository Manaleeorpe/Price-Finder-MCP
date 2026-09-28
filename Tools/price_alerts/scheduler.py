import asyncio
import re
from datetime import datetime, time, timedelta
from typing import Any

from Tools.json_logging import log_json
from Tools.price import check_price_now
from Tools.price_alerts.database import session_scope
from Tools.price_alerts.models import (
    PRICE_ALERT_TIME_ZONE,
    PRICE_ALERT_TIME_ZONE_NAME,
    PriceAlertCheckAuditCreate,
    PriceAlertUpdate,
    create_price_alert_check_audit,
    current_price_alert_datetime,
    list_price_alerts_due_today,
    update_price_alert,
)
from Tools.price_alerts.sendMail import send_email


CHECK_HOUR = 10
CHECK_MINUTE = 0
PRICE_KEYS = (
    "latest_price",
    "current_price",
    "price",
    "amount",
    "sale_price",
    "deal_price",
    "value",
)


def _as_price_alert_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=PRICE_ALERT_TIME_ZONE)
    return value.astimezone(PRICE_ALERT_TIME_ZONE)


def seconds_until_next_price_alert_run(now: datetime | None = None) -> float:
    now = _as_price_alert_timezone(now or current_price_alert_datetime())
    next_run = datetime.combine(
        now.date(),
        time(hour=CHECK_HOUR, minute=CHECK_MINUTE),
        tzinfo=PRICE_ALERT_TIME_ZONE,
    )
    if now >= next_run:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


def _coerce_price(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        price = float(value)
        return price if price >= 0 else None
    if isinstance(value, str):
        match = re.search(r"\d+(?:,\d{2,3})*(?:\.\d+)?|\d+(?:\.\d+)?", value)
        if not match:
            return None
        price = float(match.group(0).replace(",", ""))
        return price if price >= 0 else None
    return None


def extract_latest_price(payload: Any) -> float | None:
    if isinstance(payload, list):
        for item in payload:
            price = extract_latest_price(item)
            if price is not None:
                return price
        return None

    if not isinstance(payload, dict):
        return _coerce_price(payload)

    normalized_payload = {str(key).lower(): value for key, value in payload.items()}
    for key in PRICE_KEYS:
        price = _coerce_price(normalized_payload.get(key))
        if price is not None:
            return price

    for value in payload.values():
        if isinstance(value, dict):
            price = extract_latest_price(value)
            if price is not None:
                return price

    return None


def _price_drop_email_body(product_url: str, old_price: float, new_price: float) -> str:
    return (
        "Hi,\n\n"
        "Good news! The price for one of your tracked products has dropped.\n\n"
        f"Product URL: {product_url}\n"
        f"Previous lowest notified price: {old_price}\n"
        f"Current price: {new_price}\n\n"
        "Regards,\n"
        "Price Finder"
    )


def _price_check_error(price_response: Any) -> str | None:
    if isinstance(price_response, dict):
        error = price_response.get("error")
        if error:
            return str(error)
        if price_response.get("success") is False:
            return "Price API response did not include a successful result"
    return None


def run_scheduled_price_alert_check(
    recipient_email: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    checked_at = current_price_alert_datetime()
    today = checked_at.date()
    tomorrow = today + timedelta(days=1)
    summary: dict[str, Any] = {
        "checked": 0,
        "audited": 0,
        "updated": 0,
        "emails_sent": 0,
        "emails_failed": 0,
        "failed": 0,
        "failures": [],
    }

    with session_scope() as session:
        alerts = list_price_alerts_due_today(
            session,
            limit=None,
            due_date=today,
            recipient_email=recipient_email,
            owner_id=owner_id,
        )

        for alert in alerts:
            summary["checked"] += 1
            alert_checked_at = current_price_alert_datetime()
            try:
                price_response = check_price_now(alert.product_url)
            except Exception as error:
                price_response = {
                    "success": False,
                    "error": f"{error.__class__.__name__}: {error}",
                }
            latest_price = extract_latest_price(price_response)
            audit_error = _price_check_error(price_response)
            if latest_price is None and audit_error is None:
                audit_error = "Could not extract latest price from price API response"
            try:
                create_price_alert_check_audit(
                    session,
                    PriceAlertCheckAuditCreate(
                        alert_id=alert.alert_id,
                        product_url=alert.product_url,
                        checked_at=alert_checked_at,
                        checked_on=alert_checked_at.date(),
                        price=latest_price,
                        success=latest_price is not None,
                        error=audit_error,
                    ),
                )
            except Exception as error:
                session.rollback()
                summary["failed"] += 1
                summary["failures"].append(
                    {
                        "alert_id": alert.alert_id,
                        "error": f"Could not write price check audit: {error}",
                    }
                )
            else:
                summary["audited"] += 1

            lowest_notified_price = None
            email_failure = None

            if latest_price is not None and latest_price < alert.lowest_notified_price:
                try:
                    send_email(
                        recipient=alert.recipient_email,
                        subject="Price drop alert",
                        body=_price_drop_email_body(
                            alert.product_url,
                            alert.lowest_notified_price,
                            latest_price,
                        ),
                    )
                except Exception as error:
                    email_failure = {
                        "alert_id": alert.alert_id,
                        "error": f"Could not send price drop email: {error}",
                    }
                    summary["emails_failed"] += 1
                else:
                    lowest_notified_price = latest_price
                    summary["emails_sent"] += 1

            update = PriceAlertUpdate(
                latest_price=latest_price,
                lowest_notified_price=lowest_notified_price,
                last_updated_at=today,
                next_check_at=tomorrow,
            )
            updated_alert = update_price_alert(session, alert.alert_id, update)
            if updated_alert is None:
                summary["failed"] += 1
                summary["failures"].append(
                    {
                        "alert_id": alert.alert_id,
                        "error": "Price alert was not found during update",
                    }
                )
                continue

            if email_failure is not None:
                summary["failed"] += 1
                summary["failures"].append(email_failure)
                continue

            if latest_price is None:
                summary["failed"] += 1
                summary["failures"].append(
                    {
                        "alert_id": alert.alert_id,
                        "error": "Could not extract latest price from price API response",
                        "response": price_response,
                    }
                )
                continue

            summary["updated"] += 1

    log_json("price_alerts.scheduled_check.completed", **summary)
    return summary


async def run_daily_price_alert_scheduler() -> None:
    while True:
        delay_seconds = seconds_until_next_price_alert_run()
        log_json(
            "price_alerts.scheduler.waiting",
            delay_seconds=round(delay_seconds, 2),
            check_hour=CHECK_HOUR,
            check_minute=CHECK_MINUTE,
            check_timezone=PRICE_ALERT_TIME_ZONE_NAME,
        )
        await asyncio.sleep(delay_seconds)
        try:
            await asyncio.to_thread(run_scheduled_price_alert_check)
        except Exception as error:
            log_json(
                "price_alerts.scheduled_check.failed",
                error={"type": error.__class__.__name__, "message": str(error)},
            )
