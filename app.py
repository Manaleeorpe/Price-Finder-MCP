import asyncio
import os

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlmodel import Session

from Tools.json_logging import log_api_request
from Tools.price_alerts import (
    PriceAlertCreate,
    PriceAlertRead,
    PriceAlertStatus,
    PriceAlertUpdate,
    create_db_and_tables,
    create_price_alert,
    delete_price_alert,
    get_price_alert,
    get_session,
    is_price_alert_admin,
    is_database_configured,
    list_price_alerts,
    list_price_alerts_due_today,
    normalize_email,
    run_daily_price_alert_scheduler,
    run_scheduled_price_alert_check,
    update_price_alert,
)


app = FastAPI(
    title="Price Alert API",
    description="APIs for price alert creation, lookup, and scheduling.",
    version="1.0.0",
)


_price_alert_scheduler_task: asyncio.Task | None = None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@app.middleware("http")
async def json_logging_middleware(request, call_next):
    return await log_api_request(request, call_next)


@app.on_event("startup")
async def on_startup():
    global _price_alert_scheduler_task

    if is_database_configured():
        create_db_and_tables()
        if (
            _env_bool("PRICE_ALERT_SCHEDULER_ENABLED", True)
            and (_price_alert_scheduler_task is None or _price_alert_scheduler_task.done())
        ):
            _price_alert_scheduler_task = asyncio.create_task(
                run_daily_price_alert_scheduler()
            )


@app.on_event("shutdown")
async def on_shutdown():
    global _price_alert_scheduler_task

    if _price_alert_scheduler_task is None:
        return

    _price_alert_scheduler_task.cancel()
    try:
        await _price_alert_scheduler_task
    except asyncio.CancelledError:
        pass
    finally:
        _price_alert_scheduler_task = None


def _handle_missing_alert(alert_id: str):
    raise HTTPException(status_code=404, detail=f"Price alert not found: {alert_id}")


def _forbidden():
    raise HTTPException(status_code=403, detail="Not authorized for this price alert")


def _normalize_email_for_request(value: str) -> str:
    try:
        return normalize_email(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _recipient_scope_for(requester_email: str) -> str | None:
    requester_email = _normalize_email_for_request(requester_email)
    return None if is_price_alert_admin(requester_email) else requester_email


def _authorize_recipient(requester_email: str, recipient_email: str) -> None:
    requester_email = _normalize_email_for_request(requester_email)
    recipient_email = _normalize_email_for_request(recipient_email)
    if not is_price_alert_admin(requester_email) and requester_email != recipient_email:
        _forbidden()


def _authorize_alert(requester_email: str, alert) -> None:
    requester_email = _normalize_email_for_request(requester_email)
    if is_price_alert_admin(requester_email):
        return
    if alert.recipient_email != requester_email:
        _forbidden()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/price-alerts", response_model=PriceAlertRead, status_code=201)
def api_create_price_alert(
    request: PriceAlertCreate,
    requester_email: str = Query(..., min_length=3),
    session: Session = Depends(get_session),
):
    _authorize_recipient(requester_email, request.recipient_email)
    return create_price_alert(session, request)


@app.get("/price-alerts", response_model=list[PriceAlertRead])
def api_list_price_alerts(
    requester_email: str = Query(..., min_length=3),
    status: PriceAlertStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
):
    return list_price_alerts(
        session,
        status=status,
        limit=limit,
        recipient_email=_recipient_scope_for(requester_email),
    )


@app.get("/price-alerts/due-today", response_model=list[PriceAlertRead])
def api_list_price_alerts_due_today(
    requester_email: str = Query(..., min_length=3),
    status: PriceAlertStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
):
    return list_price_alerts_due_today(
        session,
        status=status,
        limit=limit,
        recipient_email=_recipient_scope_for(requester_email),
    )


@app.post("/price-alerts/run-scheduled-check")
def api_run_scheduled_price_alert_check(
    requester_email: str = Query(..., min_length=3),
):
    return run_scheduled_price_alert_check(
        recipient_email=_recipient_scope_for(requester_email),
    )


@app.get("/price-alerts/{alert_id}", response_model=PriceAlertRead)
def api_get_price_alert(
    alert_id: str,
    requester_email: str = Query(..., min_length=3),
    session: Session = Depends(get_session),
):
    alert = get_price_alert(session, alert_id)
    if alert is None:
        _handle_missing_alert(alert_id)
    _authorize_alert(requester_email, alert)
    return alert


@app.patch("/price-alerts/{alert_id}", response_model=PriceAlertRead)
def api_update_price_alert(
    alert_id: str,
    request: PriceAlertUpdate,
    requester_email: str = Query(..., min_length=3),
    session: Session = Depends(get_session),
):
    existing_alert = get_price_alert(session, alert_id)
    if existing_alert is None:
        _handle_missing_alert(alert_id)
    _authorize_alert(requester_email, existing_alert)
    if request.recipient_email is not None:
        _authorize_recipient(requester_email, request.recipient_email)

    alert = update_price_alert(session, alert_id, request)
    if alert is None:
        _handle_missing_alert(alert_id)
    return alert


@app.delete("/price-alerts/{alert_id}")
def api_delete_price_alert(
    alert_id: str,
    requester_email: str = Query(..., min_length=3),
    session: Session = Depends(get_session),
):
    alert = get_price_alert(session, alert_id)
    if alert is None:
        _handle_missing_alert(alert_id)
    _authorize_alert(requester_email, alert)

    deleted = delete_price_alert(session, alert_id)
    if not deleted:
        _handle_missing_alert(alert_id)
    return {"deleted": True, "alert_id": alert_id}
