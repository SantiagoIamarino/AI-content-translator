"""Stable provider batches; neighboring cues are read-only context."""
from __future__ import annotations

import json
from pathlib import Path

from .providers import ProviderError, invoke_checked
from .util import fingerprint, write_json


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
        responses.append(invoke_checked(bounded_spec, request_path, directory / "response.json", role, subset, before_invoke=before_invoke))
    if not responses:
        raise ProviderError(f"No cues in {role} request")
    result = {"schema": responses[0]["schema"], "job_id": request["job_id"],
              "translator": responses[0]["translator"],
              "segments": [row for response in responses for row in response["segments"]],
              "batch_providers": [response["translator"] for response in responses],
              "_aidub_request_identity": identity}
    write_json(root / f"{role}_provider_response.json", result)
    return result
