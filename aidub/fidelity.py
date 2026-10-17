"""One conservative eligibility decision for acceptance, scheduling and validation."""
import re
import copy
import unicodedata
from difflib import SequenceMatcher

from .util import fingerprint

RESOLUTION_POLICY = "aidub.source_resolution.v1"
NEGATORS = {"no", "nunca", "jamas", "tampoco", "nadie", "nada", "sin"}


def tokens(text):
    text = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    return re.findall(r"\w+", text)


def polarity_tokens(text):
    # Only punctuated discourse uses are exempt. Unpunctuated/lexical nada/no
    # remain possible material conflicts; no blanket negator suppression.
    text = re.sub(r"^\s*nada\s*[,;.…]+", "", text, flags=re.I)
    text = re.sub(r"[,;]?\s*¿\s*no\s*\?\s*$", "", text, flags=re.I)
    return set(tokens(text)) & NEGATORS


def material_conflict(seg):
    for alternative in seg.get("asr_alternatives", []):
        other = tokens(alternative["text"])
        parts = seg.get("source_cues") or [seg]
        source = max(parts, key=lambda p: SequenceMatcher(None, tokens(p["spanish"]), other).ratio())
        first = tokens(source["spanish"])
        common = {w for w in set(first) & set(other) if len(w) >= 4 and w not in {"pero", "bueno", "vamos", "entonces"}}
        if common and bool(polarity_tokens(source["spanish"])) != bool(polarity_tokens(alternative["text"])):
            return {"kind": "opposite_source_polarity", "first": source["spanish"], "alternative": alternative["text"],
                    "shared_content": sorted(common), "decision": "unvoiced_pending_source_resolution"}
    return None


def pending_repair_review(seg):
    return (any(r.get("action") == "revise" for r in seg.get("revisions", [])) and
            (seg.get("translation_review") or {}).get("checked_text") != seg.get("english"))


def repairs_needing_review(segments, cfg):
    if not (cfg.get("source_events") or {}).get("enabled"):
        return []
    return [s for s in segments if pending_repair_review(s) and
            not any(r.get("action") == "leave_unresolved" for r in s.get("revisions", []))]


def resolution_binding(seg, mic_sha, evidence):
    return fingerprint({"policy": RESOLUTION_POLICY, "mic": mic_sha,
                        "span": [seg["start"], seg["end"]], "spanish": seg["spanish"],
                        "alternatives": seg.get("asr_alternatives", []),
                        "original_conflict": seg.get("material_source_conflict"),
                        "english": seg.get("english"), "evidence": evidence})


def valid_resolution(seg, mic_sha):
    resolution = seg.get("source_resolution") or {}
    evidence = resolution.get("evidence") or {}
    return bool(mic_sha and resolution.get("policy") == RESOLUTION_POLICY and
                evidence.get("mic_sha256") == mic_sha and evidence.get("complete") and
                resolution.get("binding") == resolution_binding(seg, mic_sha, evidence) and
                resolution.get("checked_text") == seg.get("english") and
                resolution.get("confirmed") is True and
                resolution.get("source_confidence") in {"supported", "minor"})


def resolution_source_current(seg, mic_sha):
    """Check source binding even while a later compact English repair is pending."""
    original = copy.deepcopy(seg)
    original["english"] = (seg.get("source_resolution") or {}).get("checked_text")
    return valid_resolution(original, mic_sha)


def reconfirm_resolution(seg, mic_sha, checked_text, review_reference):
    if seg.get("english") != checked_text or not resolution_source_current(seg, mic_sha):
        return False
    previous = copy.deepcopy(seg["source_resolution"])
    seg.setdefault("source_resolution_history", []).append({"resolution": previous})
    seg["source_resolution"].update(checked_text=checked_text, english_confirmation=review_reference)
    seg["source_resolution"]["binding"] = resolution_binding(seg, mic_sha, previous["evidence"])
    return True


