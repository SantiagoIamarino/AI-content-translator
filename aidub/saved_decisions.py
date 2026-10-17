"""Read-only reduction of identity-bound provider attempts, including recovery children.

No locks, provider calls, counters or job writes occur here. Callers accepting a
result into a job must hold its existing owned lock and retain the receipt.
"""
import copy
import json
import os
from pathlib import Path

from .providers import ProviderError, response_errors
from .util import fingerprint
from .source_disagreement import POLICY as DISAGREEMENT_POLICY


def envelope_error(request, response, role):
    if not isinstance(response, dict) or not isinstance(response.get("segments"), list):
        return "response/segments is malformed"
    ids = [r.get("id") for r in response["segments"] if isinstance(r, dict)]
    expected = [r["id"] for r in request["segments"]]
    if (len(ids) != len(response["segments"]) or any(type(i) is not int for i in ids)
            or len(ids) != len(set(ids)) or set(ids) != set(expected)):
        return "response IDs must exactly match the request, without duplicates"
    schema = {"review": "aidub.review_response.v1", "translation": "aidub.translation_response.v1"}[role]
    if (response.get("schema") != schema or response.get("job_id") != request.get("job_id")
            or not isinstance(response.get("translator"), dict)):
        return "response schema/job/provider envelope does not match"
    return None


def _without_feedback(value):
    return {k: v for k, v in value.items() if k != "validation_feedback"}


def _bound_provider(spec, request, role, current, state, response):
    provenance = state.get("provider_provenance")
    if provenance is None and state.get("schema") != "aidub.provider_state.v2":
        provenance = response.get("translator", {}).get("provenance")
    if provenance is not None and response.get("translator", {}).get("provenance") != provenance:
        return False
    if spec.get("kind") == "codex_chatgpt" and (not provenance or any(
            provenance.get(k) != spec.get(k) for k in ("model", "reasoning", "auth"))):
        return False
    if state.get("schema") == "aidub.provider_state.v2":
        identity_spec = {k: v for k, v in spec.items() if k not in
                         {"max_attempts", "timeout_sec", "max_request_chars", "max_response_bytes"}}
        identity_spec["resolved_model"] = spec.get("model") or os.environ.get(spec.get("model_env") or "")
        identity_spec["resolved_base_url"] = spec.get("base_url") or os.environ.get(spec.get("base_url_env") or "")
        if provenance is not None:
            identity_spec["effective_provenance"] = provenance
        identity = fingerprint({"request": request, "provider": identity_spec, "role": role,
                                "current": {str(k): v for k, v in current.items()}})
        if state.get("identity") != identity or state.get("role") != role:
            return False
    return True


def replay_saved_batch(spec, request, directory, role, current=None):
    """Validate original and scoped raw responses, never trust aggregate markers.

    A recovery must name the exact parent and copy its rows/context unchanged.
    A later invalid response cannot erase an earlier valid decision. Conversely a
    valid revision remains a revision: this reducer does not turn it into `ok`.
    """
    directory = Path(directory)
    current = current or {}
    if role == "review" and any(current.get(r["id"]) != r.get("english") for r in request["segments"]):
        raise ProviderError("Saved review request does not match current English")
    result = {"rows": {}, "receipts": {}, "errors": {}, "history": False,
              "exhausted": False, "scopes": [], "feedback": {}, "recovery_terminal": False}
    documents = [(directory, request, False)]
    parent_rows = {r["id"]: r for r in request["segments"]}
    for path in sorted(directory.glob("content_recovery/*/request.json")):
        child = json.loads(path.read_text())
        control = child.get("content_recovery") or {}
        rows = child.get("segments") or []
        ids = [r.get("id") for r in rows if isinstance(r, dict)]
        if (path.parent.name != fingerprint(child) or control.get("parent_request_identity") != fingerprint(request)
                or len(ids) != len(rows) or len(ids) != len(set(ids)) or not ids
                or control.get("ids") != ids or any(r != parent_rows.get(r.get("id")) for r in rows)
                or {k: v for k, v in child.items() if k not in {"segments", "content_recovery", "validation_feedback"}}
                != {k: v for k, v in request.items() if k not in {"segments", "validation_feedback"}}):
            continue
        documents.append((path.parent, child, True))
        result["scopes"].append({"request": path, "ids": ids, "budget": control.get("budget")})
    stamps = {}
    for root, document, scoped in documents:
        for path in sorted(root.glob("response_attempts/*/state.json")):
            state = json.loads(path.read_text())
            attempts = state.get("attempts") or []
            unresolved_infrastructure = state.get("status") == "blocked" or (
                state.get("status") != "response_ready" and attempts and attempts[-1].get("status") in
                {"invoking", "outcome_uncertain", "provider_failed", "blocked"})
            for attempt in state.get("attempts", []):
                rp = Path(attempt.get("request_path", "")); sp = Path(attempt.get("response_path", ""))
                if not rp.is_file():
                    continue
                saved_request = json.loads(rp.read_text())
                if _without_feedback(saved_request) != _without_feedback(document):
                    continue
                if not sp.is_file():
                    if unresolved_infrastructure:
                        raise ProviderError("Saved provider outcome/infrastructure failure remains unresolved", uncertain=True)
                    continue
                try:
                    data = json.loads(sp.read_text())
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(data, dict) or not _bound_provider(spec, document, role, current, state, data):
                    continue
                result["history"] = True
                if unresolved_infrastructure:
                    raise ProviderError("Saved provider infrastructure failure cannot become a content omission",
                                        permanent=state.get("status") == "blocked")
                if not scoped:
                    result["exhausted"] |= state.get("status") == "attempts_exhausted"
                else:
                    result["recovery_terminal"] |= state.get("status") in {"attempts_exhausted", "response_ready"}
                if envelope_error(document, data, role):
                    continue  # Never reconstruct a malformed whole response.
                for row in data["segments"]:
                    sid = row["id"]
                    one = dict(document, segments=[parent_rows[sid]])
                    errors = response_errors(one, dict(data, segments=[row]), role, current)
                    result["feedback"].setdefault(str(sid), []).extend(
                        error for error in (attempt.get("errors") or []) if f"id {sid} " in str(error))
                    if errors:
                        result["errors"].setdefault(str(sid), []).append({"response": str(sp), "errors": errors})
                        continue
                    stamp = float(attempt.get("ended_at") or attempt.get("started_at") or 0)
                    order = (stamp, int(scoped), str(sp))
                    if order >= stamps.get(sid, (-1, -1, "")):
                        result["rows"][sid] = row
                        result["receipts"][str(sid)] = {
                            "parent_request_identity": fingerprint(request), "request_identity": fingerprint(document),
                            "provider_attempt_identity": state.get("identity", path.parent.name),
                            "request_path": str(rp), "response_path": str(sp), "state_path": str(path),
                            "response_sha256": fingerprint(data), "provider": data["translator"],
                            "validation_policy": DISAGREEMENT_POLICY,
                            "source": copy.deepcopy(parent_rows[sid]), "decision": copy.deepcopy(row)}
                        stamps[sid] = order
    return result


