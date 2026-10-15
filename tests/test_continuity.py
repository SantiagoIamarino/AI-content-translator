import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

from aidub.audio import render_voice_with_margins
from aidub.continuity import identity, protected_edges, render_protected, source_pacing_score
from aidub.linework import collect_line_best_of_n
from aidub.pipeline import _present_v3
from aidub.selection import settings


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.sr = 24000
        self.edge = {'presentation_version': 3, 'enabled': True, 'fade_ms': 12,
                     'protection': {'floor_rms': .0015, 'max_tail_ms': 400, 'settle_ms': 20}}
        # A voiced core, a closure, then a quiet final sound below the fixed RMS gate.
        self.wav = np.zeros(24000, dtype=np.float32)
        self.wav[2400:12000] = .08*np.sin(2*np.pi*180*np.arange(9600)/self.sr)
        self.wav[14400:18000] = .004*np.sin(2*np.pi*2300*np.arange(3600)/self.sr)

    def test_quiet_final_sound_after_closure_is_kept_without_fade(self):
        old, _ = render_voice_with_margins(self.wav, self.sr)
        new, info = render_protected(self.wav, self.sr, self.edge, target_rms=None,
                                     lead_room=24000, tail_room=24000)
        self.assertGreater(len(new), len(old)+4000)
        start = info['first'] - round(info['lead_ms_used']*self.sr/1000)
        np.testing.assert_array_equal(new[14400-start:18000-start], self.wav[14400:18000])
        self.assertTrue(info['protected_signal_preserved'])

    def test_raw_unsettled_ending_is_rejected_not_faded(self):
        raw = self.wav[:17000]
        piece, info = render_protected(raw, self.sr, self.edge, target_rms=None,
                                       lead_room=24000, tail_room=24000)
        self.assertIsNone(piece)
        self.assertEqual(info['reason'], 'raw_ending_unsettled')

    def test_limited_window_rejects_instead_of_cutting_soft_phoneme(self):
        piece, info = render_protected(self.wav, self.sr, self.edge, target_rms=None,
                                       lead_room=24000, tail_room=1000)
        self.assertIsNone(piece)
        self.assertEqual(info['reason'], 'protected_edge_outside_window')

    def test_tempo_overflow_is_not_silently_sliced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root/'raw.wav'
            sf.write(raw, self.wav, self.sr, subtype='FLOAT')
            chosen = {'raw_path': str(raw), 'tempo': 1.1, 'seed': 1, 'kind': 'primary', 'placed': True}
            def bad_tempo(ffmpeg, src, dest, tempo, **kw):
                sf.write(dest, np.ones(self.sr*2)*.02, self.sr, subtype='FLOAT')
            with patch('aidub.pipeline.atempo', bad_tempo):
                result = _present_v3(SimpleNamespace(dir=root), {'executables': {'ffmpeg': 'ffmpeg'}},
                                     {'id':1, 'start':1}, chosen, 0, 2, 3, None, self.edge)
            self.assertFalse(result['placed'])
            self.assertEqual(result['timing_error'], 'protected_edge_outside_window_after_tempo')

    def test_source_duration_breaks_rushed_take_preference(self):
        opts = settings({'voice_selection': {'enabled': True, 'source_pacing': {'enabled':True}}})
        seg = {'start':45.16, 'end':56.43525}
        short = {'score':1.1067, 'components': {}, 'pacing': {'core_sec':7.6165,'syllables':41}}
        longer = {'score':1.3993, 'components': {}, 'pacing': {'core_sec':8.5657,'syllables':41}}
        self.assertLess(source_pacing_score(longer, seg, opts)['score'], source_pacing_score(short, seg, opts)['score'])
        untouched = copy.deepcopy(short)
        source_pacing_score(short, seg, opts)
        self.assertEqual(short, untouched)
        # Long real silence is not a target, and short reactions receive no duration penalty.
        self.assertLess(source_pacing_score(short, {'start':0,'end':60},opts)['source_pacing']['target_sec'], 11)
        self.assertEqual(source_pacing_score(short, {'start':0,'end':.8},opts)['score'], short['score'])

    def test_presentation_rejection_uses_extra_seed_and_preserves_raw_quality(self):
        cfg = {'schedule': {'seed_base':42}, 'fit_retries': {}}
        called=[]
        def synth(text, seed):
            called.append(seed)
            return {}
        def attempt(seg, text, seed, kind, meta, *args):
            return {'seed':seed,'kind':kind,'placed':seed!=43,'tempo':1,'generated_duration_sec':.5,
                    **({'presentation_rejected':'raw_ending_unsettled'} if seed==43 else {})}
        result = collect_line_best_of_n({'id':1,'english':'Alright','start':1}, occupied=0,next_start=3,
             source_duration=4,cfg=cfg,synthesize=synth,assess=lambda *a:{'ok':True,'reasons':[]},
             attempt_fn=attempt,revision_limit_n=0,score=lambda a:{'score':1},candidates=1,max_extra=1)
        self.assertEqual(called,[43,1043])
        self.assertEqual(result['chosen']['seed'],1043)
        self.assertTrue(result['attempts'][0]['raw_quality']['ok'])
        self.assertFalse(result['attempts'][0]['quality']['ok'])

    def test_where_d_repetition_is_expected_but_extra_repetition_still_rejects(self):
        from aidub.textnorm import sequence_check
        expected = "Where'd it land? Where'd it land?"
        result = sequence_check(expected, "Where did it land? Where did it land?")
        self.assertEqual(result['hard'], [])
        self.assertEqual(result['soft'], [])
        self.assertIn('repetition', sequence_check(expected, "Where did it land? "*3)['hard'])
        self.assertIn('missing_or_incorrect_text', sequence_check(expected, "Where did it land?")['hard'])

    def test_fractional_lead_room_does_not_overlap_or_omit_following_cue(self):
        from aidub.pipeline import _present_v2
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            raw=root/'raw.wav'
            sf.write(raw,self.wav,self.sr,subtype='FLOAT')
            occupied=1928.5521246666665
            seg={'id':302, 'start':1928.560396}
            chosen={'raw_path':str(raw),'seed':1,'kind':'primary','tempo':1.,'placed':True}
            result=_present_v2(SimpleNamespace(dir=root),{'schedule':{'trim_rms':.005}},seg,chosen,occupied,1932.928938,2000,None,{})
            self.assertGreaterEqual(result['placement_start'],occupied)
            # A 48 kHz assembler must keep both cues, not silently omit cue 302.
            result3=_present_v3(SimpleNamespace(dir=root),{'schedule':{'trim_rms':.005}},seg,chosen,occupied,1932.928938,2000,None,self.edge)
            self.assertTrue(result3['placed'])
            self.assertGreaterEqual(result3['placement_start'],occupied)

    def test_only_opted_in_schedule_identity_changes(self):
        self.assertEqual(identity({'voice_edge':{'presentation_version':2}}),{})
        self.assertIn('continuity_code',identity({'voice_edge':self.edge}))
        self.assertIn('continuity_code',identity({'voice_selection':{'source_pacing':{'enabled':True}}}))


if __name__ == '__main__':
    unittest.main()
