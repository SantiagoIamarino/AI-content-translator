import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from aidub.audio import mix_game_and_voice, render_voice_with_margins, safety_fade
from aidub.handoff import translation_request
from aidub.ledger import cached_candidate, checkpoint_matches, write_checkpoint, read_checkpoint
from aidub.linework import account_lines, collect_line, leading_shift, quality_seed_sequence
from aidub.providers import ProviderError, invoke_checked, require_provider
from aidub.quality import assess_waveform, speaker_disagreements, speaker_profile
from aidub.segment import build_segments, review_low_energy


def _tone(f0, sr, seconds, rolloff):
    n = int(sr * seconds)
    t = np.arange(n, dtype=np.float32) / sr
    y = np.zeros(n, dtype=np.float32)
    for k in range(1, 16):
        y += (k ** -rolloff) * np.sin(2 * np.pi * f0 * k * t)
    peak = float(np.max(np.abs(y))) + 1e-9
    return (y / peak * 0.2).astype(np.float32)


def _cfg():
    return {
        "schedule": {"seed_base": 42, "alternate_seed_offset": 100, "max_tempo": 1.1},
        "quality": {"max_retries": 2, "min_speaker_features": 2},
        "fit_retries": {"max_alternate_seeds": 3, "max_leading_shift_sec": 0.4},
        "reference": {"id": "B"},
    }


