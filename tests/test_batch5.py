import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from aidub.fidelity import (RESOLUTION_POLICY, boundary_diagnostics, eligibility, material_conflict,
                            resolution_binding, voicing_uncertainty)
from aidub.job import Job, JobLock
from aidub.pipeline import source_uncertainty_issues, _cache_misses
from aidub.source_resolution import (resolve_sources, pending_source_resolution, load_state,
                                     assessment_errors, settings, _episode_key)
from aidub.review import validate_review_response
from aidub.util import read_json, write_json


def cue():
    return dict(id=1, start=1., end=3., spanish='Bueno vamos vamos', english='Well, come on, come on.',
                english_original='Well, come on, come on.', uncertain_words=[], revisions=[],
                source_words=[dict(word=w, start=1.1+i*.3, end=1.3+i*.3, probability=.95) for i,w in enumerate(('Bueno','vamos','vamos'))],
                translation_review=dict(status='disputed', checked_text='Well, come on, come on.', issues=['uncertain_source']))


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.cfg=read_json(Path(__file__).resolve().parents[1]/'config/default.json')
        self.cfg.update(source_events={'enabled':True}, source_resolution={'enabled':True,'max_semantic_rounds':2},
                        translation_quality={'enabled':True,'review':{'enabled':True,'max_rounds':2,'back_translation':'disputed'}},
                        asr_second_pass={'enabled':True,'model':'turbo','options':{'beam_size':5}})
        self.cfg['models']={'whisper_path':str(self.root/'weights.pt')};(self.root/'weights.pt').write_bytes(b'fake')
        self.job=Job.create(self.root/'job','test','unused',self.cfg)
        self.seg=cue();self.job.data['timeline']=[self.seg];self.job.stage('translation')['status']='complete';self.job.save()
        sr=1000; (self.job.dir/'extract').mkdir()
        sf.write(self.job.dir/'extract/mic_raw.wav',.1*np.sin(2*np.pi*100*np.arange(5000)/sr),sr)
        write_json(self.job.dir/'extract/alignment.json',dict(mic_sha256='mic',offset_sec=0.,video_duration=5.))
        write_json(self.job.dir/'inspect/probe.json',{'described':{'video':{'duration':5.}}})
        self.calls=[];self.hearings=[]

    def hear(self,path,options):
        self.hearings.append((path,options))
        return {'text':'Bueno vamos vamos','segments':[{'words':[dict(w,start=w['start'],end=w['end']) for w in self.seg['source_words']], 'no_speech_prob':0.}]}

    def response(self,request,confidence='minor',revise=None,parts=None):
        rows=[]
        for src in request['segments']:
            e=src['source_evidence']
            rows.append(dict(id=src['id'],verdict='revise' if revise else 'ok',issues=['fragment'] if revise else ['uncertain_source'] if confidence=='material' else [],
                             reason='Concrete acoustic/semantic explanation',disputed=confidence=='material',
                             source_assessment=dict(confidence=confidence,reading=e['primary_text'],evidence_id=e['identity'],reason='Equivalent supported grammar' if confidence=='minor' else 'Material alternative remains',parts=parts or [])))
            if revise:rows[-1]['english']=revise
        return {'schema':'aidub.review_response.v1','job_id':request['job_id'],'translator':{'kind':'fake','model':'fake'},'segments':rows}

    def invoke(self,spec,request,root,role,current,cfg,**kw):
        self.calls.append(request)
        return self.response(request)

    def run_resolution(self,invoke=None,hearing=None):
        with JobLock(self.job.dir):
            with patch('aidub.source_resolution.invoke_batches',side_effect=invoke or self.invoke):
                resolve_sources(self.job,self.cfg,{'review':{'kind':'command'}},hearing=hearing or self.hear)

    def test_minor_supported_meaning_eligible_in_all_consumers(self):
        self.run_resolution()
        self.assertEqual(len(self.calls),1);self.assertEqual(len(self.hearings),1)
        s=self.job.data['timeline'][0]
        self.assertEqual(eligibility(s,self.cfg,'mic')['source_confidence'],'minor')
        self.assertIsNone(voicing_uncertainty(s,self.cfg,'mic'))
        self.assertEqual(source_uncertainty_issues({},[s],self.cfg,'mic'),[])
        with patch('aidub.pipeline.lookup_cache',return_value=None) as cache:
            self.assertEqual(_cache_misses([s],self.cfg,Path('unused'),'ref','text',5,'mic'),[1])
            cache.assert_called_once()
        self.assertEqual(s['english'],'Well, come on, come on.')
        self.assertEqual(s['source_resolution_history'][0]['translation_review']['status'],'disputed')

    def test_true_negation_not_cleared_by_context_only(self):
        self.seg.update(spanish='No recuerdo los juguetes',asr_alternatives=[{'text':'Recuerdo los juguetes'}])
        self.seg['material_source_conflict']=material_conflict(self.seg)
        self.run_resolution(lambda spec,req,*args,**kw: self.response(req,'material'))
        self.assertEqual(load_state(self.job)['episodes'].popitem()[1]['rounds'],2)
        self.assertEqual(eligibility(self.seg,self.cfg,'mic')['synthesis'],'withheld')
        self.assertFalse(pending_source_resolution(self.job,self.cfg))
        self.assertIsNotNone(self.seg['material_source_conflict'])

    def test_revision_needs_exact_confirmation_without_extra_round(self):
        def invoke(spec,req,*args,**kw):
            self.calls.append(req)
            return self.response(req,revise='Well, let us go.' if len(self.calls)==1 else 'Well, come along.')
        self.run_resolution(invoke)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.seg['english'],'Well, come along.')
        self.assertEqual(self.seg['translation_review']['status'],'revised_unconfirmed')
        self.assertEqual(eligibility(self.seg,self.cfg,'mic')['synthesis'],'withheld')
        self.assertFalse(pending_source_resolution(self.job,self.cfg))
        self.run_resolution(lambda *a,**k: self.fail('budget reset'))

    def test_revision_followed_by_ok_is_confirmed_exactly(self):
        def invoke(spec,req,*args,**kw):
            self.calls.append(req)
            return self.response(req,revise='Well, let us go.' if len(self.calls)==1 else None)
        self.run_resolution(invoke)
        self.assertEqual(self.calls[1]['segments'][0]['english'],'Well, let us go.')
        self.assertEqual(eligibility(self.seg,self.cfg,'mic')['synthesis'],'full')

    def test_resume_preserves_pending_identity_and_budget(self):
        def interrupt(*args,**kw):
            self.calls.append(args[1]);raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):self.run_resolution(interrupt)
        self.job=Job(self.job.dir)
        pending=load_state(self.job)['pending']
        self.run_resolution()
        self.assertEqual(self.calls[0],self.calls[1])
        self.assertEqual(load_state(self.job)['requests'][0]['identity'],pending['identity'])
        self.assertEqual(len(self.hearings),1)
        self.assertFalse(pending_source_resolution(self.job,self.cfg))
        self.run_resolution(lambda *a,**k:self.fail('accepted response repeated'))

    def test_manifest_acceptance_recovers_lagging_sidecar(self):
        def capture(spec,req,*args,**kw):
            self.old_state=read_json(self.job.dir/'handoff/source_resolution/state.json')
            return self.response(req)
        self.run_resolution(capture)
        write_json(self.job.dir/'handoff/source_resolution/state.json',self.old_state)
        self.job=Job(self.job.dir)
        self.assertNotIn('pending',load_state(self.job))
        self.assertFalse(pending_source_resolution(self.job,self.cfg))

    def test_incomplete_hearing_never_repeated_or_approved(self):
        def fail(*args):self.hearings.append(1);raise TimeoutError('original acoustic timeout')
        self.run_resolution(lambda spec,req,*args,**kw:self.response(req,'material'),fail)
        self.assertEqual(len(self.hearings),1)
        entry=next(iter(load_state(self.job)['episodes'].values()))
        self.assertFalse(entry['evidence']['complete'])
        self.assertIn('original acoustic timeout',entry['evidence']['error'])
        self.run_resolution(lambda *a,**k:self.fail('exhausted budget repeated'),fail)
        self.assertEqual(len(self.hearings),1)

    def test_stale_mic_span_alternatives_text_or_evidence_rejected(self):
        self.run_resolution();original=copy.deepcopy(self.seg)
        for change in ('mic','span','alternatives','text','evidence'):
            s=copy.deepcopy(original);mic='mic'
            if change=='mic':mic='different'
            if change=='span':s['end']+=.1
            if change=='alternatives':s['asr_alternatives']=[{'text':'No vamos'}]
            if change=='text':s['english']='Different.'
            if change=='evidence':s['source_resolution']['evidence']['inside']['text']='Changed'
            self.assertEqual(eligibility(s,self.cfg,mic)['synthesis'],'withheld',change)

    def test_supported_clause_has_lineage_and_visible_remainder(self):
        self.seg['source_words'][2]['probability']=.1
        self.seg['source_words'][1]['word']='vamos,'
        parts=[{'word_range':[0,2],'english':'Well, come on.'}]
        def invoke(spec,req,*args,**kw):
            self.calls.append(req)
            return self.response(req,'supported_spans',revise='Well, come on.' if len(self.calls)==1 else None,parts=parts)
        self.run_resolution(invoke)
        children=self.job.data['timeline']
        spoken=[s for s in children if not s.get('source_remainder')]
        self.assertEqual(len(spoken),1);self.assertEqual(spoken[0]['source_lineage']['parent_id'],1)
        self.assertEqual(eligibility(spoken[0],self.cfg,'mic')['synthesis'],'supported_spans')
        self.assertTrue(any(s.get('source_remainder') for s in children))
        self.assertTrue(source_uncertainty_issues({},children,self.cfg,'mic'))
        self.assertEqual(len(self.job.data['source_resolution_parents']),1)
        self.run_resolution(lambda *a,**k:self.fail('split repeated'))

    def test_parts_cannot_drop_confirmed_hesitation(self):
        self.seg['required_event_prefix']='Uh...'
        def invoke(spec,req,*args,**kw):return self.response(req,'supported_spans',revise='Well, come on.',parts=[{'word_range':[0,2],'english':'Well, come on.'}])
        with self.assertRaisesRegex(RuntimeError,'event-bearing'):self.run_resolution(invoke)

    def test_noise_cannot_become_hesitation_or_lexical_speech(self):
        self.job.data['timeline']=[];self.job.save()
        write_json(self.job.dir/'transcribe/vocal_events.json',{'events':[dict(id='unknown',start=1.,end=1.5,kind='unknown',disposition='unresolved')]})
        def invoke(spec,req,*args,**kw):return self.response(req,'supported')
        with self.assertRaisesRegex(RuntimeError,'near-silent'):self.run_resolution(invoke)
        self.assertEqual(self.job.data['timeline'],[])

    def test_nonblocking_primary_confirmation_reuses_evidence(self):
        self.seg['translation_review']['status']='revised_unconfirmed'
        self.run_resolution(hearing=lambda *a:self.fail('unnecessary new hearing'))
        e=self.seg['source_resolution']['evidence']
        self.assertEqual(e['contextual']['provenance']['kind'],'primary_source_words')
        self.assertEqual(eligibility(self.seg,self.cfg,'mic')['synthesis'],'full')

    def test_overlapping_boundaries_block_before_provider_or_synthesis(self):
        a=copy.deepcopy(self.seg);b=copy.deepcopy(a);b.update(id=2,start=1.5,end=2.,spanish='vamos')
        self.job.data['timeline']=[a,b];self.job.save()
        self.assertFalse(pending_source_resolution(self.job,self.cfg))
        self.run_resolution(lambda *a,**k:self.fail('boundary needs scoped correction'))
        self.assertTrue(all(eligibility(s,self.cfg,'mic')['synthesis']=='withheld' for s in self.job.data['timeline']))
        diagnostics=boundary_diagnostics([a,b]);self.assertEqual(diagnostics[1]['issues'][0]['kind'],'overlapping_duplicate')
        b.update(start=3.2,end=3.5,spanish='vamos',source_words=[dict(word='vamos',start=3.2,end=3.5,probability=.9)])
        self.assertFalse(boundary_diagnostics([a,b]))

    def test_legacy_snapshots_do_not_enable_resolution_on_resume(self):
        self.assertFalse(settings({'source_events':{'enabled':True}}))
        self.assertFalse(pending_source_resolution(self.job,{'source_events':{'enabled':True}}))



    def test_source_reason_is_equivalent_in_nested_field_but_semantic_checks_stay(self):
        self.job.data['timeline']=[];self.job.save()
        ledger={'events':[dict(id='unknown',start=1.,end=1.5,kind='unknown',disposition='unresolved')]}
        write_json(self.job.dir/'transcribe/vocal_events.json',ledger)
        def invoke(spec,req,*a,**kw):
            response=self.response(req,'material')
            response['segments'][0].pop('reason')
            self.assertEqual(validate_review_response(req,response,{req['segments'][0]['id']:''}),[])
            bad=copy.deepcopy(response);bad['segments'][0]['disputed']=False
            self.assertTrue(validate_review_response(req,bad,{req['segments'][0]['id']:''}))
            return response
        self.run_resolution(invoke)
        self.assertEqual(self.job.data['timeline'],[])

    def test_saved_response_revalidated_without_relabeling_or_call(self):
        from aidub.batches import request_batches
        from aidub.source_resolution import saved_source_response
        from aidub.util import fingerprint
        req={'schema':'aidub.review_request.v1','job_id':'test','source_resolution_policy':RESOLUTION_POLICY,
             'segments':[{'id':1,'english':'Well, come on, come on.','source_evidence':{
                 'identity':'e','complete':True,'primary_text':self.seg['spanish'],'primary_words':self.seg['source_words']},'source_span':[1.,3.]}]}
        limits=self.cfg.get('batching') or {}
        batch=request_batches(req,max_cues=int(limits.get('max_cues',40)),max_chars=int(limits.get('max_chars',24000)))[0]
        response=self.response(batch)
        response['translator']={'kind':'command','model':'gpt-6-luna','provenance':{'model':'gpt-6-luna','reasoning':'medium','auth':'chatgpt','original_marker':'retain'}}
        root=self.job.dir/'handoff/source_resolution';directory=root/'responses/batches/review'/fingerprint(req)/'batch_0000/response_attempts/original'
        request_path=directory/'attempt_01_request.json';response_path=directory/'attempt_01_response.json'
        write_json(request_path,batch);write_json(response_path,response)
        write_json(directory/'state.json',{'attempts':[{'request_path':str(request_path),'response_path':str(response_path),'status':'invalid_response'}]})
        recovered,history=saved_source_response(root,req,dict(kind='codex_chatgpt',model='gpt-6-luna',reasoning='medium',auth='chatgpt'),self.cfg)
        self.assertTrue(history);self.assertEqual(recovered['translator'],response['translator'])
        self.assertEqual(read_json(response_path),response)


    def test_invalid_row_does_not_poison_supported_neighbor_after_exhaustion(self):
        from aidub.batches import request_batches
        from aidub.source_resolution import saved_source_response
        from aidub.util import fingerprint
        source={'id':1,'english':'Well, come on, come on.','source_evidence':{
                 'identity':'e','complete':True,'primary_text':self.seg['spanish'],'primary_words':self.seg['source_words']},'source_span':[1.,3.]}
        other=copy.deepcopy(source);other['id']=2
        req={'schema':'aidub.review_request.v1','job_id':'test','source_resolution_policy':RESOLUTION_POLICY,'segments':[source,other]}
        limits=self.cfg.get('batching') or {}
        batch=request_batches(req,max_cues=int(limits.get('max_cues',40)),max_chars=int(limits.get('max_chars',24000)))[0]
        response=self.response(batch);response['segments'][1]['disputed']=True
        root=self.job.dir/'handoff/source_resolution';directory=root/'responses/batches/review'/fingerprint(req)/'batch_0000/response_attempts/original'
        rp=directory/'attempt_01_request.json';sp=directory/'attempt_01_response.json'
        write_json(rp,batch);write_json(sp,response)
        write_json(directory/'state.json',{'status':'attempts_exhausted','attempts':[{'request_path':str(rp),'response_path':str(sp)}]})
        recovered,_=saved_source_response(root,req,{'kind':'command'},self.cfg)
        self.assertEqual([r['id'] for r in recovered['segments']],[1])
        self.assertEqual(set(recovered['source_invalid_rows']),{'2'})
        # An invalid row is an explicit abstention, never an approved substitute.
        self.assertEqual(read_json(sp),response)

    def test_compact_confirmation_rebinds_only_unchanged_source(self):
        from aidub.fidelity import reconfirm_resolution
        self.run_resolution()
        self.seg['english']='Well, let us go.'
        self.assertEqual(eligibility(self.seg,self.cfg,'mic')['synthesis'],'withheld')
        self.assertFalse(reconfirm_resolution(self.seg,'mic','Wrong text','audit'))
        self.assertTrue(reconfirm_resolution(self.seg,'mic','Well, let us go.','audit'))
        self.seg['translation_review']={'status':'revised_confirmed','checked_text':'Well, let us go.'}
        self.assertEqual(eligibility(self.seg,self.cfg,'mic')['synthesis'],'full')
        self.seg['end']+=.2
        self.assertFalse(reconfirm_resolution(self.seg,'mic','Well, let us go.','audit'))


    def test_targeted_neighbors_are_actual_timeline_not_other_disputes(self):
        neighbor=copy.deepcopy(self.seg);neighbor.update(id=2,start=3.5,end=4.,spanish='Vecino real',english='Actual neighbor.',translation_review={'status':'accepted_draft','checked_text':'Actual neighbor.'})
        other=copy.deepcopy(self.seg);other.update(id=3,start=4.2,end=4.8,spanish='Otro',english='Another.',source_words=[dict(word='Otro',start=4.25,end=4.6,probability=.95)])
        self.job.data['timeline']=[self.seg,neighbor,other];self.job.save()
        def invoke(spec,req,*a,**kw):
            row=next(r for r in req['segments'] if r['id']==1)
            self.assertEqual(row['context_after'][0]['id'],2)
            self.assertEqual(row['context_after'][0]['english'],'Actual neighbor.')
            return self.response(req)
        self.run_resolution(invoke)


    def test_malformed_supported_parts_rejected_without_validator_crash(self):
        e={'identity':'e','complete':True,'primary_text':'Bueno','primary_words':self.seg['source_words']}
        src={'id':1,'source_span':[1.,3.],'source_evidence':e}
        for parts in ([None],[{'word_range':[0,2],'english':None}]):
            row={'verdict':'revise','english':None,'issues':['fragment'],'disputed':False,
                 'source_assessment':dict(confidence='supported_spans',reading='Bueno',evidence_id='e',reason='Test malformed field',parts=parts)}
            self.assertTrue(assessment_errors(row,src,'Well.'))

    def test_normal_auto_resolves_before_media_under_owned_lock(self):
        from contextlib import ExitStack
        from aidub.pipeline import run_job, translation_fingerprint
        from aidub.unattended import run_unattended
        self.cfg['jobs_dir']=str(self.root)
        self.cfg['providers']={role:{'kind':'command','command':['/bin/false'],'max_attempts':1}
                               for role in ('context','translation','review','repair','back_translation')}
        write_json(self.job.dir/'config.json',self.cfg)
        self.job.stage('translation').update(status='complete',fingerprint=translation_fingerprint(self.job.data['timeline']))
        self.job.save()
        events=[]
        def invoke(spec,req,*args,**kw):
            with self.assertRaisesRegex(RuntimeError,'locked'):
                with JobLock(self.job.dir): pass
            events.append('source_review')
            return self.response(req)
        def schedule(job,cfg):
            events.append('schedule')
            self.assertEqual(eligibility(job.data['timeline'][0],cfg,'mic')['synthesis'],'full')
            return {'needs_repair':[]}
        def validate(job,cfg,summary,gain):
            events.append('validate');job.state='complete';job.save()
            return {'english_video':'fake'}
        from unittest.mock import Mock
        worker=Mock(side_effect=self.hear);worker.close=Mock()
        with ExitStack() as stack:
            for name in ('inspect','extract','transcribe'):
                stack.enter_context(patch('aidub.pipeline.stage_'+name,return_value={}))
            stack.enter_context(patch('aidub.pipeline.stage_schedule',side_effect=schedule))
            stack.enter_context(patch('aidub.pipeline.stage_mix',side_effect=lambda *a:events.append('mix') or {}))
            stack.enter_context(patch('aidub.pipeline.stage_validate',side_effect=validate))
            stack.enter_context(patch('aidub.pipeline._risk_report'))
            stack.enter_context(patch('aidub.unattended.require_synthesis_ready'))
            stack.enter_context(patch('aidub.source_resolution.invoke_batches',side_effect=invoke))
            stack.enter_context(patch('aidub.pipeline._SecondHearing',return_value=worker))
            self.assertEqual(run_job(self.job),2)
            self.assertEqual(events,[])
            self.assertEqual(run_unattended(self.cfg,'unused','job'),0)
            self.assertEqual(events,['source_review','schedule','mix','validate'])
            self.assertEqual(run_unattended(self.cfg,'unused','job'),0)
            self.assertEqual(events.count('source_review'),1)
        worker.close.assert_called_once()

    def test_near_silent_unknown_can_be_accounted_without_inventing_speech(self):
        from aidub.events import event_placement_report
        from aidub.fidelity import region_is_resolved
        self.job.data['timeline']=[];self.job.save()
        sf.write(self.job.dir/'extract/mic_raw.wav',np.zeros(5000),1000)
        ledger={'mic_sha256':'mic','events':[dict(id='unknown',start=1.,end=1.5,kind='unknown',disposition='unresolved')]}
        write_json(self.job.dir/'transcribe/vocal_events.json',ledger)
        self.run_resolution(lambda spec,req,*a,**kw:self.response(req,'non_speech'),hearing=lambda *a:{'text':'','segments':[]})
        report=event_placement_report(ledger,[],self.job.data['source_region_resolutions'])
        self.assertEqual(report['unresolved'],[])
        self.assertEqual(ledger['events'][0]['disposition'],'unresolved')
        region=next(iter(self.job.data['source_region_resolutions'].values()))['region']
        self.assertFalse(region_is_resolved(region,self.job.data['source_region_resolutions'],'different-mic'))

    def test_cached_second_hearing_keeps_original_identity_and_no_new_request(self):
        from aidub.second_pass import settings as hs
        from aidub.util import fingerprint
        settings=hs(self.cfg);identity='abc123abc123abc123'
        window=[.65,3.35]
        audit={'identity':identity,'settings':settings,'targets':[{'kind':'uncertain_cue','id':8,'first_pass':self.seg['spanish'],'window':window}]}
        write_json(self.job.dir/'transcribe/second_pass.json',audit)
        words=[dict(w,no_speech_prob=0.) for w in self.seg['source_words']]
        write_json(self.job.dir/'transcribe/second_pass'/identity[:16]/'cue_8.json',{'window':window,'words':words,'text':self.seg['spanish']})
        self.run_resolution(hearing=lambda *a:self.fail('identical hearing repeated'))
        e=self.seg['source_resolution']['evidence']
        self.assertEqual(e['contextual']['provenance']['kind'],'saved_second_pass')
        self.assertEqual(e['contextual']['provenance']['hearing_identity'],identity)


