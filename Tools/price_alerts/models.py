import re
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo
from uuid import uuid4

from pydantic import field_validator
from sqlalchemy import Column, Date, DateTime
from sqlmodel import Field, Session, SQLModel, select


PRICE_ALERT_TIME_ZONE_NAME = "Asia/Kolkata"
PRICE_ALERT_TIME_ZONE = ZoneInfo(PRICE_ALERT_TIME_ZONE_NAME)
PRICE_ALERT_ADMIN_EMAIL = "orpemanalee@gmail.com"


class PriceAlertRole(str, Enum):
    admin = "admin"
    user = "user"


class PriceAlertStatus(str, Enum):
    active = "active"
    paused = "paused"
    disabled = "disabled"


class TesterAccount(SQLModel, table=True):
    __tablename__ = "tester_accounts"

    owner_id: str = Field(primary_key=True, index=True)
    token_hash: str = Field(index=True, unique=True)
    recipient_email: str = Field(min_length=3, index=True)
    role: PriceAlertRole = Field(default=PriceAlertRole.user, index=True)
    active_alert_limit: int = Field(default=5, ge=0)
    manual_check_daily_limit: int = Field(default=3, ge=0)
    manual_check_count: int = Field(default=0, ge=0)
    manual_check_window_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))

    @field_validator("recipient_email")
    @classmethod
    def validate_recipient_email(cls, value: str) -> str:
        return normalize_email(value)


def _default_alert_id() -> str:
    return f"alert_{uuid4().hex[:12]}"


def _default_audit_id() -> str:
    return f"audit_{uuid4().hex[:12]}"


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("email must be a valid email address")
    return value


def get_price_alert_role(email: str) -> PriceAlertRole:
    return (
        PriceAlertRole.admin
        if normalize_email(email) == PRICE_ALERT_ADMIN_EMAIL
        else PriceAlertRole.user
    )


def is_price_alert_admin(email: str) -> bool:
    return get_price_alert_role(email) == PriceAlertRole.admin


def current_price_alert_datetime() -> datetime:
    return datetime.now(PRICE_ALERT_TIME_ZONE)


def current_price_alert_date() -> date:
    return current_price_alert_datetime().date()


def _default_next_check_at() -> date:
    return current_price_alert_date() + timedelta(days=1)


