import unittest
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from Tools.price_alerts.auth import load_tester_configs, owner_id_from_token, token_hash
from Tools.price_alerts.models import (
    PRICE_ALERT_ADMIN_EMAIL,
    PriceAlert,
    PriceAlertRole,
    PriceAlertStatus,
    TesterAccount,
    current_price_alert_date,
    get_price_alert_role,
    is_price_alert_admin,
    list_price_alerts,
    upsert_tester_account,
)


class PriceAlertAccessTests(unittest.TestCase):
    def test_admin_email_has_admin_role(self):
        self.assertEqual(
            get_price_alert_role(PRICE_ALERT_ADMIN_EMAIL.upper()),
            PriceAlertRole.admin,
        )
        self.assertTrue(is_price_alert_admin(PRICE_ALERT_ADMIN_EMAIL))
        self.assertFalse(is_price_alert_admin("buyer@example.com"))

    def test_tester_config_derives_owner_id_from_token(self):
        token = "tester-token"
        with patch.dict(
            "os.environ",
            {
                "TESTER_ACCOUNTS_JSON": (
                    '[{"token":"tester-token","recipient_email":"Buyer@Example.com",'
                    '"active_alert_limit":2,"manual_check_daily_limit":1}]'
                )
            },
            clear=False,
        ):
            configs = load_tester_configs()

        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].owner_id, owner_id_from_token(token))
        self.assertEqual(configs[0].token_hash, token_hash(token))
        self.assertEqual(configs[0].recipient_email, "buyer@example.com")

    def test_list_price_alerts_can_be_scoped_to_owner(self):
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
                    owner_id="owner_123",
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
                    owner_id="owner_456",
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
                owner_id="owner_123",
            )
            all_alerts = list_price_alerts(session, owner_id=None)

        engine.dispose()

        self.assertEqual([alert.alert_id for alert in scoped_alerts], ["alert_owner"])
        self.assertEqual(len(all_alerts), 2)

    def test_upsert_tester_account_stores_verified_recipient_and_limits(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            account = upsert_tester_account(
                session,
                TesterAccount(
                    owner_id="owner_123",
                    token_hash="hash_123",
                    recipient_email="Buyer@Example.com",
                    active_alert_limit=2,
                    manual_check_daily_limit=1,
                ),
            )

        engine.dispose()

        self.assertEqual(account.recipient_email, "buyer@example.com")
        self.assertEqual(account.active_alert_limit, 2)
        self.assertEqual(account.manual_check_daily_limit, 1)


if __name__ == "__main__":
    unittest.main()
