"""Regressions from the conversational-performance audit, using bounded fixtures."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from aidub.second_pass import run_second_pass, final_coverage
from aidub.segment import coverage_gaps_file
from aidub.util import read_json
from aidub.util import write_json
from aidub.events import apply_events, event_placement_report, identity as event_identity
from aidub.context import quality_translation_request
from aidub.handoff import validate_translation_response, TRANSLATION_SCHEMA
from aidub.textnorm import sequence_check
from aidub.performance import contextual_quality, quiet_intervals, score_contextual
from aidub.continuity import render_protected
from aidub.context import join_short_pauses, utterance_groups
from aidub.pipeline import source_uncertainty_issues, _present_v3, _cache_misses
from aidub.linework import collect_line_best_of_n
from aidub.fidelity import material_conflict, voicing_uncertainty
from types import SimpleNamespace
from aidub.vocal_verification import verify_prefix


def seg(i, start, end, text):
    return dict(id=i, start=start, end=end, spanish=text, notes="", uncertain_words=[])


class SurvivingCoverageTests(unittest.TestCase):
    def test_short_gap_word_needs_timed_context_corroboration(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);mic=root/"mic.wav";sf.write(mic,np.zeros(16000*5),16000)
            built={"segments":[seg(1,1,2,"No tiene sentido")],"untranscribed_energy":[{"span":[2.1,2.3]}],"corrections":[]}
            cfg={"asr_second_pass":{"enabled":True,"confirm_recovered":True}}
            def hear(path,options):
                if "gap_confirm" in str(path):
                    return {"segments":[{"words":[dict(word="sentido",start=.1,end=.4,probability=.99)]}]}
                return {"segments":[{"words":[dict(word="¡Gracias!",start=.35,end=.37,probability=.65)]}]}
            out=run_second_pass(root,built,mic,0,cfg,hear)
            self.assertEqual(len(out["segments"]),1)
            target=read_json(root/"transcribe/second_pass.json")["targets"][0]
            self.assertEqual(target["outcome"],"unintelligible")
            self.assertFalse(target["context_confirmation"]["confirmed"])
            # Policy changes preserve saved acoustic hearings; only the new
            # confirmation window is an additional ASR request.
            run_second_pass(root,built,mic,0,cfg,lambda *a:self.fail("hearing cache not reused"))

    def test_context_word_with_broad_approximate_timing_can_corroborate_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);mic=root/"mic.wav";sf.write(mic,np.zeros(16000*5),16000)
            built={"segments":[seg(1,3,4,"Intentar escapar")],"untranscribed_energy":[{"span":[2.1,2.3]}],"corrections":[]}
            built["segments"][0]["source_words"]=[dict(word="Intentar",start=3.2,end=3.6)]
            cfg={"asr_second_pass":{"enabled":True,"confirm_recovered":True}}
            def hear(path,options):
                # Confirmation window starts at 1.3; broad word 1.3–2.4
                # intersects the gap even though its midpoint is too early.
                a,b=(0.,1.1) if "gap_confirm" in str(path) else (.35,.55)
                return {"segments":[{"words":[dict(word="Intentar...",start=a,end=b,probability=.7)]}]}
            out=run_second_pass(root,built,mic,0,cfg,hear)
            self.assertEqual(len(out["segments"]),2)
            self.assertEqual(read_json(root/"transcribe/second_pass.json")["targets"][0]["outcome"],"recovered")

    def test_final_coverage_includes_recovered_prefix_and_joined_cues(self):
        d={"segments":[seg(2,10.179,20.949,"Eh... Es la primera vez")],
           "untranscribed_energy":[{"span":[10.179,11.097]},{"span":[21.8,22]}]}
        c=final_coverage(d)
        self.assertEqual(c["kept"],1)
        self.assertEqual(c["uncovered"],[(21.8,22.)])

    def test_a_distant_connector_does_not_close_an_uncertain_timed_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);mic=root/"mic.wav";sf.write(mic,np.zeros(160000),16000)
            s=seg(1,3,4,"Y bueno")
            s["source_words"]=[dict(word="Y",start=3,end=3.2),dict(word="bueno",start=3.2,end=4)]
            built={"segments":[s],"corrections":[],"untranscribed_energy":[{"span":[5,5.6]}]}
            hearing={"segments":[{"words":[dict(word="Y...",start=.4,end=.8,probability=.534)]}]}
            out=run_second_pass(root,built,mic,0,{"asr_second_pass":{"enabled":True}},lambda *a:hearing)
            self.assertEqual(out["untranscribed_energy"][0]["second_pass"]["outcome"],"unintelligible")

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


class VocalEventTests(unittest.TestCase):
    def test_focused_prefix_hearings_survive_full_sentence_normalization_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);mic,cfg,built,raw=self.fixture(root);calls=[]
            def hear(path):
                calls.append(path);return {"text":"Uh.","mean_probability":.25}
            result=verify_prefix(root,{"path":str(mic)},"Uh...",lambda:"checker",hear)
            self.assertTrue(result["verified"])
            self.assertTrue(result["low_confidence"])
            self.assertEqual(len(calls),2)
            again=verify_prefix(root,{"path":str(mic)},"Uh...",lambda:"checker",lambda p:self.fail("cache missed"))
            self.assertTrue(again["cache_hit"])
            q=contextual_quality({},dict(ok=True,reasons=[],asr_text="This is the first time",event_prefix_check=result),
                                 {"required_event_prefix":"Uh..."},{})
            self.assertTrue(q["event_prefix_verified"])
            wrong=verify_prefix(root,{"path":str(mic)},"Hmm...",lambda:"checker",lambda p:{"text":"This is"})
            self.assertFalse(wrong["verified"])

    def test_timed_prefix_keeps_following_thought_and_requires_generated_filler(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);mic,cfg,built,raw=self.fixture(root)
            cfg["source_events"]["realization_mode"]="prefix_with_following"
            out=apply_events(built,raw,mic,0,cfg,"mic")
            self.assertEqual(len(out["segments"]),1)
            s=out["segments"][0]
            self.assertEqual(s["id"],2)
            self.assertEqual(s["spanish"],"Eh... Es la primera vez.")
            self.assertEqual(s["start"],.5)
            self.assertEqual(contextual_quality({},dict(ok=True,reasons=[],asr_text="It's the first time"),s,{})["reasons"],
                             ["missing_vocal_event_prefix"])
            q=contextual_quality({},dict(ok=True,reasons=[],asr_text="Uh, it's the first time"),s,{})
            self.assertTrue(q["event_prefix_verified"])
            self.assertEqual(event_placement_report(out["vocal_events"],[dict(id=2,placed=True,quality=q)])["unresolved"],[])

    def fixture(self, root, annotation=True, noise=False):
        sr = 16000; x = np.zeros(sr*3)
        x[round(.5*sr):sr] = (np.random.default_rng(7).normal(0, .05, sr//2) if noise else
                                          .1*np.sin(2*np.pi*140*np.arange(sr//2)/sr))
        mic = root/"mic.wav"; sf.write(mic, x, sr)
        cfg = {"_project_root": str(root), "source_events": {"enabled": True}, "schedule": {"max_tempo": 1.1},
               "translation_quality": {"enabled": True}}
        built = {"segments": [seg(2, .5, 2, "Es la primera vez.")]}
        raw = {"segments": [{"words": [dict(word=w, start=a, end=b) for w,a,b in
                                       [("Es",1,1.2),("la",1.2,1.3),("primera",1.3,1.6),("vez.",1.6,2)]]}]}
        if annotation:
            cfg["source_events"]["annotations_file"] = "events.json"
            write_json(root/"events.json", dict(schema="aidub.source_events.v1", mic_sha256="mic",
                events=[dict(id="thinking", start=.5, end=1., kind="hesitation", status="confirmed",
                             provenance="user_listening", evidence="User identified the thinking sound", realization="Uh...")]))
        return mic, cfg, built, raw

    def test_confirmed_hesitation_inside_cue_reaches_translation_and_placement(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); mic,cfg,built,raw = self.fixture(root)
            out = apply_events(built,raw,mic,0,cfg,"mic")
            self.assertEqual([(s["id"],s["spanish"],s["start"]) for s in out["segments"]],
                             [(3,"Eh...",.5),(2,"Es la primera vez.",1.)])
            self.assertEqual(built["segments"][0]["start"], .5)  # no in-place mutation
            req = quality_translation_request("j",out["segments"],3,cfg,None)
            response = dict(schema=TRANSLATION_SCHEMA,job_id="j",translator={"kind":"command"},
                            segments=[dict(id=3,english="Uh..."),dict(id=2,english="It's the first time.")])
            self.assertEqual(validate_translation_response(req,response), [])
            response["segments"][0]["english"] = "Right!"
            self.assertTrue(validate_translation_response(req,response))
            report = event_placement_report(out["vocal_events"],[dict(id=3,english="Uh...",placed=True)])
            self.assertEqual(report["unresolved"], [])
            self.assertEqual(event_placement_report(out["vocal_events"],[])["unresolved"], ["thinking"])

    def test_periodic_unknown_is_never_automatically_spoken(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); mic,cfg,built,raw = self.fixture(root,annotation=False)
            out=apply_events(built,raw,mic,0,cfg,"mic")
            self.assertEqual(len(out["segments"]),1)
            self.assertEqual(out["vocal_events"]["events"][0]["status"],"uncertain")
            self.assertTrue(event_placement_report(out["vocal_events"],[])["unresolved"])

    def test_noise_is_not_a_hesitation_and_annotation_is_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); mic,cfg,built,raw = self.fixture(root,annotation=False,noise=True)
            out=apply_events(built,raw,mic,0,cfg,"mic")
            self.assertEqual(out["vocal_events"]["events"],[])
            mic,cfg,built,raw = self.fixture(root)
            before=event_identity(cfg)
            doc=read_json(root/"events.json");doc["events"][0]["end"]=1.2;write_json(root/"events.json",doc)
            self.assertNotEqual(before,event_identity(cfg))
            out=apply_events(built,raw,mic,0,cfg,"mic")
            self.assertEqual(len(out["segments"]),1)
            self.assertEqual(out["vocal_events"]["events"][0]["disposition"],"unresolved")
            with self.assertRaisesRegex(ValueError,"hash mismatch"):
                apply_events(built,raw,mic,0,cfg,"wrong")

    def test_missing_or_embellished_filler_is_not_a_pass(self):
        self.assertIn("missing_vocal_event",sequence_check("Uh...","")["hard"])
        self.assertIn("extra_speech",sequence_check("Uh...","Uh, let's go!")["hard"])
        self.assertEqual(sequence_check("Uh...","Um")["hard"],[])


class PerformanceTimingTests(unittest.TestCase):
    def test_disputed_source_is_not_spoken_or_loaded_for_synthesis(self):
        s=seg(1,.6,.9,"Bien.");s["english"]="Okay."
        s["translation_review"]={"status":"disputed","issues":["uncertain_source"]}
        cfg={"source_events":{"enabled":True}}
        self.assertEqual(voicing_uncertainty(s,cfg)["kind"],"unresolved_source_or_translation")
        self.assertEqual(_cache_misses([s],cfg,Path("unused"),"ref","text",3),[])
        self.assertIsNone(voicing_uncertainty(s,{}))
        s["translation_review"]["status"]="ok"
        self.assertIsNone(voicing_uncertainty(s,cfg))

    def test_protected_lead_can_use_local_slack_without_moving_next_anchor(self):
        sr=24000;x=np.zeros(sr,dtype=np.float32)
        x[2400:12000]=.08*np.sin(2*np.pi*150*np.arange(9600)/sr)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);raw=root/"raw.wav";sf.write(raw,x,sr,subtype="FLOAT")
            (root/"schedule/work").mkdir(parents=True)
            edge={"fade_ms":12,"protection":{"inspect_full_tail":True,"max_onset_delay_ms":80}}
            cue=seg(1,1,1.7,"Okay")
            chosen=dict(raw_path=str(raw),kind="candidate",seed=1,placed=True,tempo=1.)
            out=_present_v3(SimpleNamespace(dir=root),{},cue,chosen,1.,2.,3.,None,edge)
            self.assertTrue(out["placed"])
            self.assertGreater(out["presentation"]["core_onset_delay_sec"],0)
            self.assertLessEqual(out["presentation"]["core_onset_delay_sec"],.08)
            self.assertGreaterEqual(out["placement_start"],1.-1/sr)
            self.assertLess(out["placement_start"]+out["generated_duration_sec"],2.)
            self.assertTrue(out["edge"]["protected_signal_preserved"])
            self.assertEqual(cue["start"],1.)
            short=_present_v3(SimpleNamespace(dir=root),{},cue,chosen,1.,1.4,3.,None,edge)
            self.assertFalse(short["placed"])
            self.assertEqual(short["timing_error"],"protected_edge_outside_window")

    def test_opposite_source_readings_are_not_guessed_from_game_context(self):
        s=seg(1,2182.6,2184.1,"Vamos a comer unos ya es suficiente")
        s["asr_alternatives"]=[{"text":"Pero aún no es suficiente"}]
        self.assertEqual(material_conflict(s)["decision"],"unvoiced_pending_source_resolution")
        s=seg(1,22,30,"Pero luego no volví a jugarlo")
        s["asr_alternatives"]=[{"text":"Pero luego no volvía a jugarlo, digamos"}]
        self.assertIsNone(material_conflict(s))
        s["spanish"]="No debería luchar Tengo tres balas"
        s["source_cues"]=[{"spanish":"No debería luchar"},{"spanish":"Tengo tres balas"}]
        s["asr_alternatives"]=[{"text":"Tengo 3 balas"}]
        self.assertIsNone(material_conflict(s))

    def test_valid_but_unplaceable_takes_use_remaining_budget_without_shifting_event(self):
        def run(place_third):
            seen=[]
            def synth(text,seed):seen.append(seed);return {}
            def attempt(s,text,seed,kind,meta,*unused):
                placed=place_third and len(seen)==3
                return dict(seed=seed,text=text,kind=kind,placed=placed,tempo=1.,
                            generated_duration_sec=.4 if placed else .65,status="fit_unchanged" if placed else "unresolved",timing_error="overrun")
            result=collect_line_best_of_n(dict(id=8,english="Uh...",start=1.,end=1.5,anchor_type="vocal_event"),
                occupied=0,next_start=1.5,source_duration=3,cfg={"schedule":{"seed_base":42}},
                synthesize=synth,assess=lambda *a:{"ok":True,"reasons":[]},attempt_fn=attempt,
                revision_limit_n=2,score=lambda a:{"score":0.},candidates=2,max_extra=2,search_for_placeable=True)
            return result,seen
        result,seen=run(True)
        self.assertEqual(len(seen),3)
        self.assertTrue(result["chosen"]["placed"])
        result,seen=run(False)
        self.assertEqual(len(seen),4)
        self.assertFalse(result["chosen"]["placed"])
        self.assertFalse(result["needs_repair"])
        self.assertNotIn("leading_shift_sec",result["chosen"])

    def test_classified_uncertainty_is_not_a_content_pass(self):
        c={"untranscribed_energy":[{"span":[4,5],"second_pass":{"outcome":"unintelligible","text":"Y..."}},
                                   {"span":[8,9],"second_pass":{"outcome":"non_speech_energy"}}]}
        s=seg(3,10,11,"No sé");s["translation_review"]={"status":"disputed"}
        issues=source_uncertainty_issues(c,[s])
        self.assertEqual([i["kind"] for i in issues],["unintelligible_source","disputed_translation"])
        self.assertEqual(source_uncertainty_issues({},[]),[])

    def test_source_supported_thinking_pause_is_not_a_global_failure(self):
        sr=16000; tone=.1*np.sin(2*np.pi*140*np.arange(sr)/sr)
        wav=np.r_[tone,np.zeros(round(1.3*sr)),tone].astype(np.float32)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"raw.wav";sf.write(path,wav,sr)
            opts={"source_pauses":{"enabled":True},"weights":{"pause":2.}}
            source=dict(start=10.,end=13.3,source_pauses=[dict(start=11.,end=12.3,duration=1.3)])
            original={"ok":False,"reasons":["pathological_pause"]}
            a={"raw_path":str(path)}
            good=contextual_quality(a,original,source,opts)
            self.assertTrue(good["ok"])
            self.assertEqual(original["reasons"],["pathological_pause"])
            self.assertEqual(a["raw_quality"],original)
            bad=contextual_quality({"raw_path":str(path)},dict(original,reasons=["pathological_pause","missing_or_incorrect_text"]),source,opts)
            self.assertEqual(bad["reasons"],["missing_or_incorrect_text"])
            misplaced=dict(source,source_pauses=[dict(start=10.,end=10.4,duration=.4)])
            self.assertFalse(contextual_quality({"raw_path":str(path)},original,misplaced,opts)["ok"])
            self.assertEqual(score_contextual({"score":2.,"components":{"pause":1.}},a,opts)["components"]["pause"],0.)

    def test_reaction_keeps_anchor_during_grouping(self):
        rows=[seg(1,1,2,"La idea"),seg(2,2.1,2.4,"Eh..."),seg(3,2.5,3,"es jugarlo")]
        joined,_=join_short_pauses(rows,max_gap_sec=.35,open_gap_sec=.35,max_duration_sec=10,max_parts=3,preserve_reactions=True)
        self.assertEqual(len(joined),3)
        groups=utterance_groups(rows,preserve_boundaries=True)
        self.assertNotEqual(groups[1][0],groups[2][0])

    def test_full_tail_keeps_delayed_and_soft_generated_decay(self):
        sr=24000; wav=np.zeros(sr*2,dtype=np.float32)
        wav[2400:sr]=.08*np.sin(2*np.pi*140*np.arange(sr-2400)/sr)
        # A delayed release outside the former 400-ms search, below RMS .0015.
        a,b=round(1.5*sr),round(1.7*sr)
        wav[a:b]=.0007*np.sin(2*np.pi*2200*np.arange(b-a)/sr)
        edge={"fade_ms":12,"protection":{"inspect_full_tail":True,"decay_floor_rms":.0001}}
        new,info=render_protected(wav,sr,edge,target_rms=None,lead_room=sr,tail_room=sr*2)
        self.assertTrue(info["full_tail_inspected"])
        start=info["first"]-round(info["lead_ms_used"]*sr/1000)
        np.testing.assert_array_equal(new[a-start:b-start],wav[a:b])
        short,why=render_protected(wav,sr,edge,target_rms=None,lead_room=sr,tail_room=round(.2*sr))
        self.assertIsNone(short)
        self.assertEqual(why["reason"],"protected_edge_outside_window")
