import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aidub.batches import invoke_batches, request_batches
from aidub.fidelity import eligibility
from aidub.providers import ProviderError
from aidub.saved_decisions import replay_saved_batch, restore_current_decision
from aidub.schedule import plan_fit
from aidub.util import fingerprint, read_json, write_json


FIXTURES = read_json(Path(__file__).parent / "fixtures/coverage_saved_rows.json")


class SavedCoverageTests(unittest.TestCase):
    def exercise(self, sid):
        case = copy.deepcopy(FIXTURES[str(sid)])
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        request = {"schema": "aidub.review_request.v1", "job_id": "test", "segments": [case["source"]]}
        if sid != 655:
            request["source_resolution_policy"] = "aidub.source_resolution.v1"
        spec = {"kind": "command", "command": ["fake"], "max_attempts": 1}
        cfg = {"batching": {"max_chars": 60000, "max_cues": 40}, "content_recovery": {"max_attempts": 1},
               "source_events": {"enabled": True}, "source_resolution": {"enabled": True}}
        calls = []

        def provider(spec, rp, sp, role):
            body = read_json(rp); calls.append(body)
            row = copy.deepcopy(case["decision"])
            if not body.get("content_recovery"):
                row.update(verdict="revise", english=case["source"]["english"], issues=["duration"], reason="Must change")
            result = {"schema": "aidub.review_response.v1", "job_id": "test", "translator": {"kind": "command"},
                      "segments": [row]}
            write_json(sp, result)
            return result

        current = {sid: case["source"]["english"]}
        with patch("aidub.providers.invoke_provider", side_effect=provider):
            invoke_batches(spec, request, root, "review", current, cfg)
        self.assertEqual(len(calls), 2)
        batch = request_batches(request, max_cues=40, max_chars=60000)[0]
        directory = root / "batches/review" / fingerprint(request) / "batch_0000"
        # Reproduce the pre-7053d1b successful-but-still-withheld aggregate.
        aggregate = read_json(directory / "response.json")
        aggregate["_aidub_withheld"] = [{"id": sid, "reason": "scoped_content_recovery_exhausted"}]
        write_json(directory / "response.json", aggregate)
        budgets = {str(p): p.read_bytes() for p in directory.glob("**/state.json")}
        with patch("aidub.providers.invoke_provider", side_effect=AssertionError("saved work repeated")):
            replay = replay_saved_batch(spec, batch, directory, "review", current)
        self.assertEqual(set(replay["rows"]), {sid})
        self.assertEqual(budgets, {p: Path(p).read_bytes() for p in budgets})
        segment = case["segment"]
        before = copy.deepcopy(segment)
        restored, reason = restore_current_decision(segment, replay["receipts"][str(sid)],
            (case["source"].get("source_evidence") or {}).get("mic_sha256"))
        self.assertEqual(segment, before)
        self.assertEqual(reason, "replayed_identity_bound_ok")
        self.assertEqual(eligibility(restored, cfg, (case["source"].get("source_evidence") or {}).get("mic_sha256"))["synthesis"], "full")
        self.assertIn("receipt", restored["translation_review"])
        self.assertTrue(restored["decision_recovery_history"])
        with patch("aidub.providers.invoke_provider", side_effect=AssertionError("budget reset")):
            resumed = invoke_batches(dict(spec, max_attempts=3), request, root, "review", current, cfg)
        self.assertEqual(resumed["_aidub_withheld"], [])
        self.assertEqual(budgets, {p: Path(p).read_bytes() for p in budgets})
        return replay, batch, directory, spec, current, segment

    def test_cue_83_saved_source_approval_survives_resume(self):
        self.exercise(83)

    def test_cue_123_accent_variant_saved_approval_survives_resume(self):
        self.exercise(123)

    def test_cue_523_saved_approval_keeps_current_english(self):
        self.exercise(523)

    def test_cue_655_ok_supersedes_old_marker_but_does_not_bypass_fit(self):
        self.exercise(655)
        self.assertEqual(plan_fit(1.4, .64, .64, 1.10)[0], "unresolved")

    def test_stale_text_wrong_parent_and_tampered_response_not_accepted(self):
        replay, batch, directory, spec, current, segment = self.exercise(83)
        with self.assertRaisesRegex(ProviderError, "current English"):
            replay_saved_batch(spec, batch, directory, "review", {83: "Stale"})
        receipt = replay["receipts"]["83"]
        path = Path(receipt["response_path"])
        response = read_json(path); response["segments"][0]["source_assessment"]["evidence_id"] = "foreign"
        write_json(path, response)
        self.assertNotIn(83, replay_saved_batch(spec, batch, directory, "review", current)["rows"])
        self.assertEqual(restore_current_decision(segment, receipt, "mic")[1], "saved_receipt_no_longer_valid")
        scope = directory / "content_recovery"; rp = next(scope.glob("*/request.json"))
        req = read_json(rp); req["content_recovery"]["parent_request_identity"] = "foreign"
        write_json(rp, req)
        self.assertNotIn(83, replay_saved_batch(spec, batch, directory, "review", current)["rows"])

    def test_recovered_actual_revision_stays_unconfirmed(self):
        replay, _, _, _, _, segment = self.exercise(655)
        # This assertion covers the reducer used after a valid non-identical
        # revision: it cannot acquire an `ok` through marker cleanup.
        from aidub.review import review_decision
        row = {"id": 655, "verdict": "revise", "english": "I don't know why.", "issues": ["duration"]}
        self.assertEqual(review_decision(row, segment["english"], row["english"])["status"], "revised_unconfirmed")

