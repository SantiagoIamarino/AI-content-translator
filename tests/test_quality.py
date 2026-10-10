import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from aidub.audio import adaptive_margins, speech_bounds
from aidub.config import apply_preset, load_config, load_preset
from aidub.context import (
    join_short_pauses,
    quality_translation_request,
    utterance_groups,
    validate_context_response,
)
from aidub.handoff import translation_request
from aidub.linework import collect_line_best_of_n
from aidub.providers import ProviderError, resolve_role
from aidub.review import run_review, validate_review_response
from aidub.second_pass import run_second_pass
from aidub.selection import choose, pacing, pacing_issues, settings as selection_settings
from aidub.textnorm import english_syllables, normalize_tokens, sequence_check
from aidub.util import fingerprint, read_json


def _seg(i, start, end, spanish, **extra):
    return {"id": i, "start": start, "end": end, "spanish": spanish, "notes": "", "uncertain_words": [], **extra}


class SequenceCheckTests(unittest.TestCase):
    def test_contractions_numbers_and_fillers_are_harmless(self):
        self.assertEqual(normalize_tokens("I'm gonna use 2 shells, uh, okay"), normalize_tokens("I am going to use two shells ok"))
        check = sequence_check("I'm gonna try the shotgun this time.", "I am going to try the shotgun this time")
        self.assertEqual(check["hard"], [])
        self.assertEqual(check["soft"], [])

    def test_long_word_substitution_is_not_a_spelling_variant(self):
        check = sequence_check("and they transform.", "and they transfer.")
        self.assertIn("transform", check["substituted"])
        self.assertIn("short_phrase_mismatch", check["soft"])
        self.assertEqual(sequence_check("Okay, I dodged it a little.", "Okay, I dodge it a little.")["soft"], [])

    def test_negation_flip_is_a_hard_error(self):
        check = sequence_check("I don't know where Ashley is.", "I know where Ashley is.")
        self.assertIn("critical_negation", check["hard"])

    def test_missing_number_and_name_are_reported(self):
        self.assertIn("critical_number", sequence_check("We have three shells left for Leon.", "We have shells left for Leon.")["hard"])
        check = sequence_check("I think Ashley is somewhere around here.", "I think actually is somewhere around here.")
        self.assertIn("critical_name", check["hard"])
        self.assertEqual(sequence_check("I think Ashley is over there.", "I think Ashlee is over there.")["hard"], [])
        self.assertIn("critical_name", sequence_check("Ashley is hiding over here somewhere.", "Actually is hiding over here somewhere.",
                                                      names=["Ashley"])["hard"])
        self.assertIn("critical_name", sequence_check("Ashley is here.", "Actually is here.", names=["Ashley"])["soft"])

    def test_repetition_reordering_and_truncation(self):
        self.assertIn("repetition", sequence_check("Let's go, let's go.", "Let's go, let's go, let's go, let's go.")["hard"])
        self.assertEqual(sequence_check("Come on, come on!", "Come on, come on.")["hard"], [])
        self.assertIn("reordered_words", sequence_check("the dog almost killed me now", "now me killed almost the dog")["hard"])
        self.assertIn("truncated_speech", sequence_check("We are inside the church right now", "We are inside the")["hard"])

    def test_short_reactions_are_disputed_not_rejected(self):
        check = sequence_check("Uff.", "Huh.")
        self.assertEqual(check["hard"], [])
        self.assertIn("short_phrase_mismatch", check["soft"])
        self.assertEqual(sequence_check("Oof.", "Uff")["soft"], [])

    def test_babble_and_wrong_language(self):
        self.assertIn("extra_speech", sequence_check("Perfect.", "Perfect, and then we go to the next room and look around")["hard"])
        self.assertIn("wrong_language", sequence_check("Thank goodness for that.", "Menos mal por eso", language="es")["hard"])

    def test_syllable_estimates(self):
        self.assertEqual(english_syllables("Shotgun blast"), 3)
        self.assertGreater(english_syllables("We're inside the church. Come on, come on."), 8)


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()
        self.cfg["translation_quality"] = {"enabled": True, "english_syllables_per_sec": 5.0}
        self.segments = [_seg(1, 3.2, 5.7, "Bien, tenemos a estos perritos ahora"), _seg(2, 6.7, 7.7, "Que se convierten"),
                         _seg(3, 13.2, 13.6, "Me pegó."), _seg(4, 75.3, 76.6, "Bueno, no sé dónde está Ashley")]

    def test_glossary_terms_must_occur_in_transcript(self):
        request = {"job_id": "j", "transcript": [{"spanish": s["spanish"]} for s in self.segments]}
        good = {"schema": "aidub.context_response.v1", "job_id": "j", "translator": {"kind": "command"},
                "summary": "The speaker fights dogs.", "speaker_register": "Rioplatense, casual", "style_notes": [],
                "glossary": [{"spanish": "Ashley", "english": "Ashley", "kind": "name"}]}
        self.assertEqual(validate_context_response(request, good), [])
        invented = dict(good, glossary=[{"spanish": "Leon Kennedy", "english": "Leon", "kind": "name"}])
        self.assertTrue(any("does not occur" in e for e in validate_context_response(request, invented)))

    def test_utterance_groups_follow_open_sentences_and_short_pauses(self):
        groups = utterance_groups(self.segments)
        self.assertEqual(groups[1][0], groups[2][0])
        self.assertEqual(groups[2][1:], (2, 2))
        self.assertNotEqual(groups[3][0], groups[4][0])

    def test_join_short_pauses_keeps_source_spans(self):
        segs = [_seg(1, 1.0, 2.0, "Casi"), _seg(2, 2.2, 3.0, "casi me mata un perro."), _seg(3, 3.5, 4.0, "Menos mal")]
        joined, audit = join_short_pauses(segs, max_gap_sec=0.35, open_gap_sec=0.7, max_duration_sec=10, max_parts=3)
        self.assertEqual([s["spanish"] for s in joined], ["Casi casi me mata un perro.", "Menos mal"])
        self.assertEqual(len(joined[0]["source_cues"]), 2)
        self.assertEqual(audit[0]["kind"], "utterance_join")

    def test_quality_request_has_budget_context_and_legacy_request_is_unchanged(self):
        context = {"summary": "s", "speaker_register": "r", "glossary": [], "style_notes": []}
        request = quality_translation_request("j", self.segments, 80.0, self.cfg, context)
        row = request["segments"][0]
        self.assertEqual(row["target_syllables"], round(5.0 * 2.5))
        self.assertGreaterEqual(row["max_syllables"], row["target_syllables"])
        self.assertEqual(request["global_context"]["summary"], "s")
        self.assertEqual(len(request["segments"][2]["context_before"]), 2)
        legacy = translation_request("j", self.segments, 80.0)
        self.assertNotIn("global_context", legacy)
        self.assertEqual(set(legacy["segments"][0]), {"id", "start", "end", "safe_window_sec", "anchor_type", "spanish",
                                                       "context_before", "context_after", "uncertain_words", "notes"})


