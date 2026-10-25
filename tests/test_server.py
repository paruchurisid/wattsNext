import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import server
from concierge import gemini


class ChatFlow(unittest.TestCase):
    def setUp(self):
        server.SETTINGS["offline_mode"] = True
        server.SETTINGS["api_key"] = None
        server.SETTINGS["model"] = None
        self.client = TestClient(server.app)
        resp = self.client.post("/api/session", json={"household_id": "h1"})
        self.session_id = resp.json()["session_id"]

    def test_offline_mode_is_labeled(self):
        resp = self.client.post("/api/chat", json={"session_id": self.session_id, "message": "Will I lose power?"})
        body = resp.json()
        self.assertTrue(body["offline"])
        self.assertIn("risk", body["cards"])

    def test_live_data_question_is_refused_honestly(self):
        resp = self.client.post("/api/chat", json={"session_id": self.session_id, "message": "Is the shelter on Main St open?"})
        body = resp.json()
        self.assertIn("redcross.org", body["text"])
        self.assertEqual(body["cards"], {})

    def test_fallback_household_gets_fallback_response(self):
        resp = self.client.post("/api/session", json={"household_id": "h12"})
        session_id = resp.json()["session_id"]
        resp = self.client.post("/api/chat", json={"session_id": session_id, "message": "Will I lose power?"})
        self.assertTrue(resp.json()["fallback"])


class WhatIfFlow(unittest.TestCase):
    def setUp(self):
        server.SETTINGS["offline_mode"] = True
        self.client = TestClient(server.app)
        resp = self.client.post("/api/session", json={"household_id": "h1"})
        self.session_id = resp.json()["session_id"]

    def test_block_access_moves_the_range_and_shows_before_after(self):
        resp = self.client.post("/api/whatif", json={"session_id": self.session_id, "action": "block_access"})
        body = resp.json()
        self.assertEqual(body["before"]["low_hours"]["value"], 6.7)
        self.assertEqual(body["after"]["low_hours"]["value"], 9.7)

    def test_complete_repairs_triggers_restoration_complete_message(self):
        resp = self.client.post("/api/whatif", json={"session_id": self.session_id, "action": "complete_repairs"})
        body = resp.json()
        previews = body["alerts"]["message_previews"]
        self.assertTrue(any(p["type"] == "restoration_complete" for p in previews))


class SettingsEndpoint(unittest.TestCase):
    def test_bad_key_reports_honest_error_and_offers_offline(self):
        client = TestClient(server.app)
        with patch.object(gemini, "pin_model", side_effect=gemini.ProviderError("permission", "Invalid key")):
            resp = client.post("/api/settings", json={"api_key": "not-a-real-key"})
        self.assertEqual(resp.status_code, 502)
        self.assertTrue(resp.json()["offer_offline"])


if __name__ == "__main__":
    unittest.main()
