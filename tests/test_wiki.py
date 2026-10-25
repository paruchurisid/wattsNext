import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from concierge import cases, knowledge, local_llm, chat
from backend import restoration
import server

SCENARIO = {"access_blocked": False, "extra_crews": 0, "repairs_complete": False}


class HouseholdWiki(unittest.TestCase):
    def setUp(self):
        self.settings = patch.dict(server.SETTINGS, {"provider": "local", "offline_mode": True})
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.client = TestClient(server.app)
        self.sid = self.client.post("/api/session", json={"household_id": "h1"}).json()["session_id"]
        self.addCleanup(lambda: server.SESSIONS.pop(self.sid, None))

    def wiki(self):
        return self.client.get("/api/wiki", params={"session_id": self.sid}).json()

    def test_wiki_has_household_faqs_computed_statistics_and_limits(self):
        wiki = self.wiki()
        self.assertEqual(wiki["household"]["display_name"], "Household A")
        self.assertEqual(wiki["restoration"]["low_hours"]["value"], 6.7)
        self.assertGreater(len(wiki["faqs"]), 6)
        self.assertFalse(wiki["statistics"]["risk_model"]["is_calibrated"])
        self.assertIsNotNone(wiki["statistics"]["restoration_simulation"]["p50"])
        self.assertIn("chance of losing power", wiki["statistics"]["note"])

    def test_chat_and_wiki_use_same_snapshot_revision(self):
        wiki = self.wiki()
        reply = self.client.post("/api/chat", json={"session_id": self.sid, "message": "Will I lose power and for how long?"}).json()
        self.assertEqual(reply["knowledge_revision"], wiki["revision"])
        self.assertEqual(reply["cards"]["restoration"], wiki["restoration"])

    def test_snapshot_refreshes_after_scenario_and_declarations(self):
        before = self.wiki()
        self.client.post("/api/whatif", json={"session_id": self.sid, "action": "block_access"})
        after = self.wiki()
        self.assertNotEqual(before["revision"], after["revision"])
        self.assertEqual(after["restoration"]["low_hours"]["value"], 9.7)
        self.client.post("/api/chat", json={"session_id": self.sid, "message": "I use a CPAP"})
        medical = self.wiki()
        self.assertNotEqual(after["revision"], medical["revision"])
        self.assertTrue(medical["household"]["declared_needs"]["medical_device"])
        self.assertIn("provider-approved", " ".join(medical["prep"]["actions"]))

    def test_local_prompt_contains_precomputed_wiki_facts(self):
        snapshot = knowledge.build("h1", SCENARIO)
        with patch.object(local_llm, "generate", return_value="The replay estimates a restoration range of 6.7 to 13.5 hours because of damage assigned upstream of this household.") as generate:
            reply = chat.local_reply("How long could repairs take?", "h1", SCENARIO, knowledge_snapshot=snapshot)
        self.assertIn("WIKI CONTEXT", generate.call_args.args[0])
        self.assertIn("Household A", generate.call_args.args[0])
        self.assertFalse(reply["offline"])

    def test_statistics_question_uses_computed_values(self):
        wiki = self.wiki()
        reply = self.client.post("/api/chat", json={"session_id": self.sid, "message": "Explain the P50 median statistics"}).json()
        self.assertEqual(reply["cards"]["statistics"], wiki["statistics"])
        self.assertIn(str(wiki["statistics"]["restoration_simulation"]["p50"]), reply["text"])

    def test_no_path_wiki_has_no_invented_statistics(self):
        result = knowledge.build("h12", SCENARIO)
        self.assertTrue(result["fallback"]["fallback"])
        self.assertIsNone(result["statistics"]["restoration_simulation"])
        self.assertTrue(result["faqs"])

    def test_extra_crews_do_not_compress_single_repair_statistics(self):
        case = cases.get_case("transformer_roanoke")
        baseline = restoration.estimate(case)
        extra = restoration.estimate(case, extra_crews=2)
        self.assertEqual(baseline["monte_carlo"], extra["monte_carlo"])

    def test_completed_repairs_with_blocked_access_have_zero_duration(self):
        result = restoration.estimate(cases.get_case("transformer_roanoke"), repairs_complete=True, access_blocked=True)
        self.assertEqual(result["monte_carlo"]["p90"], 0)

    def test_unknown_session_is_not_exposed(self):
        self.assertEqual(self.client.get("/api/wiki", params={"session_id": "missing"}).status_code, 404)

    def test_session_prepares_all_wiki_documents_before_chat_is_ready(self):
        with patch.object(local_llm, "generate", side_effect=AssertionError("Loading must not call AI")):
            result = self.client.post("/api/session", json={"household_id": "h2"}).json()
        self.addCleanup(lambda: server.SESSIONS.pop(result["session_id"], None))
        self.assertTrue(result["chat_ready"])
        prepared = result["knowledge"]
        self.assertTrue(prepared["chat_context"]["ready"])
        self.assertEqual(len(prepared["faqs"]), len(prepared["chat_context"]["documents"]))
        self.assertEqual(result["knowledge_revision"], prepared["revision"])
        self.assertIn("Household B", prepared["chat_context"]["scope"])
        self.assertIsNotNone(server.SESSIONS[result["session_id"]]["knowledge"])

    def test_failed_preparation_does_not_expose_a_ready_session(self):
        before = set(server.SESSIONS)
        with patch.object(knowledge, "build", side_effect=RuntimeError("bad data")):
            response = self.client.post("/api/session", json={"household_id": "h1"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(set(server.SESSIONS), before)

    def test_scenario_returns_prepared_context_without_opening_wiki(self):
        result = self.client.post("/api/whatif", json={"session_id": self.sid, "action": "block_access"}).json()
        self.assertTrue(result["chat_ready"])
        self.assertEqual(result["knowledge"]["restoration"]["low_hours"]["value"], 9.7)
        self.assertIn("Access blocked in this example: True", result["knowledge"]["chat_context"]["scope"])

    def test_source_data_changes_invalidate_old_context_and_history(self):
        before = self.wiki()
        session = server.SESSIONS[self.sid]
        session["history"] = [{"role": "user", "parts": [{"text": "old facts"}]}]
        with patch.dict(cases.get_household("h1"), {"display_name": "Updated household"}):
            after = self.wiki()
            self.assertNotEqual(before["revision"], after["revision"])
            self.assertIn("Updated household", after["chat_context"]["scope"])
            self.assertEqual(session["history"], [])

    def test_source_change_during_generation_replaces_stale_answer(self):
        original = cases.get_household("h1")["display_name"]
        def generate(*args, **kwargs):
            cases.get_household("h1")["display_name"] = "New data loaded"
            return "This example suggests repairs could take 6.7 to 13.5 hours. These times are not confirmed by your power company."
        try:
            with patch.dict(server.SETTINGS, {"offline_mode": False}), patch.object(local_llm, "generate", side_effect=generate):
                result = self.client.post("/api/chat", json={"session_id": self.sid, "message": "How long could repairs take?"}).json()
            self.assertTrue(result["context_refreshed"])
            self.assertIn("New data loaded", result["knowledge"]["chat_context"]["scope"])
            self.assertIn("updated facts", result["text"])
        finally:
            cases.get_household("h1")["display_name"] = original

    def test_plain_language_faq_questions_route_to_their_wiki_topic(self):
        for topic in ("confidence", "sources", "scenarios", "household", "glossary"):
            item = next(faq for faq in self.wiki()["faqs"] if faq["id"] == topic)
            with self.subTest(topic=topic):
                reply = self.client.post("/api/chat", json={"session_id": self.sid, "message": item["question"]}).json()
                self.assertEqual(reply["text"], item["answer"])
                self.assertEqual(reply["cards"], {})

    def test_general_question_gives_local_model_the_actual_wiki_answer(self):
        snapshot = knowledge.build("h1", SCENARIO)
        expected = next(item["answer"] for item in snapshot["faqs"] if item["id"] == "sources")
        with patch.object(local_llm, "generate", return_value=expected) as generate:
            reply = chat.local_reply("Is this real-time information?", "h1", SCENARIO, knowledge_snapshot=snapshot)
        self.assertIn("FACTS (computed household Wiki):\n" + expected, generate.call_args.args[0])
        self.assertFalse(reply["offline"])
        self.assertEqual(reply["text"], expected)

    def test_chat_accepts_the_same_everyday_words_as_the_buttons(self):
        for question, action in (("What if the road is blocked?", "block_access"),
                                 ("Assume the road is open", "clear_access"),
                                 ("Add two more repair teams", "add_crews")):
            with self.subTest(question=question):
                self.assertEqual(chat.scenario_action(question), action)

    def test_ai_cannot_rename_the_current_confidence_level(self):
        snapshot = knowledge.build("h1", {**SCENARIO, "access_blocked": True})
        expected = chat.offline_reply("How sure are these estimates?", "h1", snapshot["scenario"], knowledge_snapshot=snapshot)
        self.assertFalse(chat._render_is_grounded("The confidence level is Less Certain because we do not know the real road delay in this example.", expected))
        self.assertIn("low confidence", expected["text"])


if __name__ == "__main__":
    unittest.main()