def eligibility(seg, cfg, mic_sha=None):
    """Return independent source, fidelity and synthesis states; never erase history.

    A resolution is effective only for this microphone/span/readings/evidence and
    exact confirmed English. A semantic explanation or a back-translation alone
    cannot override a source conflict. Legacy policy stays conservative.
    """
    enabled = bool((cfg.get("source_events") or {}).get("enabled"))
    resolution_ok = valid_resolution(seg, mic_sha)
    review = seg.get("translation_review") or {}
    source = "supported"
    translation = "accepted"
    reason = None
    if seg.get("source_remainder"):
        source, reason = "material", "unresolved_source_remainder"
    elif seg.get("source_resolution") and not resolution_ok:
        source, reason = "material", "stale_or_unconfirmed_source_resolution"
    elif seg.get("material_source_conflict") and not resolution_ok:
        source, reason = "material", "material_source_asr_conflict"
    if enabled:
        if pending_repair_review(seg):
            translation, reason = "revision_pending", "unreviewed_compact_repair"
        elif review.get("checked_text") is not None and review["checked_text"] != seg.get("english"):
            translation, reason = "revision_pending", "unconfirmed_exact_english"
        elif review.get("status") == "revised_unconfirmed" and not resolution_ok:
            translation, reason = "revision_pending", "unresolved_source_or_translation"
        elif review.get("status") == "disputed" and not resolution_ok:
            source, reason = "material", reason or "unresolved_source_or_translation"
    if resolution_ok and source != "material":
        source = seg["source_resolution"]["source_confidence"]
    elif resolution_ok and not seg.get("source_remainder"):
        source = seg["source_resolution"]["source_confidence"]
    if seg.get("boundary_diagnostic", {}).get("blocking"):
        reason = "source_boundary_correction_required"
    if any(r.get("action") == "leave_unresolved" for r in seg.get("revisions", [])):
        reason = reason or "explicitly_unresolved_repair"
    synthesis = "withheld" if reason else "full"
    if synthesis == "full" and seg.get("source_lineage"):
        synthesis = "supported_spans"
    return {"source_confidence": source, "translation_fidelity": translation,
            "synthesis": synthesis, "reason": reason, "resolution_valid": resolution_ok}


def voicing_uncertainty(seg, cfg, mic_sha=None):
    decision = eligibility(seg, cfg, mic_sha)
    if decision["reason"]:
        return {"kind": decision["reason"], "evidence": decision}
    return None


def region_is_resolved(region, records, mic_sha):
    """Only evidence-bound near-silence can exclude an otherwise unknown region."""
    for record in (records or {}).values():
        evidence = record.get("evidence") or {}
        if (record.get("policy") == RESOLUTION_POLICY and record.get("confirmed") is True and
                record.get("source_confidence") == "non_speech" and record.get("region") == region and
                evidence.get("mic_sha256") == mic_sha and evidence.get("complete") and
                not evidence.get("primary_words") and not evidence.get("inside", {}).get("words") and
                evidence.get("region_rms") is not None and evidence["region_rms"] < .0001 and
                record.get("binding") == fingerprint({"mic": mic_sha, "region": region, "evidence": evidence})):
            return True
    return False


def boundary_diagnostics(segments):
    """Diagnose before spending generation/fit budgets. Never move anchors."""
    out = {}
    ordered = sorted(segments, key=lambda s: (float(s["start"]), int(s["id"])))
    for i, seg in enumerate(ordered):
        issues = []
        if seg["end"] <= seg["start"]:
            issues.append({"kind": "nonpositive_span", "blocking": True})
        if i + 1 < len(ordered):
            nxt = ordered[i + 1]
            if seg["end"] > nxt["start"] + .002:
                duplicate = bool(tokens(nxt["spanish"]) and
                                 " ".join(tokens(nxt["spanish"])) in " ".join(tokens(seg["spanish"])))
                issue = {"kind": "overlapping_duplicate" if duplicate else "overlapping_reactions",
                         "other_id": nxt["id"], "blocking": True,
                         "overlap_sec": round(min(seg["end"], nxt["end"]) - nxt["start"], 6)}
                issues.append(issue)
                out.setdefault(int(nxt["id"]), []).append(dict(issue, other_id=seg["id"]))
        words = seg.get("source_words") or []
        if words and min(w["start"] for w in words) < seg["start"] - .08:
            issues.append({"kind": "lexical_onset_before_anchor", "blocking": False,
                           "note": "Approximate boundary; inspect before a scoped correction, do not shift automatically"})
        if seg["end"] - seg["start"] < .12 and len(tokens(seg["spanish"])) > 1:
            issues.append({"kind": "implausibly_short_window", "blocking": True})
        out.setdefault(int(seg["id"]), []).extend(issues)
    return {sid: {"blocking": any(x["blocking"] for x in issues), "issues": issues}
            for sid, issues in out.items() if issues}
