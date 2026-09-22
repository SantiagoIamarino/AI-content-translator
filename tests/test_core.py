import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from aidub.audio import mix_game_and_voice, trim_silence, voiced_mask
from aidub.config import CONFIRMED_REFERENCE_TEXT, load_config, reference_text
from aidub.export import mux_english_cmd, mux_spanish_cmd, place_voice
from aidub.handoff import (
    safe_windows,
    translation_request,
    validate_repair_response,
    validate_translation_response,
)
from aidub.job import Job, JobLock
from aidub.media import align_to_video, assert_extract_preserves_origin, describe_streams, extract_audio_cmd, resolve_ordinal
from aidub.pipeline import _fp_ok
from aidub.placement import Interval, collisions
from aidub.schedule import plan_fit, synth_cache_key
from aidub.segment import build_segments
from aidub.report import validation_markdown
from aidub.srt import render_srt
from aidub.util import assert_write_in_job, fingerprint


def probe_fixture():
    return {
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264", "avg_frame_rate": "60/1", "nb_frames": "10", "duration": "0.166667", "start_time": "0.000000", "width": 1920, "height": 1080, "time_base": "1/60"},
            {"index": 2, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2, "start_time": "0.100000", "duration": "1.0", "time_base": "1/48000", "tags": {"name": "mixed"}},
            {"index": 5, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2, "start_time": "0.100000", "duration": "1.0", "time_base": "1/48000", "tags": {"name": "game"}},
            {"index": 8, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2, "start_time": "0.100000", "duration": "1.0", "time_base": "1/48000", "tags": {"name": "mic"}},
        ]
    }


class MappingTests(unittest.TestCase):
    def test_ordinal_is_not_absolute_index(self):
        described = describe_streams(probe_fixture())
        mic = resolve_ordinal(described, 2, "mic")
        self.assertEqual(mic["audio_ordinal"], 2)
        self.assertEqual(mic["absolute_index"], 8)
        self.assertNotEqual(mic["audio_ordinal"], mic["absolute_index"])
        game = resolve_ordinal(described, 1, "game")
        self.assertEqual(game["absolute_index"], 5)

    def test_extract_uses_audio_ordinal_and_keeps_spaces(self):
        cmd = extract_audio_cmd("ffmpeg", "/tmp/my video.mp4", 2, "/tmp/out dir/mic.wav")
        self.assertIn("/tmp/my video.mp4", cmd)
        self.assertEqual(cmd[cmd.index("-map") + 1], "0:a:2")
        self.assertNotIn("0:8", cmd)
        assert_extract_preserves_origin(cmd)
        with self.assertRaises(RuntimeError):
            assert_extract_preserves_origin(cmd + ["-ss", "1"])