class SpeakerTests(unittest.TestCase):
    def test_female_shotgun_profile_needs_two_features(self):
        reference = {"f0": 130.0, "centroid": 1350.0, "tilt": 0.35}
        one_feature = {"f0": 220.0, "centroid": 1350.0, "tilt": 0.35}
        flags = speaker_disagreements(one_feature, reference, 1.2)
        self.assertEqual(flags, ["f0"])
        self.assertLess(len(flags), 2)
        shotgun = {"f0": 210.0, "centroid": 2840.0, "tilt": 1.5}
        flags = speaker_disagreements(shotgun, reference, 1.2)
        self.assertGreaterEqual(len(flags), 2)
        self.assertIn("centroid", flags)

    def test_short_phrase_ignores_f0_alone(self):
        reference = {"f0": 130.0, "centroid": 1350.0, "tilt": 0.35}
        short = {"f0": 240.0, "centroid": 1350.0, "tilt": 0.35}
        self.assertEqual(speaker_disagreements(short, reference, 0.3), [])

    def test_waveform_rejects_bright_voice_and_keeps_a_close_one(self):
        sr = 16000
        male = _tone(130, sr, 1.2, 1.8)
        from aidub.quality import speaker_profile

        reference = speaker_profile(male, sr)
        close = _tone(125, sr, 1.2, 1.8)
        bright = _tone(220, sr, 1.2, 0.55)
        self.assertTrue(assess_waveform(close, sr, reference)["ok"])
        rejected = assess_waveform(bright, sr, reference)
        self.assertFalse(rejected["ok"])
        self.assertIn("wrong_speaker", rejected["reasons"])
        self.assertIn("f0", rejected["speaker_features_disagreed"])
        self.assertIn("centroid", rejected["speaker_features_disagreed"])

    def test_recorded_shotgun_blast_when_present(self):
        ref_path = Path("/home/siamarino/audios/04_referencia_ingles_emocion.wav")
        cache = Path("/home/siamarino/ai-dubbing-e2e-Deepseek/jobs/deepseek_90s/cache/synth")
        if not ref_path.is_file() or not cache.is_dir():
            self.skipTest("reference or Deepseek cache is not on this machine")
        import soundfile as sf
        from aidub.audio import to_mono

        ref, sr = sf.read(ref_path, dtype="float32", always_2d=False)
        reference = speaker_profile(to_mono(ref), sr)
        seen = False
        for meta_path in cache.glob("*.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("text") not in {"Shotgun blast", "Shotgun blast."} or int(meta.get("seed", -1)) != 49:
                continue
            wav, wav_sr = sf.read(meta_path.with_suffix(".wav"), dtype="float32", always_2d=False)
            result = assess_waveform(to_mono(wav), wav_sr, reference)
            self.assertIn("wrong_speaker", result["reasons"])
            self.assertIn("f0", result["speaker_features_disagreed"])
            self.assertIn("centroid", result["speaker_features_disagreed"])
            seen = True
        if not seen:
            self.skipTest("Deepseek shotgun seed 49 was not in the cache")


class RetryTests(unittest.TestCase):
    def test_quality_retries_are_bounded_to_one_line(self):
        calls = []

        def synthesize(text, seed):
            calls.append((text, seed))
            return {"path": "mem", "seed": seed, "duration_sec": 1.0}

        def assess(meta, text):
            ok = int(meta["seed"]) == 43 + 2000
            return {"ok": ok, "reasons": [] if ok else ["wrong_speaker"]}

        def attempt_fn(seg, text, seed, kind, meta, occupied, nxt, source_duration):
            return {
                "placed": True,
                "trim_duration_sec": 1.0,
                "generated_duration_sec": 1.0,
                "status": "fit_unchanged",
                "timing_error": "",
                "text": text,
                "seed": seed,
                "kind": kind,
                "safe_window_sec": nxt - seg["start"],
                "cache_hit": False,
                "raw_path": "mem",
                "raw_duration_sec": 1.0,
            }

        seg = {"id": 1, "start": 0.0, "end": 1.0, "english": "Shotgun blast", "spanish": "Escopetazo", "revisions": []}
        result = collect_line(
            seg, occupied=0.0, next_start=3.0, source_duration=10.0, cfg=_cfg(),
            synthesize=synthesize, assess=assess, attempt_fn=attempt_fn, revision_limit_n=1,
        )
        self.assertTrue(result["chosen"]["placed"])
        self.assertEqual([seed for _, seed in calls], quality_seed_sequence(43, 2))
        self.assertTrue(all(text == "Shotgun blast" for text, _ in calls))
        self.assertEqual(len(calls), 3)

    def test_failed_quality_does_not_spend_extra_fit_seeds(self):
        calls = []
        cfg = _cfg()
        cfg["quality"]["max_retries"] = 1

        def synthesize(text, seed):
            calls.append(seed)
            return {"seed": seed}

        def assess(meta, text):
            return {"ok": False, "reasons": ["wrong_speaker"]}

        def attempt_fn(seg, text, seed, kind, meta, occupied, nxt, source_duration):
            return {
                "placed": True, "trim_duration_sec": 1, "generated_duration_sec": 1,
                "status": "fit_unchanged", "timing_error": "", "text": text, "seed": seed,
                "kind": kind, "safe_window_sec": 2, "cache_hit": False, "raw_path": "x",
                "raw_duration_sec": 1, "quality": {},
            }

        seg = {"id": 7, "start": 1.0, "end": 2.0, "english": "Shotgun blast", "spanish": "Escopetazo", "revisions": []}
        result = collect_line(
            seg, occupied=0.0, next_start=4.0, source_duration=10.0, cfg=cfg,
            synthesize=synthesize, assess=assess, attempt_fn=attempt_fn, revision_limit_n=1,
        )
        self.assertFalse(result["chosen"]["placed"])
        self.assertFalse(result["needs_repair"])
        self.assertEqual(calls, [49, 1049])
        self.assertTrue(result["chosen"]["timing_error"].startswith("quality_rejected:"))

    def test_fit_seeds_and_leading_silence_do_not_move_the_next_line(self):
        later = {"id": 2, "start": 6.0, "end": 7.0, "english": "Next", "spanish": "Siguiente", "revisions": []}
        self.assertAlmostEqual(leading_shift(5.0, 1.3, 4.0, later["start"], 0.4), 0.3, places=6)
        cfg = _cfg()
        cfg["quality"]["max_retries"] = 0
        cfg["fit_retries"]["max_alternate_seeds"] = 2
        calls = []

        def synthesize(text, seed):
            calls.append(seed)
            return {"seed": seed}

        def assess(meta, text):
            return {"ok": True, "reasons": []}

        def attempt_fn(seg, text, seed, kind, meta, occupied, nxt, source_duration):
            return {
                "placed": False, "trim_duration_sec": 1.3, "generated_duration_sec": 1.3,
                "status": "unresolved", "timing_error": "overrun_tempo_limit", "text": text,
                "seed": seed, "kind": kind, "safe_window_sec": nxt - seg["start"],
                "cache_hit": False, "raw_path": "x", "raw_duration_sec": 1.4,
            }

        seg = {"id": 1, "start": 5.0, "end": 5.4, "english": "Too long", "spanish": "Largo", "revisions": []}
        result = collect_line(
            seg, occupied=4.0, next_start=later["start"], source_duration=10.0, cfg=cfg,
            synthesize=synthesize, assess=assess, attempt_fn=attempt_fn, revision_limit_n=1,
        )
        self.assertEqual(later["start"], 6.0)
        self.assertEqual(calls, [43, 143, 243])
        self.assertEqual(result["chosen"]["status"], "spill_into_leading_silence")
        self.assertLess(result["chosen"]["placement_start"], seg["start"])
        self.assertLessEqual(result["chosen"]["placement_start"] + result["chosen"]["generated_duration_sec"], later["start"] + 1e-4)
        self.assertEqual(account_lines([1, 2], [1], []), [2])


class EdgeTests(unittest.TestCase):
    def test_margin_fade_does_not_attenuate_the_core_or_the_game(self):
        sr = 16000
        wav = np.zeros(sr, dtype=np.float32)
        wav[8000:10000] = 0.5
        piece, info = render_voice_with_margins(wav, sr, lead_ms=20, tail_ms=30, fade_ms=12, target_rms=None)
        self.assertGreater(info["lead_ms_used"], 0)
        self.assertLess(abs(float(piece[0])), 0.05)
        core = piece[info["core_lo"]:info["core_hi"]]
        self.assertGreater(float(np.max(np.abs(core))), 0.45)
        game = np.full((8, 2), 0.2, dtype=np.float32)
        before = game.copy()
        voice = np.zeros(8, dtype=np.float32)
        voice[2:5] = 0.1
        mixed, _ = mix_game_and_voice(game, voice, 0.99)
        self.assertTrue(np.array_equal(game, before))
        silent = np.where(np.abs(voice) < 1e-8)[0]
        self.assertTrue(np.allclose(mixed[silent], game[silent]))

    def test_safety_fade_keeps_a_hot_consonant(self):
        sr = 16000
        wav = np.zeros(sr // 10, dtype=np.float32)
        wav[20] = 0.8
        faded, _ = safety_fade(wav, sr, fade_ms=8, guard=0.2)
        self.assertAlmostEqual(float(faded[20]), 0.8, places=5)


class SegmentReviewTests(unittest.TestCase):
    def _cfg(self):
        return {
            "energy_rms": 0.005,
            "energy_window_sec": 0.01,
            "onset_lookback_sec": 0.05,
            "end_tail_sec": 0.05,
            "merge_max_silence_sec": 0.12,
            "min_voiced_sec": 0.04,
            "uncertain_probability": 0.5,
        }

    def test_borderline_harmonic_is_kept_and_hallucination_is_not(self):
        sr = 16000
        n = sr
        wav = np.zeros((n, 1), dtype=np.float32)
        t = np.arange(int(0.4 * sr)) / sr
        quiet = (0.00424 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
        wav[int(0.2 * sr):int(0.2 * sr) + quiet.size, 0] = quiet
        whisper = {"segments": [{
            "start": 0.2, "end": 0.6, "text": " puerta",
            "words": [{"word": " puerta", "start": 0.2, "end": 0.6, "probability": 0.9}],
        }]}
        built = build_segments(whisper, wav, sr, self._cfg())
        self.assertEqual(len(built["segments"]), 1)
        self.assertIn("energy review", built["segments"][0]["notes"])
        noise = np.zeros((n, 1), dtype=np.float32)
        rng = np.random.default_rng(0)
        noise[int(0.2 * sr):int(0.6 * sr), 0] = rng.normal(0, 0.004, int(0.4 * sr)).astype(np.float32)
        dropped = build_segments(whisper, noise, sr, self._cfg())
        self.assertEqual(dropped["segments"], [])
        hall = {"segments": [{
            "start": 0.2, "end": 0.6, "text": " Gracias por ver el video",
            "words": [
                {"word": " Gracias", "start": 0.2, "end": 0.3, "probability": 0.9},
                {"word": " por", "start": 0.3, "end": 0.4, "probability": 0.9},
                {"word": " ver", "start": 0.4, "end": 0.5, "probability": 0.9},
                {"word": " el", "start": 0.5, "end": 0.55, "probability": 0.9},
                {"word": " video", "start": 0.55, "end": 0.6, "probability": 0.9},
            ],
        }]}
        hall_built = build_segments(hall, wav, sr, self._cfg())
        self.assertEqual(hall_built["segments"], [])
        self.assertEqual(review_low_energy("Gracias por ver el video", quiet, sr, 0.005)[0], False)


class ProviderTests(unittest.TestCase):
    def test_unconfigured_names_the_required_shape(self):
        with self.assertRaises(ProviderError) as ctx:
            require_provider({"kind": "unconfigured"}, "translation")
        self.assertIn("api_key_env", str(ctx.exception))
        self.assertIn("AIDUB_TRANSLATION_API_KEY", str(ctx.exception))

    def test_openai_missing_key_does_not_invent_one(self):
        from aidub.providers import invoke_provider

        with tempfile.TemporaryDirectory() as td:
            request = Path(td) / "request.json"
            request.write_text("{}", encoding="utf-8")
            with self.assertRaises(ProviderError) as ctx:
                invoke_provider(
                    {"kind": "openai_compatible", "base_url": "http://127.0.0.1:9/v1", "model": "m", "api_key_env": "AIDUB_TEST_MISSING_KEY"},
                    request,
                    Path(td) / "response.json",
                    "translation",
                )
        self.assertIn("AIDUB_TEST_MISSING_KEY", str(ctx.exception))
        self.assertNotIn("sk-", str(ctx.exception))

    def test_command_provider_is_validated(self):
        request = translation_request("job", [
            {"id": 1, "start": 0.0, "end": 1.0, "spanish": "Hola", "anchor_type": "utterance", "notes": "", "uncertain_words": []},
        ], 3.0)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            req = root / "request.json"
            res = root / "response.json"
            req.write_text(json.dumps(request), encoding="utf-8")
            script = root / "ok.py"
            script.write_text(
                "import json,sys\n"
                "req=json.load(open(sys.argv[1]))\n"
                "json.dump({'schema':'aidub.translation_response.v1','job_id':req['job_id'],"
                "'translator':{'kind':'command'},'segments':[{'id':s['id'],'english':'Hello'} for s in req['segments']]}, open(sys.argv[2],'w'))\n",
                encoding="utf-8",
            )
            data = invoke_checked(
                {"kind": "command", "command": [sys.executable, str(script), "{request}", "{response}"]},
                req, res, "translation",
            )
            self.assertEqual(data["segments"][0]["english"], "Hello")
            bad = root / "bad.py"
            bad.write_text("import json,sys\njson.dump({'schema':'aidub.translation_response.v1','job_id':'job','translator':{'kind':'command'},'segments':[]}, open(sys.argv[2],'w'))\n", encoding="utf-8")
            with self.assertRaises(ProviderError):
                invoke_checked(
                    {"kind": "command", "command": [sys.executable, str(bad), "{request}", "{response}"]},
                    req, root / "bad.json", "translation",
                )


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_matches_text_and_reference_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wav = root / "line.wav"
            wav.write_bytes(b"RIFF")
            record = {
                "english": "Shotgun blast",
                "reference_sha256": "abc",
                "candidates": [{"text": "Shotgun blast", "seed": 49, "wav": str(wav), "quality": {"ok": True, "reasons": []}}],
            }
            write_checkpoint(root, 7, record)
            loaded = read_checkpoint(root, 7)
            self.assertTrue(checkpoint_matches(loaded, "Shotgun blast", "abc"))
            self.assertFalse(checkpoint_matches(loaded, "Shotgun blast.", "abc"))
            self.assertIsNotNone(cached_candidate(loaded, "Shotgun blast", 49))
            self.assertIsNone(cached_candidate(loaded, "Shotgun blast", 50))


if __name__ == "__main__":
    unittest.main()
