import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import server
from concierge import gemini, local_llm


class VisitorConnections(unittest.TestCase):
    def setUp(self):
        self.settings = patch.dict(server.SETTINGS, {"provider": "local", "offline_mode": False,
                                                    "api_key": None, "model": None})
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.client = TestClient(server.app)
        self.session = self.client.post("/api/session", json={"household_id": "h1"}).json()["session_id"]
        self.addCleanup(lambda: server.SESSIONS.pop(self.session, None))

    def post(self, **extra):
        return self.client.post("/api/chat", json={"session_id": self.session,
            "message": "How long could repairs take?", **extra})

    def test_key_check_does_not_change_shared_settings_or_return_key(self):
        original = dict(server.SETTINGS)
        with patch.object(gemini, "pin_model", return_value="gemini-2.5-flash"):
            response = self.client.post("/api/connection", json={"api_key": "visitor-secret"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("visitor-secret", response.text)
        self.assertEqual(server.SETTINGS, original)

    def test_gemini_request_uses_visitor_key_without_storing_it(self):
        with patch.object(server.chat, "online_reply", return_value={"text": "A Gemini answer", "cards": {}, "offline": False}) as online:
            response = self.post(connection={"provider": "gemini", "offline_mode": False,
                                            "api_key": "visitor-secret", "model": "gemini-2.5-flash"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(online.call_args.args[0], "visitor-secret")
        self.assertIsNone(server.SETTINGS["api_key"])

    def test_gemini_error_does_not_silently_switch_engines(self):
        with patch.object(server.chat, "online_reply", side_effect=gemini.ProviderError("quota", "Quota exceeded")), \
                patch.object(local_llm, "generate", side_effect=AssertionError("must not switch")):
            response = self.post(connection={"provider": "gemini", "api_key": "test", "model": "gemini-2.5-flash"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["category"], "quota")
        self.assertFalse(server.SESSIONS[self.session]["busy"])

    def test_browser_local_round_trip_validates_output_and_records_one_turn(self):
        connection = {"provider": "local", "browser_local": True, "model": "llama3.2:3b", "offline_mode": False}
        with patch.object(local_llm, "generate", side_effect=AssertionError("inference belongs to browser")):
            prepared = self.post(connection=connection).json()
            self.assertIn("local_request", prepared)
            self.assertNotIn("local_expected", prepared)
            self.assertEqual(server.SESSIONS[self.session]["history"], [])
            response = self.post(connection=connection, turn_id=prepared["turn_id"],
                local_result="Repairs in this example could take 6.7 to 13.5 hours because the assigned transformer needs to be replaced.")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["local_model"], "llama3.2:3b")
        self.assertFalse(response.json()["offline"])
        self.assertEqual(len(server.SESSIONS[self.session]["history"]), 2)
        repeated = self.post(turn_id=prepared["turn_id"], local_result="Repeated answer")
        self.assertEqual(repeated.status_code, 409)

    def test_browser_model_cannot_change_verified_estimates(self):
        prepared = self.post(connection={"provider": "local", "browser_local": True}).json()
        response = self.post(turn_id=prepared["turn_id"], local_result="Your repairs are guaranteed to finish in 2 hours and crews are already on their way.")
        self.assertTrue(response.json()["local_fallback"])
        self.assertEqual(response.json()["local_error"]["category"], "validation")

    def test_changed_scenario_rejects_inflight_browser_answer(self):
        prepared = self.post(connection={"provider": "local", "browser_local": True}).json()
        self.client.post("/api/whatif", json={"session_id": self.session, "action": "block_access"})
        response = self.post(turn_id=prepared["turn_id"], local_result="An old answer about repairs.")
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