def replay_response(request, role, replay):
    receipts = replay["receipts"]
    provider = next(iter(receipts.values()), {}).get("provider", {})
    pending = [r["id"] for r in request["segments"] if r["id"] not in replay["rows"]]
    return {"schema": {"review": "aidub.review_response.v1", "translation": "aidub.translation_response.v1"}[role],
            "job_id": request["job_id"], "translator": provider,
            "segments": [replay["rows"][r["id"]] for r in request["segments"] if r["id"] in replay["rows"]],
            "saved_decision_receipts": receipts,
            "_aidub_historical_validation_feedback": replay["feedback"],
            "_aidub_withheld": [{"id": sid, "reason": "scoped_content_recovery_exhausted",
                                  "validation_errors": [e for item in replay["errors"].get(str(sid), []) for e in item["errors"]]}
                                 for sid in pending]}


def restore_current_decision(segment, receipt, mic_sha=None):
    """Return a copy with a superseded marker removed only for a bound current row.

    Used by isolated evaluation/stopped-job migration, not an implicit mutation of
    completed jobs. Receipt construction and validation belong to replay above.
    """
    from .review import review_decision
    from .fidelity import RESOLUTION_POLICY, resolution_binding
    src = receipt["source"]; row = receipt["decision"]
    # Receipts are audit data, not authority on their own. Recheck their raw
    # request/response before a stopped-job migration can consume them.
    request = json.loads(Path(receipt["request_path"]).read_text())
    response = json.loads(Path(receipt["response_path"]).read_text())
    state = json.loads(Path(receipt["state_path"]).read_text())
    if (fingerprint(response) != receipt["response_sha256"]
            or envelope_error(request, response, "review")
            or receipt["provider"] != response.get("translator")
            or receipt["provider_attempt_identity"] != state.get("identity", Path(receipt["state_path"]).parent.name)
            or src not in request["segments"] or row not in response["segments"]
            or not any(a.get("request_path") == receipt["request_path"] and
                       a.get("response_path") == receipt["response_path"] for a in state.get("attempts", []))
            or response_errors(dict(request, segments=[src]), dict(response, segments=[row]),
                               "review", {src["id"]: src.get("english")})):
        return copy.deepcopy(segment), "saved_receipt_no_longer_valid"
    if (src["id"] != segment["id"] or src.get("spanish") != segment.get("spanish")
            or (src.get("source_span") and src["source_span"] != [segment["start"], segment["end"]])):
        return copy.deepcopy(segment), "saved_source_binding_changed"
    final = row.get("english", src.get("english"))
    if final != segment.get("english"):
        return copy.deepcopy(segment), "saved_english_binding_changed"
    out = copy.deepcopy(segment)
    evidence = src.get("source_evidence")
    if evidence:
        if (evidence.get("mic_sha256") != mic_sha or evidence.get("span") != [segment["start"], segment["end"]]
                or src.get("asr_alternatives", []) != segment.get("asr_alternatives", [])):
            return out, "saved_acoustic_binding_changed"
        assessment = row["source_assessment"]
        confirmed = row["verdict"] == "ok" and assessment["confidence"] in {"supported", "minor"}
        record = {"policy": RESOLUTION_POLICY, "evidence": evidence, "source_confidence": assessment["confidence"],
                  "confirmed": confirmed, "checked_text": final, "assessment": assessment,
                  "request_identity": receipt["request_identity"], "provider": receipt["provider"],
                  "saved_response": receipt["response_path"], "receipt": receipt}
        record["binding"] = resolution_binding(out, mic_sha, evidence)
        out["source_resolution"] = record
        status = "accepted_source_resolution" if confirmed else "revised_unconfirmed" if row["verdict"] == "revise" else "disputed"
    else:
        status = review_decision(row, src["english"], final)["status"]
    out.setdefault("decision_recovery_history", []).append({"previous_review": out.get("translation_review"), "receipt": receipt})
    out["translation_review"] = {"status": status, "checked_text": final, "issues": row.get("issues", []),
                                 "receipt": receipt}
    return out, "replayed_identity_bound_" + row["verdict"]
