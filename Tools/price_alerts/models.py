import re
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import field_validator
from sqlalchemy import Column, Date
from sqlmodel import Field, Session, SQLModel, select


class PriceAlertStatus(str, Enum):
    active = "active"
    paused = "paused"
    disabled = "disabled"


def _default_alert_id() -> str:
    return f"alert_{uuid4().hex[:12]}"


def _default_next_check_at() -> date:
    return date.today() + timedelta(days=1)


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
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("recipient_email must be a valid email address")
        return value

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


def create_price_alert(session: Session, alert: PriceAlertCreate) -> PriceAlert:
    db_alert = PriceAlert(
        alert_id=alert.alert_id or _default_alert_id(),
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


def get_price_alert(session: Session, alert_id: str) -> PriceAlert | None:
    return session.get(PriceAlert, alert_id)


def list_price_alerts(
    session: Session,
    status: PriceAlertStatus | None = None,
    limit: int | None = 100,
) -> list[PriceAlert]:
    statement = select(PriceAlert)
    if status is not None:
        statement = statement.where(PriceAlert.status == status)
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement))


def list_price_alerts_due_today(
    session: Session,
    status: PriceAlertStatus | None = None,
    limit: int | None = 100,
) -> list[PriceAlert]:
    statement = select(PriceAlert).where(PriceAlert.next_check_at == date.today())
    if status is not None:
        statement = statement.where(PriceAlert.status == status)
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
