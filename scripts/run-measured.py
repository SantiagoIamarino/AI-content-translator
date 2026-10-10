#!/usr/bin/env python3
"""Linux child resource measurement without a system time package."""
import json
import resource
import subprocess
import sys
import time
from pathlib import Path


def main():
    if len(sys.argv) < 3:
        sys.exit('Usage: run-measured.py METRICS_JSON COMMAND [ARG ...]')
    started = time.monotonic()
    child = subprocess.Popen(sys.argv[2:])
    try:
        code = child.wait()
    except KeyboardInterrupt:
        # A user systemd unit signals its entire owned control group.
        import signal
        if child.poll() is None:
            child.send_signal(signal.SIGINT)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        code = 130
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    Path(sys.argv[1]).write_text(json.dumps({
        'wall_seconds': time.monotonic() - started,
        'exited_child_peak_ram_bytes': usage.ru_maxrss * 1024,
        'child_user_seconds': usage.ru_utime,
        'child_system_seconds': usage.ru_stime,
        'exit_code': code,
        'memory_scope': 'Linux RUSAGE_CHILDREN maximum; not aggregate concurrent RSS',
    }, indent=2) + '\n')
    return code if code >= 0 else 128 - code


if __name__ == '__main__':
    sys.exit(main())