class PolicyTests(unittest.TestCase):
    def test_discourse_markers_do_not_negate_proposition(self):
        for first,other in [('Nada, me gustaría saber','Me gustaría saber'),('Es como una sabana africana','Es como una sabana africana, ¿no?')]:
            self.assertIsNone(material_conflict(dict(spanish=first,asr_alternatives=[{'text':other}])))
        for first,other in [('No recuerdo los juguetes','Recuerdo los juguetes'),('Nada funciona','Funciona'),('No me deja interactuar','Me deja interactuar')]:
            self.assertIsNotNone(material_conflict(dict(spanish=first,asr_alternatives=[{'text':other}])))

    def test_context_only_cannot_override_true_conflict(self):
        src=dict(id=1,spanish='No recuerdo juguetes',source_span=[0,2],asr_alternatives=[{'text':'Recuerdo juguetes'}],
                 source_evidence={'identity':'e','complete':True,'primary_text':'No recuerdo juguetes','primary_words':[{'word':'No','probability':.9}],
                                  'contextual':{'provenance':{'kind':'primary_source_words'}},'inside':{'text':'No recuerdo juguetes','words':[{'word':'No','probability':.9}]}})
        row=dict(verdict='ok',issues=[],disputed=False,source_assessment=dict(confidence='supported',reading='No recuerdo juguetes',reason='Context agrees',parts=[],evidence_id='e'))
        self.assertTrue(any('contextual' in e for e in assessment_errors(row,src,'I cannot remember toys.')))

    def test_resolution_contract_is_scoped_to_review_not_translation(self):
        import importlib.util
        path=Path(__file__).resolve().parents[1]/'scripts/provider_codex.py'
        spec=importlib.util.spec_from_file_location('batch5_codex_schema',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        req={'job_id':'j','source_resolution_policy':RESOLUTION_POLICY}
        schema=module._schema('review',req)
        self.assertIn('source_assessment',schema['properties']['segments']['items']['required'])
        del req['source_resolution_policy']
        self.assertNotIn('source_assessment',module._schema('review',req)['properties']['segments']['items']['properties'])


if __name__=='__main__':unittest.main()
