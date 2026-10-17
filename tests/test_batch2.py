"""Compact-review orchestration with cached fixtures and fake media only."""
import copy
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from aidub.config import load_config
from aidub.fidelity import voicing_uncertainty
from aidub.job import Job, JobLock
from aidub.pipeline import _save_timeline, accept_repair, next_hint, run_job, translation_fingerprint
from aidub.providers import ProviderError
from aidub.unattended import run_unattended
from aidub.util import read_json, write_json


class CompactReviewOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = load_config()
        self.cfg['jobs_dir'] = str(self.root)
        self.cfg['source_events'] = {'enabled': True}
        # Isolate batch-2 compact review budgets from the separately tested
        # batch-5 source-resolution handoff enabled for new performance jobs.
        self.cfg['source_resolution'] = {'enabled': False}
        self.cfg['translation_quality'] = {'enabled': True, 'review': {
            'enabled': True, 'max_rounds': 2, 'back_translation': 'disputed'}}
        # Even an accidentally unmocked invocation cannot contact a provider.
        spec = {'kind': 'command', 'command': [sys.executable, '-c',
                'raise AssertionError("test provider must be mocked")'], 'max_attempts': 1}
        self.cfg['providers'] = {r: copy.deepcopy(spec) for r in
                                 ('translation', 'repair', 'context', 'review', 'back_translation')}
        self.job = Job.create(self.root / 'batch2', 'batch2', str(self.root / 'unused.mp4'), self.cfg)
        self.job.data['timeline'] = [{
            'id': 1, 'start': 1., 'end': 5., 'spanish': 'Espero que no me haya visto.',
            'notes': '', 'uncertain_words': [], 'english': "Hope I'm not seen.",
            'revisions': [{'action': 'revise', 'from': "I hope it hasn't seen me.",
                           'to': "Hope I'm not seen.", 'reason': 'compact'}],
            'translation_review': {'status': 'accepted_draft', 'checked_text': "I hope it hasn't seen me."}}]
        self.job.set_stage('translation', 'complete', translation_fingerprint(self.job.data['timeline']))
        _save_timeline(self.job)
        write_json(self.job.dir / 'inspect/probe.json', {'described': {'video': {'duration': 10.}}})
        self.fixtures = read_json(Path(__file__).parent / 'fixtures/compact_repair_review.json')
        self.events = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ('inspect', 'extract', 'transcribe'):
            self.stack.enter_context(patch('aidub.pipeline.stage_' + name, return_value={}))
        self.stack.enter_context(patch('aidub.pipeline.stage_schedule', side_effect=self.schedule))
        self.stack.enter_context(patch('aidub.pipeline.stage_mix', side_effect=self.mix))
        self.stack.enter_context(patch('aidub.pipeline.stage_validate', side_effect=self.validate))
        self.stack.enter_context(patch('aidub.pipeline._risk_report'))
        self.stack.enter_context(patch('aidub.unattended.require_synthesis_ready'))
        self.no_work = []
        for name in ('get_shared_backend', 'synthesize_cached', 'run_cmd', 'AsrClient'):
            guard = self.stack.enter_context(patch('aidub.pipeline.' + name,
                side_effect=AssertionError('No models or media execution in batch-2 tests')))
            self.no_work.append(guard)

    def tearDown(self):
        for guard in self.no_work:
            guard.assert_not_called()

    def provider(self, spec, request_path, response_path, role):
        self.assertEqual(role, 'review')
        # The outer job lock must stay owned during invocation and acceptance.
        with self.assertRaisesRegex(RuntimeError, 'locked'):
            with JobLock(self.job.dir):
                pass
        request = read_json(request_path)
        self.assertEqual(Job(self.job.dir).state, 'awaiting_repair_review')
        self.events.append(('review', request['round']))
        if request['round'] == 2:
            self.assertEqual(request['segments'][0]['english'], "Hope it hasn't seen me.")
        response = copy.deepcopy(self.fixtures[str(request['round'])])
        write_json(response_path, response)
        return response

    def schedule(self, job, cfg):
        seg = job.data['timeline'][0]
        uncertainty = voicing_uncertainty(seg, cfg)
        self.events.append(('schedule', seg['english'], uncertainty))
        if uncertainty is None:
            self.assertEqual(seg['translation_review']['checked_text'], seg['english'])
        return {'needs_repair': [], 'blocked': uncertainty is not None}

    def mix(self, job, cfg, summary):
        self.events.append(('mix',))
        return {}

    def validate(self, job, cfg, summary, gain):
        self.events.append(('validate',))
        job.state = 'partial' if summary['blocked'] else 'complete'
        job.save()
        return {'english_video': 'fake-only-no-export.mp4'}

    def auto(self):
        return run_unattended(self.cfg, self.job.data['video'], 'batch2')

    def states(self):
        return {str(p.relative_to(self.job.dir)): read_json(p) for p in
                self.job.dir.glob('handoff/repair_reviews/**/response_attempts/*/state.json')}

    def test_manual_handoff_stops_before_schedule_or_finalization(self):
        with patch('aidub.providers.invoke_provider', side_effect=AssertionError('manual cannot invoke')) as call:
            with JobLock(self.job.dir) as lock:
                self.assertEqual(run_job(self.job, lock=lock), 2)
                self.assertTrue(lock.owns(self.job.dir))
            self.assertEqual(run_job(Job(self.job.dir)), 2)
        call.assert_not_called()
        self.assertEqual(self.events, [])
        self.assertEqual(Job(self.job.dir).state, 'awaiting_repair_review')
        self.assertIn('exact current English', next_hint(Job(self.job.dir)))

    def test_review_precedes_schedule_and_finalization_and_resume_skips_accepted_calls(self):
        with patch('aidub.providers.invoke_provider', side_effect=self.provider) as call:
            self.assertEqual(self.auto(), 0)
            self.assertEqual(call.call_count, 2)
            before = self.states()
            self.assertEqual(self.auto(), 0)
            self.assertEqual(call.call_count, 2)
        self.assertEqual([e[0] for e in self.events[:5]], ['review', 'review', 'schedule', 'mix', 'validate'])
        self.assertEqual(self.events[2][1], "Hope it hasn't seen me.")
        self.assertEqual(self.states(), before)
        seg = Job(self.job.dir).data['timeline'][0]
        self.assertEqual(len(seg['revisions']), 1)
        self.assertEqual(len(seg['repair_review_history']), 1)
        self.assertEqual(seg['translation_review']['status'], 'revised_confirmed')
        # Review/resume cannot replenish the independent compact-revision budget.
        write_json(self.job.dir / 'handoff/repair_request.json', {'job_id': 'batch2', 'segments': [{'id': 1}]})
        response = self.job.dir / 'handoff/next_repair.fixture.json'
        write_json(response, {'schema': 'aidub.repair_response.v1', 'job_id': 'batch2',
                             'translator': {'kind': 'command'}, 'segments': [
                                 {'id': 1, 'action': 'revise', 'english': "Hope it missed me.", 'reason': 'compact'}]})
        with self.assertRaisesRegex(RuntimeError, 'already used its compact-revision budget'):
            accept_repair(Job(self.job.dir), response, revision_limit_n=1)

    def test_interrupted_acceptance_replays_cached_rounds_without_new_budget(self):
        with patch('aidub.providers.invoke_provider', side_effect=self.provider) as call:
            with patch('aidub.pipeline._save_timeline', side_effect=KeyboardInterrupt('before acceptance')):
                with self.assertRaises(KeyboardInterrupt):
                    self.auto()
            before = self.states()
            self.assertEqual(len(before), 2)
            self.assertEqual(Job(self.job.dir).state, 'awaiting_repair_review')
            self.assertEqual(self.auto(), 0)
            self.assertEqual(call.call_count, 2)
        after = self.states()
        for key, state in before.items():
            self.assertEqual(after[key]['attempts'], state['attempts'])
            # Read-only raw replay leaves historical attempt state untouched;
            # reuse provenance now lives in saved_decision_receipts.
            self.assertEqual(after[key].get('response_reuses', 0), state.get('response_reuses', 0))
        self.assertEqual(len(Job(self.job.dir).data['timeline'][0]['revisions']), 1)

    def test_failed_later_round_resume_keeps_accepted_response_and_exhausted_budget(self):
        def fail_second(spec, req, res, role):
            if read_json(req)['round'] == 2:
                raise ProviderError('fake failure, no durable response')
            return self.provider(spec, req, res, role)
        with patch('aidub.providers.invoke_provider', side_effect=fail_second) as call:
            with self.assertRaisesRegex(ProviderError, 'exhausted 1 attempts'):
                self.auto()
            before = self.states()
            with self.assertRaisesRegex(ProviderError, 'exhausted 1 attempts'):
                self.auto()
            self.assertEqual(call.call_count, 2)
        self.assertEqual(self.events, [('review', 1)])
        after = self.states()
        self.assertEqual(sorted(s['status'] for s in after.values()), ['attempts_exhausted', 'response_ready'])
        for key, state in before.items():
            self.assertEqual(after[key]['attempts'], state['attempts'])
        self.assertEqual(Job(self.job.dir).state, 'awaiting_repair_review')

    def test_unconfirmed_and_disputed_repairs_stay_blocked_across_resume(self):
        for verdict in ('revise', 'disputed'):
            with self.subTest(verdict=verdict):
                # Restore this temporary fixture job to its original pending text.
                _save_timeline(self.job)
                cfg = self.job.config()
                cfg['translation_quality']['review']['max_rounds'] = 1
                write_json(self.job.dir / 'config.json', {k: v for k, v in cfg.items() if not k.startswith('_')})
                if verdict == 'disputed':
                    self.fixtures['1']['segments'] = [{'id': 1, 'verdict': 'ok', 'issues': [],
                                                       'reason': 'Source unclear', 'disputed': True}]
                    # Separate exact-text request identity from the revise case.
                    self.job.data['timeline'][0]['english'] = 'Hope it does not see me.'
                    _save_timeline(self.job)
                self.events.clear()
                with patch('aidub.providers.invoke_provider', side_effect=self.provider) as call:
                    self.assertEqual(self.auto(), 3)
                    self.assertEqual(self.auto(), 3)
                    self.assertEqual(call.call_count, 1)
                self.assertEqual([e[0] for e in self.events[:4]], ['review', 'schedule', 'mix', 'validate'])
                self.assertIsNotNone(self.events[1][2])
                seg = Job(self.job.dir).data['timeline'][0]
                expected = 'disputed' if verdict == 'disputed' else 'revised_unconfirmed'
                self.assertEqual(seg['translation_review']['status'], expected)
                self.assertEqual(len(seg['revisions']), 1)

    def test_disabled_review_stops_without_media_or_provider(self):
        cfg = self.job.config()
        cfg['translation_quality']['review']['enabled'] = False
        write_json(self.job.dir / 'config.json', {k: v for k, v in cfg.items() if not k.startswith('_')})
        with patch('aidub.providers.invoke_provider') as call:
            self.assertEqual(self.auto(), 2)
        call.assert_not_called()
        self.assertEqual(self.events, [])
        self.assertEqual(Job(self.job.dir).state, 'awaiting_repair_review')

    def test_supervisor_recognizes_review_handoff_without_retrying_as_worker_failure(self):
        from scripts.overnight import failure_class
        category, _ = failure_class(2, {'state': 'awaiting_repair_review'}, '')
        self.assertEqual(category, 'provider_handoff')


if __name__ == '__main__':
    unittest.main()
