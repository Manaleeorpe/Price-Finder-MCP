import asyncio
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlmodel import Session

from Tools.json_logging import log_api_request
from Tools.price_alerts import (
    PriceAlertCreate,
    PriceAlertRole,
    PriceAlertRead,
    PriceAlertStatus,
    PriceAlertUpdate,
    consume_manual_price_check,
    count_active_price_alerts,
    create_db_and_tables,
    create_price_alert,
    delete_price_alert,
    get_price_alert,
    get_session,
    get_tester_account_by_token_hash,
    is_database_configured,
    list_price_alerts,
    list_price_alerts_due_today,
    run_daily_price_alert_scheduler,
    run_scheduled_price_alert_check,
    update_price_alert,
)
from Tools.price_alerts.auth import token_hash


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


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token required")
    return token


def get_current_tester_account(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    account = get_tester_account_by_token_hash(session, token_hash(_bearer_token(authorization)))
    if account is None:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return account


def _owner_scope_for(account) -> str | None:
    return None if account.role == PriceAlertRole.admin else account.owner_id


def _authorize_alert(account, alert) -> None:
    if account.role == PriceAlertRole.admin:
        return
    if alert.owner_id != account.owner_id:
        _forbidden()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/price-alerts", response_model=PriceAlertRead, status_code=201)
def api_create_price_alert(
    request: PriceAlertCreate,
    account=Depends(get_current_tester_account),
    session: Session = Depends(get_session),
):
    if (
        request.status == PriceAlertStatus.active
        and count_active_price_alerts(session, account.owner_id)
        >= account.active_alert_limit
    ):
        raise HTTPException(
            status_code=429,
            detail=f"Active alert limit reached: {account.active_alert_limit}",
        )
    return create_price_alert(
        session,
        PriceAlertCreate(
            alert_id=request.alert_id,
            owner_id=account.owner_id,
            product_url=request.product_url,
            recipient_email=account.recipient_email,
            starting_price=request.starting_price,
            lowest_notified_price=request.lowest_notified_price,
            status=request.status,
        ),
    )


@app.get("/price-alerts", response_model=list[PriceAlertRead])
def api_list_price_alerts(
    status: PriceAlertStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    account=Depends(get_current_tester_account),
    session: Session = Depends(get_session),
):
    return list_price_alerts(
        session,
        status=status,
        limit=limit,
        owner_id=_owner_scope_for(account),
    )


@app.get("/price-alerts/due-today", response_model=list[PriceAlertRead])
def api_list_price_alerts_due_today(
    status: PriceAlertStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    account=Depends(get_current_tester_account),
    session: Session = Depends(get_session),
):
    return list_price_alerts_due_today(
        session,
        status=status,
        limit=limit,
        owner_id=_owner_scope_for(account),
    )


@app.post("/price-alerts/run-scheduled-check")
def api_run_scheduled_price_alert_check(
    account=Depends(get_current_tester_account),
    session: Session = Depends(get_session),
):
    account, consumed = consume_manual_price_check(session, account.owner_id)
    if account is None:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    if not consumed:
        raise HTTPException(
            status_code=429,
            detail=f"Daily manual price check limit reached: {account.manual_check_daily_limit}",
        )
    return run_scheduled_price_alert_check(
        owner_id=_owner_scope_for(account),
    )


@app.get("/price-alerts/{alert_id}", response_model=PriceAlertRead)
def api_get_price_alert(
    alert_id: str,
    account=Depends(get_current_tester_account),
    session: Session = Depends(get_session),
):
    alert = get_price_alert(session, alert_id)
    if alert is None:
        _handle_missing_alert(alert_id)
    _authorize_alert(account, alert)
    return alert


@app.patch("/price-alerts/{alert_id}", response_model=PriceAlertRead)
def api_update_price_alert(
    alert_id: str,
    request: PriceAlertUpdate,
    account=Depends(get_current_tester_account),
    session: Session = Depends(get_session),
):
    existing_alert = get_price_alert(session, alert_id)
    if existing_alert is None:
        _handle_missing_alert(alert_id)
    _authorize_alert(account, existing_alert)
    if (
        request.status == PriceAlertStatus.active
        and existing_alert.status != PriceAlertStatus.active
        and existing_alert.owner_id is not None
        and count_active_price_alerts(session, existing_alert.owner_id)
        >= account.active_alert_limit
    ):
        raise HTTPException(
            status_code=429,
            detail=f"Active alert limit reached: {account.active_alert_limit}",
        )

    alert = update_price_alert(
        session,
        alert_id,
        PriceAlertUpdate(
            product_url=request.product_url,
            starting_price=request.starting_price,
            lowest_notified_price=request.lowest_notified_price,
            latest_price=request.latest_price,
            last_updated_at=request.last_updated_at,
            status=request.status,
            next_check_at=request.next_check_at,
        ),
    )
    if alert is None:
        _handle_missing_alert(alert_id)
    return alert


@app.delete("/price-alerts/{alert_id}")
def api_delete_price_alert(
    alert_id: str,
    account=Depends(get_current_tester_account),
    session: Session = Depends(get_session),
):
    alert = get_price_alert(session, alert_id)
    if alert is None:
        _handle_missing_alert(alert_id)
    _authorize_alert(account, alert)

    deleted = delete_price_alert(session, alert_id)
    if not deleted:
        _handle_missing_alert(alert_id)
    return {"deleted": True, "alert_id": alert_id}
