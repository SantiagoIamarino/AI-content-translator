#!/usr/bin/env python3
"""Harmless operational supervisor checks; no aidub provider/model is called."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.overnight as overnight
from scripts.overnight import run_supervisor


ROOT = Path(__file__).resolve().parents[1]


class OvernightSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aidub-overnight-test-")
        self.base = Path(self.tmp.name)
        self.jobs = self.base / "jobs"
        self.jobs.mkdir()
        self.video = self.base / "tiny-source.fixture"
        self.video.write_text("harmless fixture\n")
        self.config = self.base / "config.json"
        self.config.write_text(json.dumps({"jobs_dir": str(self.jobs)}))
        self.name = "test-" + self.base.name[-8:]
        self.job_dir = self.jobs / self.name
        self.logs = ROOT / "runs" / "overnight" / self.name
        self.worker = self.base / "worker.py"
        self.worker.write_text(r'''import json, os, signal, sys, time
from pathlib import Path
name = os.environ["AIDUB_TEST_NAME"]
job = Path(os.environ["AIDUB_TEST_JOBS"]) / name
job.mkdir(parents=True, exist_ok=True)
counter = Path(os.environ["AIDUB_TEST_COUNTER"])
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
scenario = os.environ.get("AIDUB_TEST_SCENARIO", "success")
def save(state, error=None):
    (job / "manifest.json").write_text(json.dumps({"job_id": name, "state": state, "error": error,
      "stages": {"transcribe": {"status": "complete"}}, "timeline": []}))
if scenario == "transient" and n == 0:
    save("failed", "worker exited unexpectedly")
    print("worker exited unexpectedly", flush=True)
    raise SystemExit(86)
if scenario == "permanent":
    save("failed", "Invalid configuration: unusable fixture")
    raise SystemExit(1)
if scenario == "exhausted":
    save("failed", "worker exited unexpectedly")
    raise SystemExit(86)
if scenario == "provider_uncertain":
    p = job / "handoff/batches/translation/id/batch_001/response_attempts/x/state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"role": "translation", "status": "invoking", "attempts": [{"status": "invoking", "started_at": time.time()}]}))
    save("running")
    raise SystemExit(137)
if scenario == "partial":
    save("partial")
    raise SystemExit(3)
if scenario == "slow":
    time.sleep(float(os.environ.get("AIDUB_TEST_DELAY", "0.2")))
if scenario == "inhibitor":
    if not Path(os.environ["AIDUB_TEST_INHIBITOR"]).is_file():
        raise SystemExit("sleep inhibitor did not cover worker")
if scenario == "interrupt":
    def on_int(_sig, _frame):
        (job / "checkpoint.fixture").write_text("retained")
        raise SystemExit(130)
    signal.signal(signal.SIGINT, on_int)
    while True: time.sleep(0.1)
save("complete")
raise SystemExit(0)
''')
        self.inhibitor = self.base / "inhibitor.py"
        self.inhibitor.write_text(r'''import os, subprocess, sys
from pathlib import Path
marker = Path(os.environ["AIDUB_TEST_INHIBITOR"])
marker.write_text("held")
try: raise SystemExit(subprocess.run(sys.argv[1:]).returncode)
finally: marker.unlink(missing_ok=True)
''')

    def tearDown(self):
        import shutil
        self.tmp.cleanup()
        shutil.rmtree(self.logs, ignore_errors=True)

    def args(self, resume=False, retries=2):
        return Namespace(config=str(self.config), name=self.name, video=str(self.video), preset=None,
                         mic=2, game=1, mixed=0, max_process_retries=retries, resume=resume,
                         retry_delays_seconds=[0, 1])

    def prefixes(self, scenario):
        env = os.environ.copy()
        env.update(AIDUB_TEST_NAME=self.name, AIDUB_TEST_JOBS=str(self.jobs),
                   AIDUB_TEST_COUNTER=str(self.base / "counter"), AIDUB_TEST_SCENARIO=scenario,
                   AIDUB_TEST_INHIBITOR=str(self.base / "inhibitor-held"))
        self.addCleanup(lambda: None)
        self._env = env
        return ([sys.executable, str(self.worker)], [sys.executable, str(self.inhibitor)])

    def invoke(self, scenario, *, resume=False, retries=2, interval=0.05):
        worker, inhibitor = self.prefixes(scenario)
        old = os.environ.copy()
        os.environ.update(self._env)
        args = self.args(resume, retries)
        if resume:
            args.video = None
        try:
            return run_supervisor(args, worker_prefix=worker,
                                  inhibitor_prefix=inhibitor, monitor_interval=interval)
        finally:
            os.environ.clear(); os.environ.update(old)

    def test_normal_success_and_inhibitor_release(self):
        self.assertEqual(self.invoke("success"), 0)
        self.assertFalse((self.base / "inhibitor-held").exists())
        self.assertEqual(json.loads((self.logs / "operational-report.json").read_text())["status"], "complete")
        self.assertTrue((self.logs / "console.log").is_file())

    def test_inhibitor_covers_active_worker(self):
        self.assertEqual(self.invoke("inhibitor"), 0)
        self.assertFalse((self.base / "inhibitor-held").exists())

    def test_transient_process_failure_resumes_same_job(self):
        self.assertEqual(self.invoke("transient"), 0)
        self.assertEqual((self.base / "counter").read_text(), "2")
        events = [json.loads(x) for x in (self.logs / "events.jsonl").read_text().splitlines()]
        self.assertTrue(any(x["event"] == "recovery_wait_started" for x in events))

    def test_permanent_failure_stops_without_retry(self):
        self.assertEqual(self.invoke("permanent"), 1)
        self.assertEqual((self.base / "counter").read_text(), "1")
        self.assertEqual(json.loads((self.logs / "operational-report.json").read_text())["status"],
                         "human_intervention_required")

    def test_process_retry_budget_exhaustion(self):
        self.assertEqual(self.invoke("exhausted", retries=0), 86)
        self.assertEqual((self.base / "counter").read_text(), "1")

    def test_uncertain_provider_call_is_not_retried_by_supervisor(self):
        self.assertEqual(self.invoke("provider_uncertain"), 137)
        report = json.loads((self.logs / "operational-report.json").read_text())
        self.assertEqual(report["last_worker_exit"]["category"], "provider_handoff")
        self.assertEqual((self.base / "counter").read_text(), "1")

    def test_missing_source_is_blocked_and_saved_identity_can_resume(self):
        worker, inhibitor = self.prefixes("success")
        missing = self.base / "unmounted" / "recording.mkv"
        args = self.args()
        args.video = str(missing)
        old = os.environ.copy(); os.environ.update(self._env)
        try:
            self.assertEqual(run_supervisor(args, worker_prefix=worker, inhibitor_prefix=inhibitor), 75)
        finally:
            os.environ.clear(); os.environ.update(old)
        self.assertEqual(json.loads((self.logs / "operational-report.json").read_text())["status"], "blocked")
        missing.parent.mkdir(); missing.write_text("mounted fixture")
        self.assertEqual(self.invoke("success", resume=True), 0)
        self.assertEqual(json.loads((self.logs / "launch.json").read_text())["video"], str(missing.resolve()))

    def test_interruption_keeps_checkpoint_and_resume_uses_saved_identity(self):
        worker, inhibitor = self.prefixes("interrupt")
        runner = self.base / "runner.py"
        runner.write_text('''import sys\nfrom argparse import Namespace\nfrom scripts.overnight import run_supervisor\na=Namespace(config=sys.argv[1],name=sys.argv[2],video=sys.argv[3],preset=None,mic=2,game=1,mixed=0,max_process_retries=2,retry_delays_seconds=[0,1],resume=False)\nraise SystemExit(run_supervisor(a,worker_prefix=sys.argv[4:6],inhibitor_prefix=sys.argv[6:8],monitor_interval=0.05))\n''')
        env = self._env.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.Popen([sys.executable, str(runner), str(self.config), self.name, str(self.video),
                                 *worker, *inhibitor], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, cwd=ROOT)
        deadline = time.time() + 5
        while not (self.logs / "events.jsonl").exists() and time.time() < deadline: time.sleep(0.02)
        time.sleep(0.15)
        proc.send_signal(2)
        out, _ = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 130, out)
        self.assertTrue((self.job_dir / "checkpoint.fixture").is_file())
        self.assertEqual(self.invoke("success", resume=True), 0)
        self.assertEqual((self.base / "counter").read_text(), "2")

    def test_duplicate_supervisor_lock_is_rejected(self):
        self.logs.mkdir(parents=True, exist_ok=True)
        lock = (self.logs / "SUPERVISOR.lock").open("a+")
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        worker, inhibitor = self.prefixes("success")
        old = os.environ.copy(); os.environ.update(self._env)
        try:
            self.assertEqual(run_supervisor(self.args(), worker_prefix=worker, inhibitor_prefix=inhibitor), 75)
        finally:
            os.environ.clear(); os.environ.update(old); lock.close()

    def test_slow_healthy_work_is_not_killed(self):
        self.assertEqual(self.invoke("slow"), 0)

    def test_partial_is_terminal(self):
        self.assertEqual(self.invoke("partial"), 3)
        self.assertEqual((self.base / "counter").read_text(), "1")

    def test_fallback_migrates_only_provider_mapping_once(self):
        import copy
        job = self.job_dir
        job.mkdir(parents=True)
        old = {"preset": "performance", "quality": {"max_retries": 2},
               "providers": {"translation": {"kind": "command", "command": ["cursor-agent"]},
                             "repair": {"kind": "same_as", "role": "translation"}}}
        (job / "config.json").write_text(json.dumps(old))
        adapter = ROOT / "scripts/provider_codex.py"
        python = sys.executable
        luna = {"kind": "command", "command": [python, str(adapter), "--request", "{request}",
                 "--response", "{response}", "--role", "{role}"], "timeout_sec": 900,
                "max_attempts": 2}
        fallback = self.base / "fallback.json"
        fallback.write_text(json.dumps({"providers": {"translation": luna, "repair": luna,
            "context": {"kind": "same_as", "role": "translation"},
            "review": {"kind": "same_as", "role": "repair"},
            "back_translation": {"kind": "same_as", "role": "repair"}}}))
        launch = {"fallback_config": str(fallback)}
        self.logs.mkdir(parents=True, exist_ok=True)
        launch_path = self.logs / "launch.json"
        report_path = self.logs / "operational-report.json"
        events = self.logs / "events.jsonl"
        changed, _ = overnight.apply_provider_fallback(launch, job, launch_path, report_path, events)
        self.assertTrue(changed)
        migrated = json.loads((job / "config.json").read_text())
        self.assertEqual(migrated["preset"], old["preset"])
        self.assertEqual(migrated["quality"], old["quality"])
        self.assertEqual(migrated["providers"], json.loads(fallback.read_text())["providers"])
        self.assertTrue(launch["provider_fallback_applied_at"])
        self.assertFalse(overnight.apply_provider_fallback(launch, job, launch_path, report_path, events)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