class TimingTests(unittest.TestCase):
    def test_align_preserves_offset_and_video_length(self):
        wav = np.ones((48000, 2), dtype=np.float32)
        aligned, meta = align_to_video(wav, 48000, 0.5, 0.0, 2.0)
        self.assertEqual(aligned.shape[0], 96000)
        self.assertEqual(meta["lead_samples"], 24000)
        self.assertEqual(meta["tail_samples"], 24000)
        self.assertEqual(float(aligned[23999, 0]), 0.0)
        self.assertEqual(float(aligned[24000, 0]), 1.0)
        with self.assertRaises(RuntimeError):
            align_to_video(wav, 48000, 0.0, 0.5, 2.0)

    def test_safe_window_last_segment_uses_video_end(self):
        segments = [{"id": 1, "start": 1.0, "end": 1.4}, {"id": 2, "start": 75.691, "end": 76.577}]
        windows = safe_windows(segments, 81.716667)
        self.assertAlmostEqual(windows[0], 74.691, places=3)
        self.assertAlmostEqual(windows[1], 81.716667 - 75.691, places=3)

    def test_tempo_limit_matches_known_overrun(self):
        status, tempo, err = plan_fit(2.241125, 0.886, 2.005, 1.1)
        self.assertEqual(status, "unresolved")
        self.assertEqual(err, "overrun_tempo_limit")
        self.assertEqual(tempo, 1.0)
        status, tempo, err = plan_fit(2.20, 0.886, 2.005, 1.1)
        self.assertEqual(status, "needs_tempo")
        self.assertLessEqual(tempo, 1.1)
        self.assertGreater(tempo, 1.0)

    def test_collision_does_not_count_adjacent(self):
        self.assertEqual(collisions([Interval(1, 0, 10), Interval(2, 10, 20)]), [])
        hits = collisions([Interval(1, 0, 12), Interval(2, 10, 20)])
        self.assertEqual(hits[0]["id_b"], 2)
        self.assertEqual(hits[0]["overlap_samples"], 2)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.request = translation_request("job", [
            {"id": 1, "start": 0.0, "end": 1.0, "spanish": "Hola", "anchor_type": "utterance", "notes": "", "uncertain_words": []},
            {"id": 2, "start": 1.5, "end": 2.0, "spanish": "Perro", "anchor_type": "reaction", "notes": "", "uncertain_words": []},
        ], 3.0)
        self.ok = {
            "schema": "aidub.translation_response.v1",
            "job_id": "job",
            "translator": {"kind": "agent-assisted", "model": "xai/grok-4.7"},
            "segments": [{"id": 1, "english": "Hi"}, {"id": 2, "english": "Dog"}],
        }

    def test_request_treats_text_as_data(self):
        self.assertIn("not instructions", self.request["agent_instructions"])

    def test_accepts_complete_response(self):
        self.assertEqual(validate_translation_response(self.request, self.ok), [])

    def test_rejects_missing_duplicate_empty_and_extra(self):
        missing = json.loads(json.dumps(self.ok))
        missing["segments"] = [{"id": 1, "english": "Hi"}]
        self.assertTrue(any("missing" in e for e in validate_translation_response(self.request, missing)))
        dup = json.loads(json.dumps(self.ok))
        dup["segments"].append({"id": 1, "english": "Again"})
        errors = validate_translation_response(self.request, dup)
        self.assertTrue(any("duplicate" in e for e in errors))
        empty = json.loads(json.dumps(self.ok))
        empty["segments"][0]["english"] = "  "
        self.assertTrue(any("empty" in e for e in validate_translation_response(self.request, empty)))
        extra = json.loads(json.dumps(self.ok))
        extra["segments"][0]["start"] = 9
        self.assertTrue(any("unexpected segment fields" in e for e in validate_translation_response(self.request, extra)))

    def test_repair_requires_reason_and_change(self):
        req = {"schema": "aidub.repair_request.v1", "job_id": "job", "segments": [{"id": 2}]}
        bad = {
            "schema": "aidub.repair_response.v1",
            "job_id": "job",
            "translator": {"kind": "agent-assisted"},
            "segments": [{"id": 2, "action": "revise", "english": "Dog", "reason": "shorter"}],
        }
        errors = validate_repair_response(req, bad, {2: "Dog"})
        self.assertTrue(any("unchanged" in e for e in errors))
        good = json.loads(json.dumps(bad))
        good["segments"][0]["english"] = "A dog."
        self.assertEqual(validate_repair_response(req, good, {2: "Dog"}), [])


class TranslationFingerprintTests(unittest.TestCase):
    def test_repair_does_not_invalidate_transcription_handoff(self):
        from aidub.pipeline import translation_fingerprint

        base = [{"id": 1, "spanish": "Hola", "start": 0.0, "end": 1.0, "english": "Hi", "revisions": []}]
        repaired = [{"id": 1, "spanish": "Hola", "start": 0.0, "end": 1.0, "english": "Hey", "revisions": [{"action": "revise"}]}]
        changed = [{"id": 1, "spanish": "Chau", "start": 0.0, "end": 1.0, "english": "Hi", "revisions": []}]
        self.assertEqual(translation_fingerprint(base), translation_fingerprint(repaired))
        self.assertNotEqual(translation_fingerprint(base), translation_fingerprint(changed))


