"""Optional continuity ranking and conservative generated-audio edge preservation.

Source cue duration is an approximate pacing hint, never a stretch target.
Low-level generated sound is protected without claiming that energy is speech.
"""
from __future__ import annotations

import math
import numpy as np

from .audio import speech_bounds, to_mono, render_voice_with_margins, _cosine_up
from .util import sha256_file
from pathlib import Path


def identity(cfg):
    enabled = (cfg.get('voice_selection') or {}).get('source_pacing', {}).get('enabled')
    version = int((cfg.get('voice_edge') or {}).get('presentation_version', 1))
    return {'continuity_code': sha256_file(Path(__file__))} if enabled or version >= 3 else {}


def source_pacing_score(selection, seg, opts):
    """Add a soft duration term; retain text, voice, pause and tempo scores."""
    policy = opts.get('source_pacing') or {}
    if not policy.get('enabled'):
        return selection
    result = dict(selection)
    pace = selection['pacing']
    duration = max(0.0, float(seg['end']) - float(seg['start']))
    core = float(pace.get('core_sec') or 0)
    syllables = int(pace.get('syllables') or 0)
    # Short event reactions and sparse/non-speech spans should not be lengthened.
    penalty, target = 0.0, None
    if duration >= 1.6 and core > 0 and syllables >= 4:
        target = min(duration, syllables / float(opts['natural_rate_low']))
        target = max(target, syllables / float(opts['natural_rate_high']))
        penalty = max(0.0, abs(math.log(core / target)) - math.log(1.1))
    result['components'] = dict(selection['components'], source_duration=round(penalty, 4))
    result['score'] = round(selection['score'] + float(policy.get('weight', 4.0)) * penalty, 4)
    result['source_pacing'] = {'cue_duration_sec': duration, 'target_sec': target,
                               'approximate': True, 'penalty': penalty}
    return result


def protected_edges(wav, sr, edge):
    """Look across brief RMS dips within bounded generated margins.

    Unlike the legacy contiguous scan, this keeps a soft final release after a
    brief closure. This is only for generated audio, never microphone recovery.
    """
    mono = to_mono(wav) if np.asarray(wav).ndim > 1 else np.asarray(wav, dtype=np.float32)
    bounds = speech_bounds(mono, sr, .005)
    if bounds is None:
        return {'ok': False, 'reason': 'no_generated_core'}
    opts = edge.get('protection') or {}
    floor = float(opts.get('floor_rms', .0015))
    tail_limit = int(sr * float(opts.get('max_tail_ms', 400)) / 1000)
    lead_limit = int(sr * float(opts.get('max_lead_ms', 80)) / 1000)
    quiet = int(sr * float(opts.get('settle_ms', 20)) / 1000)
    win = max(1, int(sr * .01))
    first, last = bounds
    lo, hi = max(0, first - lead_limit), min(mono.size, last + tail_limit)
    # Compute only the bounded margins; long utterances remain inexpensive.
    def active(a, b):
        left, right = max(0, a - win), min(mono.size, b + win)
        x = mono[left:right].astype(np.float64)
        energy = np.convolve(x*x, np.ones(win)/win, 'same')
        return np.flatnonzero(energy[a-left:b-left] > floor**2) + a
    before, after = active(lo, first), active(last, hi)
    protected_first = int(before[0]) if before.size else first
    protected_last = int(after[-1]) + 1 if after.size else last
    terminal_rms = float(np.sqrt(np.mean(mono[-win:].astype(np.float64)**2)))
    reason = ''
    if terminal_rms > floor:
        reason = 'raw_ending_unsettled'
    elif hi < mono.size and protected_last + quiet > hi:
        reason = 'ending_margin_exhausted'
    return {'ok': not reason, 'reason': reason, 'first': first, 'last': last,
            'protected_first': protected_first, 'protected_last': protected_last,
            'terminal_rms': terminal_rms, 'floor_rms': floor,
            'lead_samples': max(first-protected_first + quiet, round(sr*float(edge.get('margin_lead_ms',20))/1000)),
            'tail_samples': max(protected_last-last + quiet, round(sr*float(edge.get('margin_tail_ms',60))/1000)),
            'scope': 'bounded generated signal; not a speech or listening verdict'}


def render_protected(wav, sr, edge, *, target_rms, lead_room, tail_room):
    """Fade only outside the protected signal; refuse an ending that cannot fit."""
    mono = to_mono(wav) if np.asarray(wav).ndim > 1 else np.asarray(wav, dtype=np.float32)
    info = protected_edges(mono, sr, edge)
    if not info['ok']:
        return None, info
    first, last = info['first'], info['last']
    start = max(0, first - min(info['lead_samples'], max(0, int(lead_room))))
    end = min(mono.size, last + min(info['tail_samples'], max(0, int(tail_room))))
    if start > info['protected_first'] or end < info['protected_last']:
        return None, dict(info, ok=False, reason='protected_edge_outside_window')
    # Obtain the same core-derived gain as the established renderer, with no fades.
    _, gain_info = render_voice_with_margins(mono, sr, lead_ms=0, tail_ms=0, fade_ms=0, target_rms=target_rms)
    gain = gain_info['gain']
    piece = mono[start:end].copy() * gain
    peak = float(np.max(np.abs(piece)))
    if peak > .98:
        piece *= .98/peak
        gain *= .98/peak
    fade = max(0, round(sr * float(edge.get('fade_ms',12))/1000))
    lead_fade = min(fade, info['protected_first'] - start)
    tail_fade = min(fade, end - info['protected_last'])
    if lead_fade:
        piece[:lead_fade] *= _cosine_up(lead_fade)
    if tail_fade:
        piece[-tail_fade:] *= _cosine_up(tail_fade)[::-1]
    info.update(gain=gain, lead_ms_used=(first-start)*1000/sr,
                tail_ms_used=(end-last)*1000/sr, core_preserved=True,
                protected_signal_preserved=bool(np.allclose(
                    piece[info['protected_first']-start:info['protected_last']-start],
                    mono[info['protected_first']:info['protected_last']]*gain, atol=1e-7)),
                edge='protected_margin_fade')
    return piece, info