class ReviewTests(unittest.TestCase):
    def _request(self):
        return {"job_id": "j", "segments": [
            {"id": 1, "spanish": "Que se convierten", "duration_sec": 1.0, "target_syllables": 5, "max_syllables": 8},
            {"id": 2, "spanish": "Si estamos completamente llenos", "duration_sec": 2.0, "target_syllables": 10, "max_syllables": 14}]}

    def test_validation_requires_reason_and_changed_text(self):
        request = {"job_id": "j", "segments": [{"id": 1}]}
        base = {"schema": "aidub.review_response.v1", "job_id": "j", "translator": {"kind": "command"}}
        bad = dict(base, segments=[{"id": 1, "verdict": "revise", "english": "Same", "issues": []}])
        errors = validate_review_response(request, bad, {1: "Same"})
        self.assertTrue(any("unchanged" in e for e in errors))
        self.assertTrue(any("issue kind" in e for e in errors))
        ok = dict(base, segments=[{"id": 1, "verdict": "ok", "issues": [], "reason": ""}])
        self.assertEqual(validate_review_response(request, ok, {1: "Same"}), [])

    def test_bounded_rounds_back_translation_only_for_disputed_and_audit(self):
        calls = []

        def invoke(role, request, current):
            calls.append((role, [s["id"] for s in request["segments"]], request.get("round")))
            if role == "back_translation":
                return {"segments": [{"id": s["id"], "spanish": "Sí, tenemos la salud llena"} for s in request["segments"]]}
            if request["round"] == 1:
                return {"segments": [
                    {"id": 1, "verdict": "revise", "english": "and they transform.", "issues": ["fragment"], "reason": "dangling"},
                    {"id": 2, "verdict": "ok", "issues": [], "reason": "", "disputed": True}]}
            return {"segments": [{"id": s["id"], "verdict": "ok", "issues": [], "reason": ""} for s in request["segments"]]}

        cfg = {"translation_quality": {"enabled": True, "review": {"enabled": True, "max_rounds": 2}}}
        english, audit = run_review("j", self._request(), {1: "That turn into.", 2: "If we're full on health"}, invoke, cfg)
        self.assertEqual(english[1], "and they transform.")
        self.assertEqual([c[0] for c in calls], ["review", "back_translation", "review"])
        self.assertEqual(calls[1][1], [2])
        self.assertEqual(calls[2][1], [1, 2])
        self.assertEqual(audit["lines"]["1"]["status"], "revised_confirmed")
        self.assertEqual(audit["lines"]["2"]["status"], "accepted_draft")
        self.assertEqual(audit["lines"]["2"]["back_translations"][0]["spanish"], "Sí, tenemos la salud llena")

    def test_last_round_revision_is_marked_unconfirmed(self):
        def invoke(role, request, current):
            return {"segments": [{"id": s["id"], "verdict": "revise", "english": current[s["id"]] + "!",
                                  "issues": ["unnatural"], "reason": "tone"} for s in request["segments"]]}
        cfg = {"translation_quality": {"enabled": True, "review": {"enabled": True, "max_rounds": 1, "back_translation": "off"}}}
        _, audit = run_review("j", self._request(), {1: "a", 2: "b"}, invoke, cfg)
        self.assertEqual({v["status"] for v in audit["lines"].values()}, {"revised_unconfirmed"})


