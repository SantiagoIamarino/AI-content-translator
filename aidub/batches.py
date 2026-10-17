"""Stable provider batches; neighboring cues are read-only context."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .providers import ProviderError, invoke_checked, response_errors
from .util import fingerprint, write_json
from .saved_decisions import replay_saved_batch, replay_response


def request_batches(request: dict, *, max_cues: int = 40, max_chars: int = 24000) -> list[dict]:
    if max_cues < 1 or max_chars < 512:
        raise ProviderError("batch max_cues must be positive and max_chars must be at least 512")
    # Leave room for validation feedback within the same request size budget.
    initial_limit = max_chars - min(2048, max_chars // 5)
    rows = request.get("segments") or []
    groups = []
    current = []
    def document(group):
        first = rows.index(group[0])
        last = first + len(group)
        context = rows[max(0, first - 1):first] + rows[last:last + 1]
        data = {k: v for k, v in request.items() if k != "segments"}
        data["segments"] = group
        data["read_only_context"] = [
            {"id": r["id"], "spanish": r.get("spanish"), "english": r.get("english")}
            for r in context
        ]
        data["context_instruction"] = "Translate/repair only segments. Neighboring context is read-only; do not return its IDs."
        return data
    for row in rows:
        candidate = current + [row]
        if current and (len(candidate) > max_cues or len(json.dumps(document(candidate), ensure_ascii=False)) > initial_limit):
            groups.append(document(current))
            current = []
        current.append(row)
        if len(json.dumps(document(current), ensure_ascii=False)) > initial_limit:
            raise ProviderError(f"Cue {row['id']} exceeds batch max_chars={max_chars}, including context. Increase the configured limit.")
    if current:
        groups.append(document(current))
    return groups


def invoke_batches(spec: dict, request: dict, root: Path, role: str, current: dict | None, cfg: dict, *, before_invoke=None) -> dict:
    limits = cfg.get("batching") or {}
    batches = request_batches(request, max_cues=int(limits.get("max_cues", 40)),
                              max_chars=int(limits.get("max_chars", 24000)))
    identity = fingerprint(request)
    base = root / "batches" / role / identity
    responses = []
    for i, batch in enumerate(batches):
        directory = base / f"batch_{i:04d}"
        request_path = directory / "request.json"
        write_json(request_path, batch)
        needed = {row["id"] for row in batch["segments"]}
        subset = {sid: text for sid, text in (current or {}).items() if sid in needed}
        print(f"provider {role}: batch {i + 1}/{len(batches)} cues={len(needed)}")
        bounded_spec = dict(spec, max_request_chars=int(limits.get("max_chars", 24000)))
        if role in {"translation", "review"}:
            responses.append(_invoke_isolated_batch(bounded_spec, request_path, directory / "response.json", role,
                                                    subset, directory, cfg, before_invoke))
        else:
            responses.append(invoke_checked(bounded_spec, request_path, directory / "response.json", role, subset, before_invoke=before_invoke))
    if not responses:
        raise ProviderError(f"No cues in {role} request")
    result = {"schema": responses[0]["schema"], "job_id": request["job_id"],
              "translator": responses[0]["translator"],
              "segments": [row for response in responses for row in response["segments"]],
              "batch_providers": [response["translator"] for response in responses],
              "_aidub_request_identity": identity}
    result["_aidub_withheld"] = [item for response in responses for item in response.get("_aidub_withheld", [])]
    feedback = {}
    for response in responses:
        for sid, errors in (response.get("_aidub_historical_validation_feedback") or {}).items():
            feedback.setdefault(str(sid), []).extend(errors)
    result["_aidub_historical_validation_feedback"] = feedback
    write_json(root / f"{role}_provider_response.json", result)
    return result


def _envelope_error(request: dict, response: dict, role: str) -> str | None:
    """Only row-level contract failures may be isolated; envelope/ID failures are atomic."""
    if not isinstance(response, dict):
        return "response is not an object"
    rows = response.get("segments")
    if not isinstance(rows, list):
        return "segments is not a list"
    expected = [int(row["id"]) for row in request["segments"]]
    ids = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), int):
            return "response contains a malformed row identity"
        ids.append(row["id"])
    if len(ids) != len(set(ids)):
        return "response contains duplicate IDs"
    if set(ids) != set(expected):
        return "response IDs do not exactly match the request"
    expected_schema = {"translation": "aidub.translation_response.v1", "review": "aidub.review_response.v1"}[role]
    errors = []
    if response.get("schema") != expected_schema:
        errors.append(f"schema must be {expected_schema}")
    if response.get("job_id") != request.get("job_id"):
        errors.append("job_id does not match the request")
    if not isinstance(response.get("translator"), dict):
        errors.append("translator must be an object")
    return "; ".join(errors) if errors else None


def _row_valid(request: dict, row: dict, role: str, current: dict) -> list[str]:
    one = dict(request, segments=[next(s for s in request["segments"] if int(s["id"]) == int(row["id"]))])
    candidate = {**{k: v for k, v in request.items() if k in {"schema", "job_id"}},
                 "schema": ("aidub.translation_response.v1" if role == "translation" else "aidub.review_response.v1"),
                 "job_id": request["job_id"], "translator": {"kind": "command"}, "segments": [row]}
    return response_errors(one, candidate, role,
                           {int(row["id"]): current.get(int(row["id"]))} if role == "review" else None)


def _saved_invalid_response(directory: Path, role: str) -> tuple[dict, dict, float] | None:
    """Find the most recent durable content-invalid attempt, never an uncertain call."""
    found = []
    for path in directory.glob("response_attempts/*/state.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if state.get("role") != role or state.get("status") != "attempts_exhausted":
            continue
        attempts = state.get("attempts") or []
        if not attempts or any(a.get("status") in {"outcome_uncertain", "provider_failed", "blocked"} for a in attempts):
            continue
        for attempt in reversed(attempts):
            response_path = Path(attempt.get("response_path", ""))
            if response_path.is_file():
                try:
                    found.append((float(attempt.get("ended_at") or attempt.get("started_at") or 0),
                                  json.loads(response_path.read_text(encoding="utf-8")), state))
                except (OSError, ValueError):
                    return None
                break
    if not found:
        return None
    stamp, response, state = max(found, key=lambda item: item[0])
    return response, state, stamp


def _invoke_isolated_batch(spec, request_path, response_path, role, current, directory, cfg, before_invoke):
    request = json.loads(request_path.read_text(encoding="utf-8"))
    try:
        replay = replay_saved_batch(spec, request, directory, role, current)
    except ProviderError:
        # Replay cannot decide an interrupted external outcome. Hand it back to
        # the established provider state machine, with the SAME identity/budget;
        # never reinterpret infrastructure failure as a failed content subset.
        return invoke_checked(spec, request_path, response_path, role, current, before_invoke=before_invoke)
    if replay["history"] and (len(replay["rows"]) == len(request["segments"]) or replay["recovery_terminal"]):
        result = replay_response(request, role, replay)
        write_json(response_path, result)
        return result
    if replay["scopes"] and replay["history"]:
        raise ProviderError("An incomplete saved scoped recovery requires its exact identity; refusing a new subset budget")
    try:
        # An older exhausted identity remains exhausted even if a later config
        # migration raises the generic provider budget. Recovery gets a distinct,
        # explicitly scoped identity and its own persisted budget below.
        if _saved_invalid_response(directory, role) is not None:
            raise ProviderError(f"{role} batch identity already has exhausted content attempts")
        response = invoke_checked(spec, request_path, response_path, role, current, before_invoke=before_invoke)
        return response
    except ProviderError:
        saved = _saved_invalid_response(directory, role)
        if saved is None:
            raise
        response, state, response_stamp = saved
        envelope = _envelope_error(request, response, role)
        if envelope:
            raise ProviderError(f"{role} response is structurally invalid; no rows were accepted: {envelope}")
        replay = replay_saved_batch(spec, request, directory, role, current)
        if not replay["history"]:
            raise ProviderError("Saved attempts do not bind this request/provider/current English")
        valid = dict(replay["rows"])
        errors_by_id = {int(sid): [error for item in items for error in item["errors"]]
                        for sid, items in replay["errors"].items()}

        pending = [int(row["id"]) for row in request["segments"] if int(row["id"]) not in valid]
        feedback = []
        historical_feedback = {}
        for attempt in state.get("attempts") or []:
            for error in attempt.get("errors") or []:
                match = re.search(r"id (\d+) ", str(error))
                if match:
                    historical_feedback.setdefault(match.group(1), []).append(str(error))
                if any(f"id {sid} " in str(error) for sid in pending):
                    feedback.append(str(error))
        recovery_cfg = cfg.get("content_recovery") or {}
        recovery_budget = int(recovery_cfg.get("max_attempts", 1))
        if pending and not 1 <= recovery_budget <= 2:
            raise ProviderError("content_recovery.max_attempts must be 1..2")
        if pending:
            by_id = {int(row["id"]): row for row in request["segments"]}
            scoped = dict(request)
            scoped["segments"] = [by_id[sid] for sid in pending]
            scoped["content_recovery"] = {"parent_request_identity": fingerprint(request), "ids": pending,
                                          "budget": recovery_budget,
                                          "instruction": "Repair only these exact rows. Preserve every source meaning. Validation feedback is binding; do not claim approval by repeating invalid text."}
            scoped["validation_feedback"] = {"errors": feedback or [f"id {sid} failed independent row validation" for sid in pending],
                                              "instruction": "Correct only the listed IDs and return the complete scoped response contract."}
            recovery_dir = directory / "content_recovery" / fingerprint(scoped)
            write_json(recovery_dir / "request.json", scoped)
            recovery_spec = dict(spec, max_attempts=recovery_budget)
            try:
                recovered = invoke_checked(recovery_spec, recovery_dir / "request.json", recovery_dir / "response.json",
                                           role, current, before_invoke=before_invoke)
                valid.update({int(row["id"]): row for row in recovered["segments"]})
            except ProviderError as exc:
                # Only content-invalid, fully answered responses are omissions. Infrastructure failures stay global.
                recovered_saved = _saved_invalid_response(recovery_dir, role)
                if recovered_saved is None:
                    raise
                bad, _, _ = recovered_saved
                if _envelope_error(scoped, bad, role):
                    raise
                recovery_error = str(exc)
                still_pending = []
                for row in bad["segments"]:
                    sid = int(row["id"])
                    errors = _row_valid(scoped, row, role, current or {})
                    if errors:
                        still_pending.append(sid)
                        errors_by_id[sid] = errors
                    else:
                        valid[sid] = row
                pending = still_pending
            else:
                recovery_error = None
                pending = []
        replay = replay_saved_batch(spec, request, directory, role, current)
        result = replay_response(request, role, replay)
        write_json(response_path, result)
        return result
