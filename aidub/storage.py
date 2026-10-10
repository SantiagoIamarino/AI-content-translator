"""Conservative pre-extraction estimate; retry lengths and codecs remain variable."""
import shutil


def storage_budget(job_dir, source, described, mapping, cfg):
    duration = float(described['video']['duration'])
    sr = int(cfg['schedule']['output_sr'])
    channels = sum(int(mapping[r].get('channels') or 2) for r in ('mic', 'game'))
    # Extracts, actual FLOAT mix/voice, source windows, and a conservative voice
    # retry allowance. Two comparison exports copy the picture, not the source file.
    retry = 1 + int((cfg.get('quality') or {}).get('max_retries', 2)) + int((cfg.get('fit_retries') or {}).get('max_alternate_seeds', 3))
    revisions = 1 + int((cfg.get('unattended') or {}).get('max_shorter_translations', 2))
    estimate = int(2 * source.stat().st_size + duration * (sr * (channels * 2 + 12 + int(mapping['mic'].get('channels') or 2) * 2)
                                                        + 24000 * 4 * retry * revisions))
    existing = sum(p.stat().st_size for p in job_dir.rglob('*') if p.is_file() and not p.is_symlink())
    reserve = int((cfg.get('processing') or {}).get('storage_reserve_bytes', 1024**3))
    required = max(0, estimate - existing) + reserve
    free = shutil.disk_usage(job_dir).free
    if free < required:
        raise RuntimeError(f"Insufficient job disk space: free={free} bytes, estimated additional={required} bytes. "
                           "Choose another jobs_dir/free space; no artifacts were removed.")
    return {'estimated_total_bytes': estimate, 'existing_job_bytes': existing, 'estimated_additional_bytes': required,
            'free_bytes': free, 'reserve_bytes': reserve, 'note': 'Estimate, not a storage guarantee; retry lengths vary.'}
