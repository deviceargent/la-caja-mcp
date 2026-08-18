import importlib
import os
import tempfile
import unittest


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LA_CAJA_DATA"] = self.tmp.name
        import lacaja_mcp.server as server
        self.server = importlib.reload(server)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("LA_CAJA_DATA", None)

    def test_proposal_can_be_retrieved(self):
        created = self.server.propose(
            "Test proposal",
            "A deliberately small proposal.",
            actor="claude",
        )
        entity_id = created["entity"]["id"]
        result = self.server.get_entity(entity_id, actor="chatgpt")
        self.assertEqual(result["entity"]["status"], "candidate")
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["history"][0]["actor"], "claude")

    def test_challenge_unknown_entity_must_not_create_orphan_event(self):
        result = self.server.challenge(
            "does-not-exist",
            "This should fail.",
            actor="chatgpt",
        )
        self.assertEqual(result.get("error"), "entity_not_found")

    def test_status_transition_preserves_history(self):
        created = self.server.propose(
            "Status test",
            "Initial proposal.",
            actor="claude",
        )
        entity_id = created["entity"]["id"]
        self.server.challenge(entity_id, "Objection.", actor="chatgpt")
        self.server.update_entity(
            entity_id,
            "disputed",
            "Objection remains unresolved.",
            actor="claude",
        )
        result = self.server.get_entity(entity_id)
        self.assertEqual(result["entity"]["status"], "disputed")
        self.assertEqual([e["kind"] for e in result["history"]], [
            "proposal", "challenge", "status_change"
        ])

    def test_invalid_status_is_rejected(self):
        created = self.server.propose("Status test", "Proposal.", actor="claude")
        result = self.server.update_entity(
            created["entity"]["id"],
            "truth",
            "This status is not part of the protocol.",
            actor="chatgpt",
        )
        self.assertEqual(result.get("error"), "invalid_status")

    def test_search_finds_event_content(self):
        self.server.propose(
            "Ontology question",
            "Semantic interpretation may remain outside the graph.",
            actor="claude",
        )
        result = self.server.search_context("semantic interpretation")
        self.assertGreaterEqual(len(result["events"]), 1)

    def test_state_does_not_drop_old_events(self):
        created = self.server.propose("Long history", "Initial.", actor="claude")
        entity_id = created["entity"]["id"]
        for i in range(75):
            self.server.challenge(entity_id, f"Objection {i}", actor="chatgpt")
        result = self.server.get_state()
        self.assertEqual(len(result["recent_events"]), 76)


if __name__ == "__main__":
    unittest.main()
