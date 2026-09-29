import json
import unittest
from unittest.mock import patch

from server import server


class PriceAlertMCPResourcePromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_resource_template_is_discoverable(self):
        templates = await server.mcp.list_resource_templates()

        self.assertTrue(
            any(
                template.uri_template
                == "price-alert://users/{requester_email}/alerts/{alert_id}"
                and template.mime_type == "application/json"
                for template in templates
            )
        )

    async def test_prompt_is_discoverable_with_required_alert_id(self):
        prompts = await server.mcp.list_prompts()
        prompt = next(prompt for prompt in prompts if prompt.name == "review_price_alert")

        self.assertEqual(prompt.name, "review_price_alert")
        self.assertEqual(prompt.arguments[0].name, "requester_email")
        self.assertTrue(prompt.arguments[0].required)
        self.assertEqual(prompt.arguments[1].name, "alert_id")
        self.assertTrue(prompt.arguments[1].required)

    async def test_manual_scheduled_check_tool_is_discoverable(self):
        tools = await server.mcp.list_tools()

        self.assertTrue(
            any(tool.name == "run_scheduled_price_alert_check_tool" for tool in tools)
        )

    async def test_create_price_alert_tool_accepts_recipient_and_requester_email(self):
        tools = await server.mcp.list_tools()
        tool = next(tool for tool in tools if tool.name == "create_price_alert_tool")

        properties = tool.input_schema["properties"]
        self.assertIn("product_url", properties)
        self.assertIn("recipient_email", properties)
        self.assertIn("requester_email", properties)

    async def test_manual_scheduled_check_tool_runs_scheduler_boundary_for_admin(self):
        summary = {
            "checked": 1,
            "audited": 1,
            "updated": 1,
            "emails_sent": 0,
            "emails_failed": 0,
            "failed": 0,
            "failures": [],
        }

        with patch.object(
            server,
            "run_scheduled_price_alert_check",
            return_value=summary,
        ) as run_check:
            result = server.run_scheduled_price_alert_check_tool(
                "orpemanalee@gmail.com",
            )

        self.assertEqual(result, summary)
        run_check.assert_called_once_with(recipient_email=None)

    async def test_manual_scheduled_check_tool_scopes_non_admin_user(self):
        summary = {
            "checked": 1,
            "audited": 1,
            "updated": 1,
            "emails_sent": 0,
            "emails_failed": 0,
            "failed": 0,
            "failures": [],
        }

        with patch.object(
            server,
            "run_scheduled_price_alert_check",
            return_value=summary,
        ) as run_check:
            result = server.run_scheduled_price_alert_check_tool(
                "Buyer@Example.com",
            )

        self.assertEqual(result, summary)
        run_check.assert_called_once_with(recipient_email="buyer@example.com")

    async def test_resource_read_returns_sanitized_alert_json(self):
        alert = {
            "alert_id": "alert_123",
            "product_url": "https://example.com/product",
            "recipient_email": "secret@example.com",
            "starting_price": 100.0,
            "lowest_notified_price": 90.0,
            "latest_price": 95.0,
            "last_updated_at": "2026-09-27",
            "next_check_at": "2026-09-28",
            "status": "active",
        }

        with patch.object(server, "get_price_alert_tool", return_value=alert):
            contents = await server.mcp.read_resource(
                "price-alert://users/secret@example.com/alerts/alert_123"
            )

        payload = json.loads(contents[0].content)
        self.assertEqual(contents[0].mime_type, "application/json")
        self.assertEqual(payload["alert_id"], "alert_123")
        self.assertEqual(payload["product_url"], "https://example.com/product")
        self.assertEqual(payload["currency"], None)
        self.assertEqual(payload["last_notification_at"], None)
        self.assertEqual(payload["notification_delivery_status"], None)
        self.assertNotIn("recipient_email", payload)

    async def test_resource_read_preserves_missing_alert_pattern(self):
        missing = {"success": False, "error": "Price alert not found: alert_missing"}

        with patch.object(server, "get_price_alert_tool", return_value=missing):
            contents = await server.mcp.read_resource(
                "price-alert://users/secret@example.com/alerts/alert_missing"
            )

        payload = json.loads(contents[0].content)
        self.assertEqual(payload, missing)

    async def test_resource_read_uses_get_alert_tool_boundary(self):
        with patch.object(server, "get_price_alert_tool", return_value={"success": False}) as get_alert:
            await server.mcp.read_resource(
                "price-alert://users/owner@example.com/alerts/alert_owner"
            )

        get_alert.assert_called_once_with("alert_owner", "owner@example.com")

    async def test_prompt_rendering_instructs_client_to_read_resource(self):
        result = await server.mcp.get_prompt(
            "review_price_alert",
            {
                "requester_email": "owner@example.com",
                "alert_id": "alert_123",
            },
        )

        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        self.assertEqual(message.role, "user")
        text = message.content.text
        self.assertIn("price-alert://users/owner@example.com/alerts/alert_123", text)
        self.assertIn("`lowest_notified_price` is the notification baseline", text)
        self.assertIn("Do not trigger a fresh price check", text)

    async def test_prompt_requires_requester_email_and_alert_id(self):
        with self.assertRaises(ValueError):
            await server.mcp.get_prompt("review_price_alert", {})


if __name__ == "__main__":
    unittest.main()
