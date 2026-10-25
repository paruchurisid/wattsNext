import io
import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from starlette.testclient import TestClient
from concierge import chat, local_llm, tools
from backend.validator import validate
import server

SCENARIO = {"access_blocked": False, "extra_crews": 0, "repairs_complete": False}


class LocalAdapter(unittest.TestCase):
    def response(self, payload):
        return io.BytesIO(json.dumps(payload).encode())

    def test_configuration_is_read_after_import(self):
        with patch.dict(os.environ, {"OLLAMA_MODEL": "test-model", "OLLAMA_BASE_URL": "http://localhost:11434/"}):
            self.assertEqual(local_llm.model_name(), "test-model")
            self.assertEqual(local_llm.base_url(), "http://localhost:11434")

    def test_chat_uses_system_bounded_history_and_tuned_options(self):
        history = [{"role": "model", "parts": [{"text": "old answer"}]}] * 12
        with patch("urllib.request.urlopen", return_value=self.response({"message": {"content": "Test answer"}})) as request:
            self.assertEqual(local_llm.generate("Question", system="System", history=history), "Test answer")
            payload = json.loads(request.call_args.args[0].data)
            self.assertEqual(payload["messages"][0]["role"], "system")
            self.assertEqual(len(payload["messages"]), 6)
            self.assertEqual(payload["messages"][1]["role"], "assistant")
            self.assertFalse(payload["stream"])
            self.assertEqual(payload["keep_alive"], "10m")
            self.assertLessEqual(payload["options"]["temperature"], .15)

    def test_empty_malformed_and_truncated_outputs_fail_cleanly(self):
        for payload in ({}, [], {"message": "bad"}, {"message": {"content": 1}},
                        {"message": {"content": "partial"}, "done_reason": "length"}):
            with self.subTest(payload=payload), patch("urllib.request.urlopen", return_value=self.response(payload)):
                with self.assertRaises(local_llm.LocalProviderError):
                    local_llm.generate("Question")

    def test_timeout_has_actionable_category(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            with self.assertRaises(local_llm.LocalProviderError) as error:
                local_llm.generate("Question")
            self.assertEqual(error.exception.category, "timeout")

    def test_status_checks_installed_model(self):
        with patch.object(local_llm, "model_name", return_value="llama3.2:3b"), patch.object(local_llm, "_request", return_value={"models": [{"name": "llama3.2:3b"}]}):
            self.assertTrue(local_llm.status()["connected"])
        with patch.object(local_llm, "_request", return_value={"models": []}):
            self.assertEqual(local_llm.status()["error"]["category"], "model_missing")


class GroundedConversation(unittest.TestCase):
    def test_nearby_invented_number_is_not_rounded_into_whitelist(self):
        self.assertFalse(validate("6.74 hours", [6.7])["passed"])
        self.assertTrue(validate("6.7-13.5 hours", [6.7, 13.5])["passed"])

    def test_valid_render_uses_local_model_and_keeps_cards(self):
        with patch.object(local_llm, "generate", return_value="The replay estimates a restoration range of 6.7 to 13.5 hours because damage is assigned upstream of your household."):
            result = chat.local_reply("Will I lose power and for how long?", "h1", SCENARIO)
        self.assertFalse(result["offline"])
        self.assertIn("Medium confidence", result["text"])
        self.assertIn("not confirmed", result["text"])
        self.assertEqual(result["cards"]["restoration"]["low_hours"]["value"], 6.7)

    def test_invented_estimate_falls_back_with_visible_reason(self):
        with patch.object(local_llm, "generate", return_value="Your power will be back in 2 hours and our crews are already on the way."):
            result = chat.local_reply("How long?", "h1", SCENARIO)
        self.assertTrue(result["offline"])
        self.assertTrue(result["local_fallback"])
        self.assertEqual(result["local_error"]["category"], "validation")
        self.assertIn("6.7-13.5", result["text"])

    def test_medical_safety_is_retained_when_model_omits_it(self):
        with patch.object(local_llm, "generate", return_value="Prepare essential devices and keep your household ready for a possible power interruption in this replay."):
            result = chat.local_reply("What should I do to prepare?", "h2", SCENARIO)
        self.assertIn("provider-approved", result["text"])
        self.assertIn("not a substitute", result["text"])

    def test_safety_and_completion_do_not_depend_on_model(self):
        with patch.object(local_llm, "generate", side_effect=AssertionError("must not call")):
            prep = chat.local_reply("What should I do to prepare?", "h2", SCENARIO)
            complete = chat.local_reply("When will power be back on?", "h1", {**SCENARIO, "repairs_complete": True})
        self.assertEqual(prep["rules_reason"], "safety_guidance")
        self.assertEqual(complete["rules_reason"], "repairs_complete")
        self.assertIn("report", complete["text"])

    def test_conflicting_labels_and_invented_percentages_are_rejected(self):
        expected = chat.offline_reply("Will I lose power and for how long?", "h1", SCENARIO)
        for text in ("There is a 6.7% chance of losing power for 13.5 hours.",
                     "Low risk and high confidence; restoration takes 6.7-13.5 hours."):
            text = chat._attach_verified_guidance(text, expected)
            self.assertFalse(chat._render_is_grounded(text, expected))

    def test_followup_uses_previous_intent(self):
        history = [{"role": "user", "parts": [{"text": "How long could repairs take?"}]}]
        result = chat.offline_reply("Why is that?", "h1", SCENARIO, history)
        self.assertIn("restoration", result["cards"])
        self.assertNotIn("alerts", result["cards"])
        self.assertEqual(result["rules_reason"], "follow_up")
        self.assertLess(len(result["text"].split()), 90)

    def test_explicit_medical_declarations_only(self):
        self.assertEqual(chat.declared_needs_update("I use a CPAP"), {"medical_device": True})
        self.assertEqual(chat.declared_needs_update("I don't use a CPAP"), {"medical_device": False})
        self.assertEqual(chat.declared_needs_update("My neighbor uses a CPAP"), {})
        self.assertEqual(chat.declared_needs_update("What if someone needs a medical device?"), {})

    def test_blocked_access_confidence_is_consistent(self):
        result = chat.offline_reply("Will I lose power and for how long?", "h1", {**SCENARIO, "access_blocked": True})
        self.assertEqual(result["cards"]["risk"]["confidence"]["value"], "Low")
        self.assertEqual(result["cards"]["restoration"]["confidence"]["value"], "Low")


class ChatAPI(unittest.TestCase):
    def setUp(self):
        self.settings = patch.dict(server.SETTINGS, {"provider": "local", "offline_mode": False, "api_key": None, "model": None})
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.client = TestClient(server.app)
        self.session = self.client.post("/api/session", json={"household_id": "h1"}).json()["session_id"]
        self.addCleanup(lambda: server.SESSIONS.pop(self.session, None))

    def post(self, message):
        return self.client.post("/api/chat", json={"session_id": self.session, "message": message})

    def test_offline_toggle_never_calls_local_model(self):
        server.SETTINGS["offline_mode"] = True
        with patch.object(local_llm, "generate", side_effect=AssertionError("must not call")):
            result = self.post("How long will repairs take?")
        self.assertTrue(result.json()["offline"])

    def test_chat_applies_same_scenario_actions_as_buttons(self):
        server.SETTINGS["offline_mode"] = True
        blocked = self.post("What if access is blocked?").json()
        self.assertEqual(blocked["scenario_change"]["after"]["low_hours"]["value"], 9.7)
        self.assertEqual(blocked["cards"]["risk"]["confidence"]["value"], "Low")
        self.assertTrue(any(p["type"] == "estimate_updated" for p in blocked["cards"]["alerts"]["message_previews"]))
        cleared = self.post("What if access is clear?").json()
        self.assertEqual(cleared["scenario_change"]["after"]["low_hours"]["value"], 6.7)
        complete = self.post("What if repairs finish?").json()
        self.assertEqual(complete["scenario_change"]["after"]["high_hours"]["value"], 0.0)
        reset = self.post("Start over before the storm").json()
        self.assertEqual(reset["scenario_change"]["scenario"], SCENARIO)

    def test_failed_settings_connection_preserves_working_provider(self):
        with patch.object(server.gemini, "pin_model", side_effect=server.gemini.ProviderError("permission", "bad key")):
            result = self.client.post("/api/settings", json={"provider": "gemini", "api_key": "test"})
        self.assertEqual(result.status_code, 502)
        self.assertEqual(server.SETTINGS["provider"], "local")

    def test_malformed_supporting_requests_do_not_crash(self):
        for route in ("/api/session", "/api/settings", "/api/whatif"):
            self.assertEqual(self.client.post(route, json=[]).status_code, 400)
        self.assertEqual(self.client.post("/api/session", json={"household_id": []}).status_code, 400)
        self.assertEqual(self.client.post("/api/settings", json={"offline_mode": "false"}).status_code, 400)

    def test_history_is_bounded(self):
        server.SETTINGS["offline_mode"] = True
        for _ in range(10):
            self.post("Hello")
        self.assertEqual(len(server.SESSIONS[self.session]["history"]), 12)

    def test_bad_requests_return_400(self):
        for message in (None, [], 42, " ", "x" * 2001):
            with self.subTest(message=type(message).__name__):
                self.assertEqual(self.post(message).status_code, 400)
        self.assertEqual(self.client.post("/api/chat", content="{").status_code, 400)
        self.assertEqual(self.client.post("/api/chat", json=[]).status_code, 400)

    def test_local_failure_still_returns_answer(self):
        with patch.object(local_llm, "generate", side_effect=local_llm.LocalProviderError("Start Ollama")):
            result = self.post("How long?")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["local_fallback"])
        self.assertFalse(server.SESSIONS[self.session]["busy"])

    def test_explicit_needs_persist_only_in_this_session(self):
        server.SETTINGS["offline_mode"] = True
        self.post("I use a CPAP")
        result = self.post("How should I prepare?").json()
        self.assertIn("provider-approved", result["text"])
        self.assertFalse(tools.cases.get_household("h1")["declared_needs"].get("medical_device"))
        self.post("I don't use a CPAP")
        self.assertFalse(server.SESSIONS[self.session]["declared_needs"]["medical_device"])

    def test_slow_model_does_not_block_settings_or_allow_scenario_races(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            entered.set()
            release.wait(5)
            raise local_llm.LocalProviderError("test")
        with patch.object(local_llm, "generate", side_effect=slow), patch.object(local_llm, "status", return_value={"connected": True, "error": None}), ThreadPoolExecutor(1) as pool:
            request = pool.submit(self.post, "How long?")
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.client.get("/api/settings").status_code, 200)
                self.assertEqual(self.post("Another question").status_code, 409)
                self.assertEqual(self.client.post("/api/whatif", json={"session_id": self.session, "action": "block_access"}).status_code, 409)
            finally:
                release.set()
            self.assertEqual(request.result(timeout=3).status_code, 200)

    def test_settings_report_local_model_health_not_gemini_model(self):
        with patch.object(local_llm, "status", return_value={"connected": True, "error": None}):
            result = self.client.get("/api/settings").json()
        self.assertTrue(result["connected"])
        self.assertEqual(result["model"], local_llm.model_name())

    def test_replay_route_returns_estimate(self):
        result = self.client.get("/api/replay", params={"session_id": self.session})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["low_hours"], 6.7)


if __name__ == "__main__":
    unittest.main()
