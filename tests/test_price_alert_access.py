import unittest

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from Tools.price_alerts.models import (
    PRICE_ALERT_ADMIN_EMAIL,
    PriceAlert,
    PriceAlertStatus,
    current_price_alert_date,
    is_price_alert_admin,
    list_price_alerts,
)


class PriceAlertAccessTests(unittest.TestCase):
    def test_admin_email_is_admin(self):
        self.assertTrue(is_price_alert_admin(PRICE_ALERT_ADMIN_EMAIL.upper()))
        self.assertFalse(is_price_alert_admin("buyer@example.com"))

    def test_list_price_alerts_can_be_scoped_to_recipient(self):
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

            scoped_alerts = list_price_alerts(
                session,
                recipient_email="Owner@Example.com",
            )
            all_alerts = list_price_alerts(session, recipient_email=None)

        engine.dispose()

        self.assertEqual([alert.alert_id for alert in scoped_alerts], ["alert_owner"])
        self.assertEqual(len(all_alerts), 2)


if __name__ == "__main__":
    unittest.main()
