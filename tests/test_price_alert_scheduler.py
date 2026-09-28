import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from Tools.price_alerts.models import (
    PRICE_ALERT_TIME_ZONE,
    PriceAlert,
    PriceAlertCheckAudit,
    PriceAlertStatus,
    current_price_alert_date,
)
from Tools.price_alerts.scheduler import (
    run_scheduled_price_alert_check,
    seconds_until_next_price_alert_run,
)


class PriceAlertSchedulerTests(unittest.TestCase):
    def test_seconds_until_next_run_uses_10am_ist(self):
        now = datetime(2026, 9, 28, 9, 30, tzinfo=PRICE_ALERT_TIME_ZONE)

        self.assertEqual(seconds_until_next_price_alert_run(now), 30 * 60)

    def test_seconds_until_next_run_converts_aware_datetime_to_ist(self):
        now = datetime(2026, 9, 28, 4, 0, tzinfo=timezone.utc)

        self.assertEqual(seconds_until_next_price_alert_run(now), 30 * 60)

    def test_scheduled_check_records_audit_price_for_due_alert(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)
        today = current_price_alert_date()

        with Session(engine) as session:
            session.add(
                PriceAlert(
                    alert_id="alert_audit",
                    product_url="https://example.com/product",
                    recipient_email="buyer@example.com",
                    starting_price=100.0,
                    lowest_notified_price=100.0,
                    status=PriceAlertStatus.active,
                    next_check_at=today,
                )
            )
            session.commit()

        @contextmanager
        def test_session_scope():
            with Session(engine) as session:
                yield session

        with (
            patch(
                "Tools.price_alerts.scheduler.session_scope",
                test_session_scope,
            ),
            patch(
                "Tools.price_alerts.scheduler.check_price_now",
                return_value={"latest_price": "99.50"},
            ),
            patch("Tools.price_alerts.scheduler.send_email"),
        ):
            summary = run_scheduled_price_alert_check()

        with Session(engine) as session:
            audits = list(session.exec(select(PriceAlertCheckAudit)))
            alert = session.get(PriceAlert, "alert_audit")

        self.assertEqual(summary["checked"], 1)
        self.assertEqual(summary["audited"], 1)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].alert_id, "alert_audit")
        self.assertEqual(audits[0].checked_on, today)
        self.assertEqual(audits[0].price, 99.5)
        self.assertTrue(audits[0].success)
        self.assertEqual(alert.latest_price, 99.5)
        self.assertEqual(alert.lowest_notified_price, 99.5)
        self.assertEqual(alert.next_check_at, today + timedelta(days=1))
        engine.dispose()

    def test_scheduled_check_can_be_scoped_to_one_recipient(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)
        today = current_price_alert_date()

        with Session(engine) as session:
            session.add(
                PriceAlert(
                    alert_id="alert_owner",
                    product_url="https://example.com/owner",
                    recipient_email="owner@example.com",
                    starting_price=100.0,
                    lowest_notified_price=90.0,
                    status=PriceAlertStatus.active,
                    next_check_at=today,
                )
            )
            session.add(
                PriceAlert(
                    alert_id="alert_other",
                    product_url="https://example.com/other",
                    recipient_email="other@example.com",
                    starting_price=100.0,
                    lowest_notified_price=90.0,
                    status=PriceAlertStatus.active,
                    next_check_at=today,
                )
            )
            session.commit()

        @contextmanager
        def test_session_scope():
            with Session(engine) as session:
                yield session

        with (
            patch(
                "Tools.price_alerts.scheduler.session_scope",
                test_session_scope,
            ),
            patch(
                "Tools.price_alerts.scheduler.check_price_now",
                return_value={"latest_price": 95.0},
            ),
        ):
            summary = run_scheduled_price_alert_check(
                recipient_email="owner@example.com",
            )

        with Session(engine) as session:
            audits = list(session.exec(select(PriceAlertCheckAudit)))
            other_alert = session.get(PriceAlert, "alert_other")

        self.assertEqual(summary["checked"], 1)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].alert_id, "alert_owner")
        self.assertIsNone(other_alert.latest_price)
        self.assertEqual(other_alert.next_check_at, today)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
