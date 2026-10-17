"""Measured execution facts; external attempt counts are not billing guarantees."""
import json
import resource
import time

from .util import read_json


def provider_metrics(job_dir):
    totals = {"attempts_started": 0, "uncertain_outcomes": 0, "response_reuses": 0, "batches_with_responses": 0}
    # Include nested source/compact review handoffs and context parts, retaining
    # each existing attempt record rather than counting aggregate responses.
    for path in (job_dir / 'handoff').rglob('response_attempts/*/state.json'):
        state = read_json(path)
        totals['attempts_started'] += len(state.get('attempts', []))
        totals['uncertain_outcomes'] += len(state.get('uncertain_outcomes', []))
        totals['response_reuses'] += state.get('response_reuses', 0)
        totals['batches_with_responses'] += state.get('status') == 'response_ready'
    return totals


def stage_call(job, name, function, *args):
    started = time.perf_counter()
    failed = False
    try:
        return function(*args)
    except BaseException:
        failed = True
        raise
    finally:
        row = {'stage': name, 'wall_seconds': time.perf_counter() - started, 'failed_or_interrupted': failed,
               'process_peak_ram_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
               'exited_child_peak_ram_bytes': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024}
        path = job.dir / 'report/stage_metrics.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row) + '\n')
