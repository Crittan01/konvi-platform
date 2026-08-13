import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/connector-whatsapp"))

from services.parser import parse_webhook_payload, parse_webhook_payloads


class WhatsAppParserContextTests(unittest.TestCase):
    def test_parses_multiple_messages_from_single_webhook(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "waba-1",
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "123"},
                                "messages": [
                                    {
                                        "from": "573001112233",
                                        "id": "wamid.in.1",
                                        "type": "text",
                                        "text": {"body": "hola"},
                                    },
                                    {
                                        "from": "573001112233",
                                        "id": "wamid.in.2",
                                        "type": "text",
                                        "text": {"body": "y en azul?"},
                                    },
                                ],
                            }
                        }
                    ],
                }
            ],
        }
        parsed_list = parse_webhook_payloads(payload)
        self.assertEqual(len(parsed_list), 2)
        self.assertEqual(parsed_list[0]["meta_message_id"], "wamid.in.1")
        self.assertEqual(parsed_list[1]["meta_message_id"], "wamid.in.2")

    def test_parses_text_message_with_reply_context(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "waba-1",
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "123"},
                                "messages": [
                                    {
                                        "from": "573001112233",
                                        "id": "wamid.in.1",
                                        "type": "text",
                                        "timestamp": "1710000000",
                                        "text": {"body": "y en azul?"},
                                        "context": {"id": "wamid.out.1", "from": "573001112233"},
                                    }
                                ],
                            }
                        }
                    ],
                }
            ],
        }

        parsed = parse_webhook_payload(payload)
        assert parsed is not None
        self.assertEqual(parsed["content"], "y en azul?")
        self.assertEqual(parsed["payload"]["context"]["id"], "wamid.out.1")
        self.assertEqual(parsed["payload"]["context"]["from"], "573001112233")

    def test_parses_interactive_button_reply_content(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "waba-1",
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "123"},
                                "messages": [
                                    {
                                        "from": "573001112233",
                                        "id": "wamid.in.2",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "button_reply",
                                            "button_reply": {"id": "var-l", "title": "Talla L"},
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                }
            ],
        }

        parsed = parse_webhook_payload(payload)
        assert parsed is not None
        self.assertEqual(parsed["content"], "[Botón] Talla L")
        self.assertEqual(parsed["payload"]["interactive"]["kind"], "button_reply")
        self.assertEqual(parsed["payload"]["interactive"]["id"], "var-l")
        self.assertEqual(parsed["payload"]["interactive"]["title"], "Talla L")


if __name__ == "__main__":
    unittest.main()