def _parse_next_check_at(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as error:
            raise ValueError("next_check_at must be a date in YYYY-MM-DD format") from error
    raise TypeError("next_check_at must be a date in YYYY-MM-DD format")


class PriceAlertBase(SQLModel):
    owner_id: str | None = Field(default=None, index=True)
    product_url: str = Field(min_length=1)
    recipient_email: str = Field(min_length=3, index=True)
    starting_price: float = Field(ge=0)
    lowest_notified_price: float = Field(ge=0)
    latest_price: float | None = Field(default=None, ge=0)
    last_updated_at: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    status: PriceAlertStatus = Field(default=PriceAlertStatus.active, index=True)
    next_check_at: date = Field(sa_column=Column(Date, nullable=False))

    @field_validator("product_url")
    @classmethod
    def validate_product_url(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("product_url must start with http:// or https://")
        return value

    @field_validator("recipient_email")
    @classmethod
    def validate_recipient_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("next_check_at", mode="before")
    @classmethod
    def validate_next_check_at(cls, value: Any) -> date:
        return _parse_next_check_at(value)

    @field_validator("last_updated_at", mode="before")
    @classmethod
    def validate_last_updated_at(cls, value: Any) -> date | None:
        if value is None:
            return None
        return _parse_next_check_at(value)


class PriceAlert(PriceAlertBase, table=True):
    __tablename__ = "price_alerts"

    alert_id: str = Field(default_factory=_default_alert_id, primary_key=True, index=True)


class PriceAlertCreate(SQLModel):
    alert_id: str | None = Field(default=None, min_length=1)
    owner_id: str | None = Field(default=None, min_length=1)
    product_url: str = Field(min_length=1)
    recipient_email: str = Field(min_length=3, index=True)
    starting_price: float = Field(ge=0)
    lowest_notified_price: float = Field(ge=0)
    status: PriceAlertStatus = Field(default=PriceAlertStatus.active, index=True)

    @field_validator("product_url")
    @classmethod
    def validate_product_url(cls, value: str) -> str:
        return PriceAlertBase.validate_product_url(value)

    @field_validator("recipient_email")
    @classmethod
    def validate_recipient_email(cls, value: str) -> str:
        return PriceAlertBase.validate_recipient_email(value)


class PriceAlertUpdate(SQLModel):
    owner_id: str | None = Field(default=None, min_length=1)
    product_url: str | None = Field(default=None, min_length=1)
    recipient_email: str | None = Field(default=None, min_length=3)
    starting_price: float | None = Field(default=None, ge=0)
    lowest_notified_price: float | None = Field(default=None, ge=0)
    latest_price: float | None = Field(default=None, ge=0)
    last_updated_at: date | None = None
    status: PriceAlertStatus | None = None
    next_check_at: date | None = None

    @field_validator("product_url")
    @classmethod
    def validate_product_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return PriceAlertBase.validate_product_url(value)

    @field_validator("recipient_email")
    @classmethod
    def validate_recipient_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return PriceAlertBase.validate_recipient_email(value)

    @field_validator("next_check_at", mode="before")
    @classmethod
    def validate_next_check_at(cls, value: Any) -> date | None:
        if value is None:
            return None
        return _parse_next_check_at(value)

    @field_validator("last_updated_at", mode="before")
    @classmethod
    def validate_last_updated_at(cls, value: Any) -> date | None:
        if value is None:
            return None
        return _parse_next_check_at(value)


class PriceAlertRead(PriceAlertBase):
    alert_id: str


class PriceAlertCheckAuditBase(SQLModel):
    alert_id: str = Field(min_length=1, index=True)
    product_url: str = Field(min_length=1)
    checked_at: datetime = Field(
        default_factory=current_price_alert_datetime,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    checked_on: date = Field(
        default_factory=current_price_alert_date,
        sa_column=Column(Date, nullable=False, index=True),
    )
    price: float | None = Field(default=None, ge=0)
    success: bool = Field(default=False, index=True)
    error: str | None = Field(default=None)

    @field_validator("product_url")
    @classmethod
    def validate_product_url(cls, value: str) -> str:
        return PriceAlertBase.validate_product_url(value)


class PriceAlertCheckAudit(PriceAlertCheckAuditBase, table=True):
    __tablename__ = "price_alert_check_audit"

    audit_id: str = Field(default_factory=_default_audit_id, primary_key=True, index=True)


class PriceAlertCheckAuditCreate(PriceAlertCheckAuditBase):
    pass


class PriceAlertCheckAuditRead(PriceAlertCheckAuditBase):
    audit_id: str


def create_price_alert(session: Session, alert: PriceAlertCreate) -> PriceAlert:
    db_alert = PriceAlert(
        alert_id=alert.alert_id or _default_alert_id(),
        owner_id=alert.owner_id,
        product_url=alert.product_url,
        recipient_email=alert.recipient_email,
        starting_price=alert.starting_price,
        lowest_notified_price=alert.lowest_notified_price,
        status=alert.status,
        next_check_at=_default_next_check_at(),
    )
    session.add(db_alert)
    session.commit()
    session.refresh(db_alert)
    return db_alert


def create_price_alert_check_audit(
    session: Session,
    audit: PriceAlertCheckAuditCreate,
) -> PriceAlertCheckAudit:
    db_audit = PriceAlertCheckAudit(**audit.model_dump())
    session.add(db_audit)
    session.commit()
    session.refresh(db_audit)
    return db_audit


def get_price_alert(session: Session, alert_id: str) -> PriceAlert | None:
    return session.get(PriceAlert, alert_id)


def get_tester_account(session: Session, owner_id: str) -> TesterAccount | None:
    return session.get(TesterAccount, owner_id)


def get_tester_account_by_token_hash(
    session: Session,
    token_hash: str,
) -> TesterAccount | None:
    statement = select(TesterAccount).where(TesterAccount.token_hash == token_hash)
    return session.exec(statement).first()


def upsert_tester_account(session: Session, account: TesterAccount) -> TesterAccount:
    account.recipient_email = normalize_email(account.recipient_email)
    existing = session.get(TesterAccount, account.owner_id)
    if existing is None:
        session.add(account)
        session.commit()
        session.refresh(account)
        return account

    existing.token_hash = account.token_hash
    existing.recipient_email = account.recipient_email
    existing.role = account.role
    existing.active_alert_limit = account.active_alert_limit
    existing.manual_check_daily_limit = account.manual_check_daily_limit
    session.add(existing)
    session.commit()
    session.refresh(existing)
    return existing


def count_active_price_alerts(
    session: Session,
    owner_id: str | None = None,
) -> int:
    statement = select(PriceAlert).where(PriceAlert.status == PriceAlertStatus.active)
    if owner_id is not None:
        statement = statement.where(PriceAlert.owner_id == owner_id)
    return len(list(session.exec(statement)))


def consume_manual_price_check(
    session: Session,
    owner_id: str,
) -> tuple[TesterAccount | None, bool]:
    account = session.get(TesterAccount, owner_id)
    if account is None:
        return None, False

    today = current_price_alert_date()
    if account.manual_check_window_date != today:
        account.manual_check_window_date = today
        account.manual_check_count = 0

    if account.manual_check_count >= account.manual_check_daily_limit:
        return account, False

    account.manual_check_count += 1
    session.add(account)
    session.commit()
    session.refresh(account)
    return account, True


def list_price_alerts(
    session: Session,
    status: PriceAlertStatus | None = None,
    limit: int | None = 100,
    recipient_email: str | None = None,
    owner_id: str | None = None,
) -> list[PriceAlert]:
    statement = select(PriceAlert)
    if status is not None:
        statement = statement.where(PriceAlert.status == status)
    if recipient_email is not None:
        statement = statement.where(PriceAlert.recipient_email == normalize_email(recipient_email))
    if owner_id is not None:
        statement = statement.where(PriceAlert.owner_id == owner_id)
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement))


def list_price_alerts_due_today(
    session: Session,
    status: PriceAlertStatus | None = None,
    limit: int | None = 100,
    due_date: date | None = None,
    recipient_email: str | None = None,
    owner_id: str | None = None,
) -> list[PriceAlert]:
    due_date = due_date or current_price_alert_date()
    statement = select(PriceAlert).where(PriceAlert.next_check_at == due_date)
    if status is not None:
        statement = statement.where(PriceAlert.status == status)
    if recipient_email is not None:
        statement = statement.where(PriceAlert.recipient_email == normalize_email(recipient_email))
    if owner_id is not None:
        statement = statement.where(PriceAlert.owner_id == owner_id)
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement))


def update_price_alert(
    session: Session,
    alert_id: str,
    alert_update: PriceAlertUpdate,
) -> PriceAlert | None:
    db_alert = session.get(PriceAlert, alert_id)
    if db_alert is None:
        return None

    update_data = alert_update.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in update_data.items():
        setattr(db_alert, key, value)

    session.add(db_alert)
    session.commit()
    session.refresh(db_alert)
    return db_alert


def delete_price_alert(session: Session, alert_id: str) -> bool:
    db_alert = session.get(PriceAlert, alert_id)
    if db_alert is None:
        return False

    session.delete(db_alert)
    session.commit()
    return True