class ProviderAliasTests(unittest.TestCase):
    def test_explicit_alias_and_cycle(self):
        spec = {"kind": "command", "command": ["x"]}
        providers = {"repair": spec, "review": {"kind": "same_as", "role": "repair"}}
        self.assertIs(resolve_role(providers, "review"), spec)
        self.assertIsNone(resolve_role({"translation": spec}, "review"))
        with self.assertRaises(ProviderError):
            resolve_role({"a": {"kind": "same_as", "role": "b"}, "b": {"kind": "same_as", "role": "a"}}, "a")

    def test_preset_keeps_configured_providers_and_fixed_synthesis(self):
        cfg = load_config()
        cfg["providers"] = {"translation": {"kind": "command", "command": ["t"]}, "repair": {"kind": "command", "command": ["r"]}}
        merged = apply_preset(cfg, load_preset("quality"))
        self.assertEqual(merged["providers"]["translation"]["command"], ["t"])
        self.assertEqual(merged["providers"]["review"], {"kind": "same_as", "role": "repair"})
        self.assertEqual(merged["qwen3"], cfg["qwen3"])
        self.assertEqual(merged["schedule"], cfg["schedule"])
        self.assertEqual(merged["preset"], "quality")


class SecondPassTests(unittest.TestCase):
    def _mic(self, root):
        sr = 16000
        audio = np.zeros(sr * 10, dtype=np.float32)
        audio[int(5.0 * sr):int(5.6 * sr)] = 0.1 * np.sin(2 * np.pi * 150 * np.arange(int(0.6 * sr)) / sr)
        path = root / "mic.wav"
        sf.write(path, audio, sr)
        return path

    def test_duplicates_gaps_and_uncertain_cues(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mic = self._mic(root)
            built = {"segments": [
                _seg(1, 1.0, 2.0, "Espero que por acá"), _seg(2, 1.8, 2.1, "Espero que por acá"),
                _seg(3, 3.0, 3.5, "Vamos vamos"), _seg(4, 3.6, 4.0, "vamos vamos"),
                _seg(5, 7.0, 8.0, "Si estamos llenos", uncertain_words=[{"word": "Si", "probability": 0.2}]),
            ], "untranscribed_energy": [{"span": [5.0, 5.3]}, {"span": [5.35, 5.6]}, {"span": [9.0, 9.2]}, {"span": [9.7, 9.9]}],
                "corrections": []}

            def transcribe(path, options):
                self.assertFalse(options["condition_on_previous_text"])
                name = Path(path).stem
                def words(*items):
                    return {"segments": [{"no_speech_prob": 0.1, "words": [
                        {"word": w, "start": s, "end": e, "probability": p} for w, s, e, p in items]}]}
                if name == "dup_1_2":
                    return words(("Espero", 0.4, 0.6, .9), ("que", 0.6, 0.7, .9), ("por", 0.7, 0.8, .9), ("acá", 0.8, 1.0, .9))
                if name == "dup_3_4":
                    return words(("Vamos", .3, .5, .9), ("vamos", .5, .7, .9), ("vamos", .9, 1.1, .9), ("vamos", 1.1, 1.3, .9))
                if name == "cue_5":
                    return words(("Sí,", .4, .5, .8), ("estamos", .5, .9, .9), ("llenos", .9, 1.2, .9))
                if name == "gap_0000":
                    return words(("¡Ay,", .4, .6, .85), ("no!", .6, .9, .8))
                if name == "gap_0001":
                    return words(("mm", .3, .4, .2))
                return {"segments": []}

            cfg = {"asr_second_pass": {"enabled": True, "model": "turbo"}}
            out = run_second_pass(root, built, mic, 0.0, cfg, transcribe, mic_sha="x")
            texts = [s["spanish"] for s in out["segments"]]
            self.assertEqual(texts.count("Espero que por acá"), 1)
            self.assertIn("vamos vamos", texts)
            self.assertIn("¡Ay, no!", texts)
            self.assertEqual([s["id"] for s in out["segments"]], list(range(1, len(texts) + 1)))
            uncertain = next(s for s in out["segments"] if s["spanish"] == "Si estamos llenos")
            self.assertEqual(uncertain["asr_alternatives"][0]["text"], "Sí, estamos llenos")
            outcomes = [g["second_pass"]["outcome"] for g in out["untranscribed_energy"]]
            self.assertEqual(outcomes, ["recovered", "unintelligible", "non_speech_energy"])
            self.assertEqual(out["untranscribed_energy"][0].get("merged"), 2)
            audit = read_json(root / "transcribe/second_pass.json")
            self.assertIn("confirmed_repetition", [t.get("outcome") for t in audit["targets"]])

    def test_gap_overlapping_a_cue_does_not_duplicate_its_words(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mic = self._mic(root)
            built = {"segments": [_seg(1, 4.0, 5.3, "Y bien, se abren las puertas"), _seg(2, 8.0, 9.0, "Perfecto")],
                     "untranscribed_energy": [{"span": [5.1, 5.6]}, {"span": [7.0, 7.1]}], "corrections": []}

            def transcribe(path, options):
                lo = 4.75 if "0000" in path else 6.65
                return {"segments": [{"no_speech_prob": 0.05, "words": [
                    {"word": "puertas", "start": 5.0 - lo, "end": 5.25 - lo, "probability": 0.95},
                    {"word": "puertas.", "start": 5.35 - lo, "end": 5.55 - lo, "probability": 0.9}]}]}

            out = run_second_pass(root, built, mic, 0.0, {"asr_second_pass": {"enabled": True}}, transcribe)
            self.assertEqual([s["spanish"] for s in out["segments"]], ["Y bien, se abren las puertas", "Perfecto"])
            first = out["untranscribed_energy"][0]["second_pass"]
            self.assertEqual(first["outcome"], "already_transcribed")
            self.assertEqual(first["uncovered"], [[5.3, 5.6]])

    def test_low_confidence_gap_is_not_filled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mic = self._mic(root)
            built = {"segments": [_seg(1, 1.0, 2.0, "Hola")], "untranscribed_energy": [{"span": [5.0, 5.6]}], "corrections": []}
            transcribe = lambda path, options: {"segments": [{"no_speech_prob": 0.2, "words": [
                {"word": "vamos", "start": 0.4, "end": 0.8, "probability": 0.35}]}]}
            out = run_second_pass(root, built, mic, 0.0, {"asr_second_pass": {"enabled": True}}, transcribe)
            self.assertEqual([s["spanish"] for s in out["segments"]], ["Hola"])
            self.assertEqual(out["untranscribed_energy"][0]["second_pass"]["outcome"], "unintelligible")


class SelectionTests(unittest.TestCase):
    def _cfg(self, candidates=3, extra=2):
        return {"schedule": {"seed_base": 42}, "fit_retries": {"max_leading_shift_sec": 0.4},
                "voice_selection": {"enabled": True, "candidates": candidates, "max_extra_attempts": extra}}

    def _run(self, scores, ok, placed):
        seen = []

        def synthesize(text, seed):
            seen.append(seed)
            return {"seed": seed}

        def assess(meta, text):
            k = (meta["seed"] - 43) // 1000
            return {"ok": ok[k], "reasons": [] if ok[k] else ["truncated_speech"]}

        def attempt_fn(seg, text, seed, kind, meta, occ, nxt, dur):
            k = (seed - 43) // 1000
            return {"seed": seed, "kind": kind, "placed": placed[k], "status": "fit_unchanged" if placed[k] else "unresolved",
                    "tempo": 1.0, "generated_duration_sec": 1.0, "trim_duration_sec": 1.0, "timing_error": ""}

        def score(attempt):
            return {"score": scores[(attempt["seed"] - 43) // 1000]}

        seg = {"id": 1, "english": "Let's see if I can use the shotgun", "start": 10.0, "end": 11.0, "revisions": []}
        opts = selection_settings(self._cfg())
        result = collect_line_best_of_n(seg, occupied=0, next_start=12, source_duration=20, cfg=self._cfg(),
                                        synthesize=synthesize, assess=assess, attempt_fn=attempt_fn, revision_limit_n=2,
                                        score=score, candidates=opts["candidates"], max_extra=opts["max_extra_attempts"])
        return result, seen

    def test_scores_every_valid_take_not_first_pass(self):
        result, seen = self._run([0.9, 0.2, 0.5], [True, True, True], [True, True, True])
        self.assertEqual(len(seen), 3)
        self.assertEqual(result["chosen"]["seed"], 43 + 1000)
        self.assertEqual(result["chosen"]["selection_summary"]["valid"], 3)

    def test_extra_attempts_replace_failures_and_stay_bounded(self):
        result, seen = self._run([0.1, 0.3, 0.2, 0.4, 0.5], [False, True, False, True, False], [True] * 5)
        self.assertEqual(len(seen), 5)
        self.assertEqual(result["chosen"]["selection_summary"]["valid"], 2)
        self.assertEqual(result["chosen"]["seed"], 43 + 1000)

    def test_placeable_take_beats_a_better_unplaceable_one(self):
        result, _ = self._run([0.1, 0.8, 0.9], [True, True, True], [False, True, True])
        self.assertEqual(result["chosen"]["seed"], 43 + 1000)
        self.assertEqual(choose([{"selection": {"score": 1}, "placed": False, "seed": 1}])["seed"], 1)

    def test_pathological_pause_and_rate(self):
        sr = 16000
        tone = 0.1 * np.sin(2 * np.pi * 140 * np.arange(int(0.5 * sr)) / sr).astype(np.float32)
        wav = np.concatenate([tone, np.zeros(int(1.3 * sr), dtype=np.float32), tone])
        info = pacing(wav, sr, "We are inside the church now")
        self.assertGreater(info["longest_pause_sec"], 1.2)
        self.assertIn("pathological_pause", pacing_issues(info, {}))


class PresentationTests(unittest.TestCase):
    def test_adaptive_margin_keeps_soft_decay(self):
        sr = 24000
        core = 0.2 * np.sin(2 * np.pi * 150 * np.arange(sr) / sr)
        decay = 0.004 * np.sin(2 * np.pi * 3000 * np.arange(int(0.15 * sr)) / sr)
        wav = np.concatenate([np.zeros(sr // 10), core, decay, np.zeros(sr // 5)]).astype(np.float32)
        bounds = speech_bounds(wav, sr, 0.005)
        lead, tail, info = adaptive_margins(wav, sr, bounds, base_lead_ms=20, base_tail_ms=60, floor_rms=0.0015,
                                            max_lead_ms=80, max_tail_ms=200)
        self.assertEqual(lead, 20)
        self.assertGreater(tail, 140)
        self.assertGreater(info["tail_extension_ms"], 80)

    def test_tempo_take_gets_same_margins_and_gain_as_other_takes(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg unavailable")
        from aidub.pipeline import _apply_presentation
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "schedule/work").mkdir(parents=True)
            sr = 24000
            wav = np.concatenate([np.zeros(sr // 10), 0.05 * np.sin(2 * np.pi * 150 * np.arange(sr) / sr),
                                  np.zeros(sr // 10)]).astype(np.float32)
            raw = root / "raw.wav"
            sf.write(raw, wav, sr, subtype="FLOAT")
            job = type("J", (), {"dir": root})()
            cfg = {"executables": {"ffmpeg": shutil.which("ffmpeg")}, "schedule": {"trim_rms": 0.005},
                   "voice_edge": {"enabled": True, "margin_lead_ms": 20, "margin_tail_ms": 60, "fade_ms": 12}}
            chosen = {"placed": True, "tempo": 1.08, "raw_path": str(raw), "used_path": str(raw), "trim_duration_sec": 1.0}
            seg = {"id": 1, "start": 5.0}
            legacy = _apply_presentation(job, cfg, seg, dict(chosen), 4.0, 6.5, 30.0, 0.1)
            self.assertIsNone(legacy.get("loudness_gain"))
            cfg["voice_edge"]["presentation_version"] = 2
            unified = _apply_presentation(job, cfg, seg, dict(chosen), 4.0, 6.5, 30.0, 0.1)
            self.assertGreater(unified["loudness_gain"], 1.5)
            self.assertEqual(unified["presentation"]["version"], 2)
            self.assertGreater(unified["edge"]["lead_ms_used"], 15)
            self.assertLess(unified["placement_start"], 5.0)
            self.assertTrue(unified["edge_ok"])
            self.assertLessEqual(unified["placement_start"] + unified["generated_duration_sec"], 6.5 + 1e-3)
            same = _apply_presentation(job, cfg, seg, dict(chosen, tempo=1.0), 4.0, 6.5, 30.0, 0.1)
            self.assertAlmostEqual(same["loudness_gain"], unified["loudness_gain"], places=3)

    def test_source_loudness_is_bounded_and_relative(self):
        from aidub.pipeline import source_loudness
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "extract").mkdir()
            (root / "schedule").mkdir()
            sr = 16000
            t = np.arange(sr) / sr
            mic = np.concatenate([0.02 * np.sin(2 * np.pi * 150 * t), 0.08 * np.sin(2 * np.pi * 150 * t),
                                  0.5 * np.sin(2 * np.pi * 150 * t), np.zeros(sr)]).astype(np.float32)
            sf.write(root / "extract/mic_raw.wav", mic, sr)
            (root / "extract/alignment.json").write_text(json.dumps({"offset_sec": 0.0}))
            job = type("J", (), {"dir": root})()
            cfg = {"segmentation": {"energy_rms": 0.005}, "voice_edge": {"source_loudness": {"enabled": True, "slope": 0.5, "max_db": 3.0}}}
            out = source_loudness(job, cfg, [_seg(1, 0, 1, "a"), _seg(2, 1, 2, "b"), _seg(3, 2, 3, "c"), _seg(4, 3, 4, "d")])
            self.assertEqual(out[2]["expressive_db"], 0.0)
            self.assertEqual(out[1]["expressive_db"], -3.0)
            self.assertEqual(out[3]["expressive_db"], 3.0)
            self.assertNotIn(4, out)


class QualityEndToEndTests(unittest.TestCase):
    def test_quality_preset_auto_with_fake_models_and_provider(self):
        from aidub.audio import metrics
        from aidub.unattended import run_unattended
        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg unavailable")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sr = 48000
            t = np.arange(3 * sr) / sr
            bed = np.stack([0.02 * np.sin(2 * np.pi * 220 * t)] * 2, axis=1).astype("float32")
            mic = np.zeros_like(bed)
            for lo, hi in [(0.2, 0.5), (0.7, 1.0)]:
                a, b = int(lo * sr), int(hi * sr)
                mic[a:b] = np.stack([.2 * np.sin(2 * np.pi * 130 * t[a:b])] * 2, axis=1)
            for name, audio in [("mixed", bed + mic), ("game", bed), ("mic", mic)]:
                sf.write(root / (name + ".wav"), audio, sr)
            source = root / "source.mkv"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=64x64:r=30:d=3",
                            "-i", str(root / "mixed.wav"), "-i", str(root / "game.wav"), "-i", str(root / "mic.wav"),
                            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a", "-c:v", "libx264", "-c:a", "pcm_s16le",
                            str(source)], check=True, capture_output=True, timeout=30)
            cfg = load_config()
            cfg["jobs_dir"] = str(root / "jobs")
            cfg["export"] = {"container": "mkv"}
            cfg["models"] = {"whisper_path": str(root / "weights.pt")}
            (root / "weights.pt").touch()
            cfg["reference"]["wav"] = str(root / "reference.wav")
            sf.write(root / "reference.wav", .1 * np.sin(2 * np.pi * 130 * t), sr)
            helper = root / "provider.py"
            calls = root / "calls"
            helper.write_text(
                "import json,sys\n"
                "req=json.load(open(sys.argv[1]));role=sys.argv[3]\n"
                "open(sys.argv[4],'a').write(role+'\\n')\n"
                "base={'schema':'aidub.'+role+'_response.v1','job_id':req['job_id'],'translator':{'kind':'command'}}\n"
                "if role=='context':\n"
                "  base.update(summary='Greeting.',speaker_register='casual',glossary=[{'spanish':'Amigo','english':'buddy','kind':'slang'}],style_notes=[])\n"
                "elif role=='review':\n"
                "  base['segments']=[dict(id=s['id'],verdict='revise',english='Hello, buddy',issues=['terminology'],reason='glossary') if req['round']==1 else dict(id=s['id'],verdict='ok',issues=[],reason='') for s in req['segments']]\n"
                "else:\n"
                "  base['segments']=[dict(id=s['id'],english='Hello there') for s in req['segments']]\n"
                "json.dump(base,open(sys.argv[2],'w'))\n")
            spec = {"kind": "command", "command": [sys.executable, str(helper), "{request}", "{response}", "{role}", str(calls)]}
            cfg["providers"] = {"translation": spec, "repair": spec}
            cfg["processing"] = {"block_frames": 1024}
            synth = []

            class FakeBackend:
                def synthesize(self, text, reference_audio, reference_text, path, seed):
                    synth.append((text, seed))
                    n = int(1.0 * sr)
                    signal = np.zeros(n + int(.06 * sr), dtype="float32")
                    signal[int(.03 * sr):int(.03 * sr) + n] = .1 * np.sin(2 * np.pi * 130 * np.arange(n) / sr)
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    sf.write(path, signal, sr, subtype="FLOAT")
                    return dict(path=path, text=text, seed=seed, sample_rate=sr, duration_sec=len(signal) / sr,
                                cache_hit=False, **metrics(signal))

            class FakeClient:
                def __init__(self, *a, **kw):
                    pass

                def transcribe(self, path, **kw):
                    return {"text": "", "segments": [
                        {"start": .2, "end": .5, "text": "Hola", "no_speech_prob": .1,
                         "words": [{"word": "Hola", "start": .2, "end": .5, "probability": .9}]},
                        {"start": .7, "end": 1.0, "text": "Amigo", "no_speech_prob": .1,
                         "words": [{"word": "Amigo", "start": .7, "end": 1.0, "probability": .9}]}]}

                def start(self):
                    pass

                def close(self):
                    pass

            heard = lambda assessor, path, second=False: {"text": read_json(Path(path).with_suffix(".json"))["text"],
                                                          "language": "en", "mean_probability": .9}
            with patch("aidub.cli.preflight"), patch("aidub.unattended.require_synthesis_ready"), \
                 patch("aidub.transcription.AsrClient", FakeClient), patch("aidub.pipeline.AsrClient", FakeClient), \
                 patch("aidub.pipeline._LineAssessor._transcribe", heard), \
                 patch("aidub.verification._whisper_version", return_value="fake"), \
                 patch("aidub.pipeline.get_shared_backend", return_value=FakeBackend()), \
                 patch("aidub.pipeline.shared_backend_loaded", return_value=False):
                code = run_unattended(cfg, str(source), "quality", preset="quality")
                self.assertEqual(code, 0)
                roles = calls.read_text().split()
                self.assertEqual(roles, ["context", "translation", "review", "review"])
                self.assertEqual(run_unattended(cfg, str(source), "quality", preset="quality"), 0)
                self.assertEqual(calls.read_text().split(), roles)
            job = root / "jobs/quality"
            timeline = read_json(job / "timeline.json")["segments"]
            self.assertEqual([s["spanish"] for s in timeline], ["Hola Amigo"])
            self.assertEqual(timeline[0]["english"], "Hello, buddy")
            self.assertEqual(timeline[0]["translation_review"]["status"], "revised_confirmed")
            self.assertEqual(len({seed for _, seed in synth}), 4)
            summary = read_json(job / "mix/placed_summary.json")
            self.assertEqual(summary["segments"][0]["selection_summary"]["valid"], 4)
            self.assertEqual(summary["segments"][0]["presentation"]["version"], 2)
            report = read_json(job / "report/validation.json")
            names = {c["name"]: c["status"] for c in report["checks"]}
            self.assertEqual(names["translation_reviewed"], "passed")
            self.assertEqual(names["presentation_consistent"], "passed")
            self.assertTrue((job / "report/risk.md").is_file())
            self.assertTrue((job / "handoff/context/context.json").is_file())
            audit = read_json(job / "handoff/translation_audit.json")
            self.assertEqual(audit["lines"]["1"]["draft"], "Hello there")
            self.assertEqual(read_json(job / "config.json")["preset"], "quality")


if __name__ == "__main__":
    unittest.main()
