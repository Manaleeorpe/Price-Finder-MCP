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
    is_database_configured,
    list_price_alerts,
    list_price_alerts_due_today,
    run_daily_price_alert_scheduler,
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/price-alerts", response_model=PriceAlertRead, status_code=201)
def api_create_price_alert(
    request: PriceAlertCreate,
    session: Session = Depends(get_session),
):
    return create_price_alert(session, request)


@app.get("/price-alerts", response_model=list[PriceAlertRead])
def api_list_price_alerts(
    status: PriceAlertStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
):
    return list_price_alerts(session, status=status, limit=limit)


@app.get("/price-alerts/due-today", response_model=list[PriceAlertRead])
def api_list_price_alerts_due_today(
    status: PriceAlertStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
):
    return list_price_alerts_due_today(session, status=status, limit=limit)


@app.get("/price-alerts/{alert_id}", response_model=PriceAlertRead)
def api_get_price_alert(
    alert_id: str,
    session: Session = Depends(get_session),
):
    alert = get_price_alert(session, alert_id)
    if alert is None:
        _handle_missing_alert(alert_id)
    return alert


@app.patch("/price-alerts/{alert_id}", response_model=PriceAlertRead)
def api_update_price_alert(
    alert_id: str,
    request: PriceAlertUpdate,
    session: Session = Depends(get_session),
):
    alert = update_price_alert(session, alert_id, request)
    if alert is None:
        _handle_missing_alert(alert_id)
    return alert


@app.delete("/price-alerts/{alert_id}")
def api_delete_price_alert(
    alert_id: str,
    session: Session = Depends(get_session),
):
    deleted = delete_price_alert(session, alert_id)
    if not deleted:
        _handle_missing_alert(alert_id)
    return {"deleted": True, "alert_id": alert_id}
