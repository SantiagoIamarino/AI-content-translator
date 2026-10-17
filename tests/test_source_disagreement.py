import copy
import unittest
from pathlib import Path
from types import SimpleNamespace

from aidub.fidelity import eligibility
from aidub.source_disagreement import compare_readings, disagreement, bind_comparison_evidence
from aidub.source_resolution import assessment_errors, target_segments
from aidub.util import read_json

CASES = read_json(Path(__file__).parent / "fixtures/coverage_disagreements.json")
CFG = {"source_events": {"enabled": True}, "source_resolution": {"enabled": True}}


class DisagreementTests(unittest.TestCase):
    def test_saved_minor_discourse_keeps_exact_reviewed_english(self):
        for sid in (2, 4, 155):
            s = copy.deepcopy(CASES[str(sid)]["segment"])
            self.assertEqual(disagreement(s)["kind"], "minor", sid)
            self.assertEqual(eligibility(s, CFG)["synthesis"], "full", sid)
            self.assertEqual(target_segments(SimpleNamespace(data={"timeline": [s]},
                dir=Path("/nonexistent")), CFG), [])
            s["translation_review"]["status"] = "revised_unconfirmed"
            self.assertEqual(eligibility(s, CFG)["synthesis"], "withheld")

    def test_minor_still_needs_acoustic_words_and_normal_review(self):
        s = copy.deepcopy(CASES["2"]["segment"])
        s["source_words"] = []
        self.assertEqual(eligibility(s, CFG)["reason"], "source_lexical_evidence_required")
        s = copy.deepcopy(CASES["2"]["segment"])
        s["translation_review"]["status"] = "withheld_review_failure"
        self.assertEqual(eligibility(s, CFG)["reason"], "content_review_recovery_exhausted")

    def test_material_controls_and_localized_unknowns_never_auto_approved(self):
        for a, b in [("3300", "300"), ("No sé lo que busco", "Sé lo que busco"),
                     ("Tengo dos perros", "Tengo tres perros")]:
            self.assertEqual(compare_readings(a, b)["kind"], "material")
        for a, b in [("Yo vendo la casa", "Ellos compran la casa"), ("Morí", "Mori"),
                     ("Vamos vamos a casa", "Vamos a casa"), ("Está bien aquí", "Está aquí"),
                     ("Está bien aquí, bien, ahora vamos", "Está aquí, bien, ahora vamos"),
                     ("Está bien, vamos a casa", "Está, vamos a casa")]:
            self.assertEqual(compare_readings(a, b)["kind"], "localized")
        for sid in (234, 676):
            self.assertEqual(eligibility(CASES[str(sid)]["segment"], CFG)["synthesis"], "withheld")
        self.assertEqual(compare_readings("Hábitat, dos barreras", "Habitat: 2 barreras")["kind"], "equivalent")

    def test_contextual_material_reading_cannot_hide_behind_minor_second_pass(self):
        s = copy.deepcopy(CASES["2"]["segment"])
        s["source_evidence"] = copy.deepcopy(CASES["2"]["episode"]["evidence"])
        s["source_evidence"]["inside"]["text"] = "No es mi primera vez creando un zoológico."
        self.assertEqual(disagreement(s)["kind"], "material")

    def test_saved_context_and_stale_acoustic_binding(self):
        case = CASES["155"]; evidence = copy.deepcopy(case["episode"]["evidence"])
        s = bind_comparison_evidence(case["segment"], evidence, evidence["mic_sha256"])
        self.assertIn("source_comparison_evidence", s)
        self.assertEqual(disagreement(s)["kind"], "localized")
        self.assertEqual(eligibility(s, CFG)["reason"], "localized_source_review_required")
        evidence["inside"]["text"] = "A modified hearing"
        self.assertNotIn("source_comparison_evidence", bind_comparison_evidence(
            case["segment"], evidence, evidence["mic_sha256"]))

    def test_source_reviewer_keeps_material_guards_but_not_harmless_text_identity(self):
        for sid in (2, 4, 155, 676):
            case = CASES[str(sid)]; src = copy.deepcopy(case["segment"])
            e = case["episode"]["evidence"]
            src.update(source_evidence=e, source_span=e["span"])
            row = {"id": sid, "verdict": "ok", "issues": [], "disputed": False,
                   "source_assessment": {"confidence": "minor", "reading": e["primary_text"],
                     "evidence_id": e["identity"], "reason": "Compare the supplied acoustic words", "parts": []}}
            errors = assessment_errors(row, src, src["english"])
            if sid in (155, 676):
                self.assertTrue(any("contextual acoustic" in e for e in errors))
            else:
                self.assertEqual(errors, [], (sid, errors))

    def test_primary_can_be_supported_by_independent_context_with_minor_connector(self):
        s = copy.deepcopy(CASES["4"]["segment"])
        e = copy.deepcopy(CASES["4"]["episode"]["evidence"])
        s.update(source_evidence=e, source_span=e["span"])
        # An older clipped alternative is not authority over the independently
        # heard complete clause. Acceptance still needs a valid source review.
        s["asr_alternatives"] = [{"text": "para el staff"}]
        row = {"verdict": "ok", "issues": [], "disputed": False, "source_assessment": {
            "confidence": "minor", "reading": e["primary_text"], "evidence_id": e["identity"],
            "reason": "Independent context supports the same clause; initial conjunction only", "parts": []}}
        self.assertEqual(assessment_errors(row, s, s["english"]), [])
        self.assertEqual(eligibility(s, CFG)["synthesis"], "withheld")

    def test_number_control_cannot_be_approved_by_choosing_the_other_asr(self):
        c = CASES["676"]; e = c["episode"]["evidence"]
        s = dict(c["segment"], source_evidence=e, source_span=e["span"])
        row = {"verdict": "ok", "issues": [], "disputed": False, "source_assessment": {
            "confidence": "supported", "reading": e["inside"]["text"], "evidence_id": e["identity"],
            "reason": "Selected alternative", "parts": []}}
        self.assertTrue(any("number readings" in error for error in assessment_errors(row, s, s["english"])))
