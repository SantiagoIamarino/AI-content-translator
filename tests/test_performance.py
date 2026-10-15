"""Regressions from the conversational-performance audit, using bounded fixtures."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from aidub.second_pass import run_second_pass
from aidub.segment import coverage_gaps_file
from aidub.util import read_json


def seg(i, start, end, text):
    return dict(id=i, start=start, end=end, spanish=text, notes="", uncertain_words=[])


class SurvivingCoverageTests(unittest.TestCase):
    def test_candado_unique_suffix_survives_head_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mic = root / "mic.wav"
            sf.write(mic, np.zeros(80000), 16000)
            built = {"segments": [seg(1, 1, 1.3, "A ver"), seg(2, 2.1, 3.1, "A ver este candado")],
                     "untranscribed_energy": [], "corrections": []}
            calls = []

            def hear(path, options):
                calls.append(Path(path).stem)
                # Window starts at .65; common prefix belongs to the later cue.
                return {"segments": [{"words": [
                    dict(word=w, start=a, end=b, probability=.9)
                    for w, a, b in [("A", 1.5, 1.6), ("ver", 1.6, 1.8), ("este", 1.8, 2), ("candado", 2, 2.4)]]}]}

            out = run_second_pass(root, built, mic, 0, {"asr_second_pass": {"enabled": True}}, hear)
            self.assertEqual([s["spanish"] for s in out["segments"]], ["A ver este candado"])
            self.assertEqual(out["source_coverage"]["removed_duplicates"], 1)
            self.assertEqual(calls, ["dup_1_2"])
            # A repeated run reuses the hearing, not a new provider/model call.
            run_second_pass(root, built, mic, 0, {"asr_second_pass": {"enabled": True}},
                            lambda *args: self.fail("saved hearing was not reused"))

    def test_ambiguous_prefix_does_not_delete_unique_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); mic = root / "mic.wav"
            sf.write(mic, np.zeros(80000), 16000)
            built = {"segments": [seg(1, 1, 1.3, "A ver"), seg(2, 2.1, 3.1, "A ver este candado")],
                     "untranscribed_energy": [], "corrections": []}
            result = {"segments": [{"words": [dict(word="A ver", start=.4, end=.6, probability=.9)]}]}
            out = run_second_pass(root, built, mic, 0, {"asr_second_pass": {"enabled": True}}, lambda *a: result)
            self.assertEqual(len(out["segments"]), 2)
            self.assertEqual(read_json(root/"transcribe/second_pass.json")["targets"][0]["outcome"],
                             "unresolved_duplicate_unique_words_preserved")

    def test_removed_cue_exposes_energy_for_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); mic = root / "mic.wav"; sr = 16000
            x = np.zeros(sr*5)
            x[sr:2*sr] = .1*np.sin(2*np.pi*150*np.arange(sr)/sr)
            sf.write(mic, x, sr)
            cfg = dict(energy_rms=.005, energy_window_sec=.01, min_voiced_sec=.04)
            before = coverage_gaps_file(mic, [seg(1, .9, 2.1, "A ver")], cfg)
            after = coverage_gaps_file(mic, [], cfg)
            self.assertEqual(before, [])
            self.assertEqual(len(after), 1)
            self.assertLess(after[0]["span"][0], 1.01)
            built = {"segments": [seg(1, .9, 2.1, "Hola buenas"), seg(2, 3, 4, "Hola buenas")],
                     "untranscribed_energy": [], "corrections": []}
            calls = []
            def hear(path, options):
                calls.append(Path(path).stem)
                if calls[-1].startswith("dup"):
                    return {"segments": [{"words": [dict(word="Hola buenas", start=2.6, end=3, probability=.9)]}]}
                return {"segments": []}
            out = run_second_pass(root, built, mic, 0, {"asr_second_pass": {"enabled": True}, "segmentation": cfg}, hear)
            self.assertIn("gap_0000", calls)
            self.assertTrue(out["source_coverage"]["uncovered"])
            self.assertEqual(out["untranscribed_energy"][0]["second_pass"]["outcome"], "no_speech_heard")