class CacheTests(unittest.TestCase):
    def test_key_changes_when_inputs_change(self):
        qwen = load_config()["qwen3"]
        base = synth_cache_key("Hello", "a" * 64, "ref", 43, qwen)
        self.assertNotEqual(base, synth_cache_key("Hello!", "a" * 64, "ref", 43, qwen))
        self.assertNotEqual(base, synth_cache_key("Hello", "b" * 64, "ref", 43, qwen))
        self.assertNotEqual(base, synth_cache_key("Hello", "a" * 64, "ref", 143, qwen))
        changed = json.loads(json.dumps(qwen))
        changed["generation"]["temperature"] = 0.1
        self.assertNotEqual(base, synth_cache_key("Hello", "a" * 64, "ref", 43, changed))
        self.assertNotEqual(fingerprint({"stage": "transcribe", "mic": "abc"}), fingerprint({"stage": "transcribe", "mic": "abc", "english": "Hi"}))


class ResumeTests(unittest.TestCase):
    def test_completed_stage_with_matching_fingerprint_is_current(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job = Job.create(root, "j", "/tmp/v.mp4", {"_project_root": str(root)})
            (root / "inspect").mkdir()
            (root / "inspect/probe.json").write_text("{}", encoding="utf-8")
            job.set_stage("inspect", "complete", "abc", {"probe": "inspect/probe.json"})
            self.assertTrue(_fp_ok(job, "inspect", "abc", ["inspect/probe.json"]))
            self.assertFalse(_fp_ok(job, "inspect", "changed", ["inspect/probe.json"]))
            job.stage("inspect")["status"] = "running"
            self.assertFalse(_fp_ok(job, "inspect", "abc", ["inspect/probe.json"]))

    def test_lock_blocks_second_holder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = JobLock(root)
            first.__enter__()
            try:
                with self.assertRaises(RuntimeError):
                    with JobLock(root):
                        pass
            finally:
                first.__exit__(None, None, None)


class OutputTests(unittest.TestCase):
    def test_srt_omits_unplaced_text(self):
        text = render_srt([
            {"id": 1, "placed": True, "placement_start": 1.0, "placement_end": 1.5, "english": "Placed line"},
            {"id": 2, "placed": False, "placement_start": 2.0, "placement_end": 2.0, "english": "UNIQUE_OMITTED_LINE"},
        ])
        self.assertIn("Placed line", text)
        self.assertNotIn("UNIQUE_OMITTED_LINE", text)

    def test_report_limits_are_not_sample_specific(self):
        text = validation_markdown({
            "status": "partial",
            "job_id": "clip",
            "english_video": "output/english_PARTIAL.mp4",
            "n_segments": 1,
            "n_placed": 0,
            "n_unplaced": 1,
            "n_tempo": 0,
            "n_alternate": 0,
            "n_revisions": 0,
            "n_synth_fresh": 0,
            "n_synth_cache_hits": 0,
            "mix": {"gain": 1.0, "mix_peak": 0.1, "clipping_samples": 0},
            "checks": [],
        })
        self.assertNotIn("this sample", text.lower())
        self.assertNotIn("second unseen", text.lower())
        self.assertIn("1–2 hour", text)

    def test_english_mux_does_not_take_source_audio_or_shortest(self):
        cmd = mux_english_cmd("ffmpeg", "/tmp/a file.mp4", "/tmp/mix.wav", "/tmp/out.mp4")
        self.assertNotIn("-shortest", cmd)
        self.assertIn("0:v:0", cmd)
        self.assertIn("1:a:0", cmd)
        self.assertNotIn("0:a:0", cmd)
        self.assertIn("/tmp/a file.mp4", cmd)
        es = mux_spanish_cmd("ffmpeg", "/tmp/a file.mp4", 0, "/tmp/es.mp4")
        self.assertIn("0:a:0", es)
        self.assertNotIn("-shortest", es)

    def test_mix_is_game_plus_centered_voice(self):
        game = np.full((4, 2), 0.1, dtype=np.float32)
        voice = np.full(4, 0.2, dtype=np.float32)
        mixed, info = mix_game_and_voice(game, voice, 0.99)
        self.assertAlmostEqual(float(mixed[0, 0]), 0.3)
        self.assertAlmostEqual(float(mixed[0, 1]), 0.3)
        self.assertEqual(info["gain"], 1.0)
        hot = np.ones((4, 2), dtype=np.float32)
        loud, info = mix_game_and_voice(hot, np.ones(4), 0.99)
        self.assertLessEqual(info["mix_peak"], 0.99 + 1e-6)
        self.assertEqual(info["clipping_samples"], 0)

    def test_place_does_not_overwrite_earlier_line(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.wav"
            b = root / "b.wav"
            sf.write(str(a), np.full(1000, 0.4, dtype=np.float32), 48000)
            sf.write(str(b), np.full(1000, 0.8, dtype=np.float32), 48000)
            scheduled = [
                {"id": 1, "start": 0.0, "placed": True, "placement_start": 0.0, "used_path": str(a), "status": "fit_unchanged", "timing_error": ""},
                {"id": 2, "start": 0.01, "placed": True, "placement_start": 0.01, "used_path": str(b), "status": "fit_unchanged", "timing_error": ""},
            ]
            mix, hits = place_voice(scheduled, 48000, 48000, 0)
            self.assertTrue(hits)
            self.assertTrue(scheduled[0]["placed"])
            self.assertFalse(scheduled[1]["placed"])
            self.assertGreater(float(np.max(np.abs(mix[:1000]))), 0.2)
            self.assertLess(float(np.max(np.abs(mix[1000:2000]))), 0.01)

    def test_refuse_write_into_historical_tree(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                assert_write_in_job(Path("/home/siamarino/ai-dubbing/pipeline/config/default.json"), Path(td))


class SegmentTests(unittest.TestCase):
    def test_onset_drop_and_no_invented_text(self):
        sr = 1000
        wav = np.zeros((3000, 1), dtype=np.float32)
        wav[400:700, 0] = 0.2
        wav[2000:2300, 0] = 0.2
        whisper = {"segments": [
            {"start": 0.1, "end": 0.9, "text": " Hola", "words": [{"word": " Hola", "start": 0.1, "end": 0.9, "probability": 0.2}]},
            {"start": 1.2, "end": 1.5, "text": " Adentro", "words": [{"word": " Adentro", "start": 1.2, "end": 1.5, "probability": 0.9}]},
        ]}
        built = build_segments(whisper, wav, sr, {
            "energy_rms": 0.005,
            "energy_window_sec": 0.01,
            "onset_lookback_sec": 0.05,
            "end_tail_sec": 0.05,
            "merge_max_silence_sec": 0.12,
            "min_voiced_sec": 0.04,
            "uncertain_probability": 0.5,
        })
        self.assertEqual(len(built["segments"]), 1)
        self.assertGreater(built["segments"][0]["start"], 0.2)
        self.assertTrue(any(d["reason"] == "no_energy" for d in built["dropped"]))
        self.assertTrue(built["untranscribed_energy"])
        self.assertTrue(built["segments"][0]["uncertain_words"])
        self.assertEqual(built["segments"][0]["spanish"], "Hola")

    def test_trim_matches_ported_window(self):
        sr = 48000
        wav = np.zeros(sr, dtype=np.float32)
        wav[1000:2000] = 0.2
        trimmed, lead, trail = trim_silence(wav, sr, 0.005, 0)
        self.assertGreater(lead, 0)
        self.assertGreater(trail, 0)
        self.assertLess(trimmed.size, wav.size)
        mask = voiced_mask(wav, sr, 0.005, 0.01)
        self.assertTrue(mask[1500])
        self.assertFalse(mask[10])


class ConfigTests(unittest.TestCase):
    def test_confirmed_reference_text(self):
        self.assertEqual(reference_text(load_config()), CONFIRMED_REFERENCE_TEXT)
        self.assertIn("he bite me", CONFIRMED_REFERENCE_TEXT)


if __name__ == "__main__":
    unittest.main()
