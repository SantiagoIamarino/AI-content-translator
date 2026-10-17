import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aidub.batches import invoke_batches
from aidub.fidelity import eligibility
from aidub.omissions import build_omission_report, omissions_markdown
from aidub.providers import ProviderError
from aidub.review import run_review
from aidub.util import read_json, write_json


def review_request(ids):
    return {"schema": "aidub.review_request.v1", "job_id": "job", "segments": [
        {"id": sid, "spanish": f"fuente {sid}", "english": f"English {sid}"} for sid in ids]}


def decision(sid, verdict="ok", english=None):
    row = {"id": sid, "verdict": verdict, "issues": [], "reason": "", "disputed": False}
    if verdict == "revise":
        row.update(english=english, issues=["unnatural"], reason="Actual wording issue")
    return row


class ContentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.spec = {"kind": "command", "command": ["fake"], "max_attempts": 1}
        self.cfg = {"batching": {"max_cues": 2, "max_chars": 10000}, "content_recovery": {"max_attempts": 1}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_invalid_row_is_scoped_and_later_batch_continues(self):
        calls = []

        def fake(spec, req_path, response_path, role):
            req = read_json(req_path)
            ids = [r["id"] for r in req["segments"]]
            calls.append((ids, bool(req.get("content_recovery"))))
            if ids == [1, 2] and not req.get("content_recovery"):
                rows = [decision(1), decision(2, "revise", "English 2")]
            elif ids == [2]:
                rows = [decision(2, "revise", "A justified changed translation.")]
            else:
                rows = [decision(sid) for sid in ids]
            response = {"schema": "aidub.review_response.v1", "job_id": "job",
                        "translator": {"kind": "command"}, "segments": rows}
            write_json(response_path, response)
            return response

        with patch("aidub.providers.invoke_provider", side_effect=fake):
            result = invoke_batches(self.spec, review_request([1, 2, 3, 4]), self.root, "review", 
                                    {1: "English 1", 2: "English 2", 3: "English 3", 4: "English 4"}, self.cfg)
        self.assertEqual([r["id"] for r in result["segments"]], [1, 2, 3, 4])
        self.assertEqual(result["_aidub_withheld"], [])
        self.assertEqual(calls, [([1, 2], False), ([2], True), ([3, 4], False)])

    def test_failed_subset_is_persisted_and_resume_does_not_repeat_it(self):
        req = review_request([1, 2])
        calls = []

        def fake(spec, req_path, response_path, role):
            body = read_json(req_path)
            calls.append([r["id"] for r in body["segments"]])
            rows = ([decision(2, "revise", "English 2")] if body.get("content_recovery")
                    else [decision(1), decision(2, "revise", "English 2")])
            response = {"schema": "aidub.review_response.v1", "job_id": "job",
                        "translator": {"kind": "command"}, "segments": rows}
            write_json(response_path, response)
            return response

        with patch("aidub.providers.invoke_provider", side_effect=fake):
            first = invoke_batches(self.spec, req, self.root, "review", {1: "English 1", 2: "English 2"}, self.cfg)
        self.assertEqual(first["_aidub_withheld"][0]["id"], 2)
        self.assertEqual(calls, [[1, 2], [2]])
        recovery_request = read_json(next(self.root.glob("batches/review/*/batch_0000/content_recovery/*/request.json")))
        self.assertEqual(recovery_request["content_recovery"]["budget"], 1)
        self.assertTrue(any("unchanged" in error for error in recovery_request["validation_feedback"]["errors"]))
        original_state = read_json(next(self.root.glob("batches/review/*/batch_0000/response_attempts/*/state.json")))
        self.assertEqual(len(original_state["attempts"]), 1)
        self.spec["max_attempts"] = 3  # A later generic budget increase cannot reopen this identity.
        with patch("aidub.providers.invoke_provider", side_effect=AssertionError("accepted work repeated")):
            second = invoke_batches(self.spec, req, self.root, "review", {1: "English 1", 2: "English 2"}, self.cfg)
        self.assertEqual(second["_aidub_withheld"], first["_aidub_withheld"])

    def test_missing_duplicate_foreign_ids_and_stale_text_are_never_partially_accepted(self):
        req = review_request([1, 2])
        cases = ([decision(1)], [decision(1), decision(1)], [decision(1), decision(99)])
        for rows in cases:
            with self.subTest(rows=rows):
                from aidub.batches import _envelope_error
                response = {"schema": "aidub.review_response.v1", "job_id": "job",
                            "translator": {"kind": "command"}, "segments": rows}
                self.assertIsNotNone(_envelope_error(req, response, "review"))
        from aidub.batches import _row_valid
        stale = decision(1, "revise", "English 1")
        self.assertTrue(any("unchanged" in e for e in _row_valid(req, stale, "review", {1: "English 1"})))

    def test_revised_text_requires_exact_confirmation_and_withheld_is_ineligible(self):
        req = {"job_id": "job", "segments": [{"id": 1, "spanish": "Mirá", "english": "Look"}]}
        calls = 0

        def invoke(role, request, current):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"segments": [decision(1, "revise", "Come on") ]}
            return {"segments": [decision(1)]}

        cfg = {"translation_quality": {"enabled": True, "review": {"enabled": True, "max_rounds": 2}}}
        _, audit = run_review("job", req, {1: "Look"}, invoke, cfg)
        self.assertEqual(audit["lines"]["1"]["status"], "revised_confirmed")
        seg = {"english": "English", "translation_review": {"status": "withheld_review_failure"}}
        self.assertEqual(eligibility(seg, {"source_events": {"enabled": True}})["synthesis"], "withheld")

    def test_prior_unchanged_revise_failures_are_explicit_in_next_review_request(self):
        req = {"job_id": "job", "segments": [{"id": 523, "spanish": "No me gustó", "english": "It looked bad."},
                                                   {"id": 556, "spanish": "Parece una rampa", "english": "It looks like a ramp."}]}
        next_request = {}

        def invoke(role, request, current):
            nonlocal next_request
            if request["round"] == 1:
                return {"segments": [decision(523, "revise", "I didn't like how it looked."),
                                     {"id": 556, "verdict": "ok", "issues": ["uncertain_source"],
                                      "reason": "The source wording is uncertain.", "disputed": True}],
                        "_aidub_historical_validation_feedback": {
                            "523": ["id 523 revise text is unchanged"],
                            "556": ["id 556 revise text is unchanged"]}}
            next_request = request
            return {"segments": [decision(523), decision(556)]}

        cfg = {"translation_quality": {"enabled": True, "review": {"enabled": True, "max_rounds": 2,
                                                                           "back_translation": "off"}}}
        run_review("job", req, {523: "It looked bad.", 556: "It looks like a ramp."}, invoke, cfg)
        errors = next_request["validation_feedback"]["errors"]
        self.assertTrue(any("id 523" in e for e in errors))
        self.assertTrue(any("id 556" in e for e in errors))

    def test_infrastructure_failure_is_not_reclassified_as_content_omission(self):
        req = review_request([1, 2])
        with patch("aidub.providers.invoke_provider", side_effect=ProviderError("quota exhausted", permanent=True)):
            with self.assertRaisesRegex(ProviderError, "quota exhausted"):
                invoke_batches(self.spec, req, self.root, "review", {1: "English 1", 2: "English 2"}, self.cfg)

    def test_partial_omission_report_binds_export_and_explains_withheld_cue(self):
        report = build_omission_report("job", "partial", "/job/output/english_PARTIAL.mp4", "abc", "rev1",
            [{"id": 2, "start": 10.2, "end": 12.4, "status": "not_placed"}],
            [{"id": 2, "start": 10.2, "end": 12.4, "spanish": "No sé.", "english": "I don't know.",
              "translation_review": {"status": "withheld_review_failure",
                                     "reason": {"reason": "scoped_content_recovery_exhausted"}}}])
        self.assertEqual(report["export"], "/job/output/english_PARTIAL.mp4")
        self.assertEqual(report["validation_fingerprint"], "rev1")
        omission = report["omissions"][0]
        self.assertEqual((omission["spanish"], omission["english"], omission["recovery_state"]),
                         ("No sé.", "I don't know.", "scoped_content_recovery_exhausted"))
        self.assertIn("10.200–12.400s", omissions_markdown(report))

    def test_omission_markdown_handles_missing_timestamps(self):
        report = build_omission_report("job", "partial", "/job/output/english_PARTIAL.mp4", "abc", "rev1",
            [{"id": 2, "start": None, "end": None, "status": "withheld_source_uncertainty"}],
            [{"id": 2, "start": None, "end": None, "spanish": "No entiendo.", "english": None,
              "translation_review": {"status": "withheld_source_uncertainty",
                                     "reason": {"reason": "source_boundary_unresolved"}}}])
        markdown = omissions_markdown(report)
        self.assertIn("timestamp unavailable", markdown)
        self.assertIn("## ID 2", markdown)


if __name__ == "__main__":
    unittest.main()
