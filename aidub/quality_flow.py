"""Unattended quality translation: global context, contextual translation, bilingual review."""

from __future__ import annotations

from pathlib import Path

from .batches import invoke_batches
from .context import (
    context_identity,
    context_parts,
    context_request,
    merge_glossary,
    settings as quality_settings,
)
from .job import Job
from .providers import invoke_checked, require_provider, resolve_role, validate_provider_config
from .review import run_review, settings as review_settings
from .util import fingerprint, read_json, write_json
from .fidelity import repairs_needing_review, resolution_source_current, reconfirm_resolution

QUALITY_ROLES = ("context", "review", "back_translation")


def required_roles(cfg: dict) -> list[str]:
    if not quality_settings(cfg):
        return []
    roles = ["context"]
    if review_settings(cfg):
        roles.append("review")
        if str(review_settings(cfg).get("back_translation", "disputed")) == "disputed":
            roles.append("back_translation")
    return roles


def validate_quality_providers(cfg: dict, providers: dict) -> None:
    for role in required_roles(cfg):
        validate_provider_config(require_provider(resolve_role(providers, role), role))


def load_context(job: Job, cfg: dict, segments: list[dict]) -> dict | None:
    path = job.dir / "handoff/context/context.json"
    if not quality_settings(cfg) or not path.is_file():
        return None
    data = read_json(path)
    if data.get("identity") == context_identity(job.data["job_id"], segments, cfg):
        return data
    parents = job.data.get("source_resolution_parents") or []
    if parents:
        # Frozen global context/glossary still describes the original source,
        # including unresolved remainders. Never regenerate it from partial text.
        original = [s for s in segments if not s.get("source_lineage")] + parents
        if data.get("identity") == context_identity(job.data["job_id"], original, cfg):
            return data
    return None


def ensure_context(job: Job, cfg: dict, segments: list[dict], providers: dict, before_invoke=None) -> dict:
    existing = load_context(job, cfg, segments)
    if existing is not None:
        print("context: reusing transcript context and glossary")
        return existing
    opts = quality_settings(cfg)
    max_chars = int(opts.get("context_max_chars", 60000))
    identity = context_identity(job.data["job_id"], segments, cfg)
    spec = require_provider(resolve_role(providers, "context"), "context")
    spec = dict(spec, max_request_chars=max_chars + 24000)
    parts = context_parts(segments, max_chars)
    previous, conflicts, translator = None, [], None
    for index, lines in enumerate(parts):
        directory = job.dir / "handoff/context" / identity[:16] / f"part_{index:03d}"
        request = context_request(job.data["job_id"], lines, index, len(parts), previous)
        write_json(directory / "request.json", request)
        print(f"provider context: part {index + 1}/{len(parts)} lines={len(lines)}")
        response = invoke_checked(spec, directory / "request.json", directory / "response.json", "context", None,
                                  before_invoke=before_invoke)
        glossary, found = merge_glossary(list((previous or {}).get("glossary") or []) + list(response["glossary"]))
        conflicts.extend(found)
        previous = {"summary": response["summary"].strip(), "speaker_register": response["speaker_register"].strip(),
                    "glossary": glossary, "style_notes": [n.strip() for n in response["style_notes"] if n.strip()]}
        translator = response.get("translator")
    context = {"schema": "aidub.context.v1", "identity": identity, **previous, "glossary_conflicts": conflicts,
               "parts": len(parts), "translator": translator,
               "note": "Derived from the Spanish transcript only; not from the picture."}
    write_json(job.dir / "handoff/context/context.json", context)
    return context


def translate_with_review(job: Job, cfg: dict, providers: dict, export_translation, before_invoke=None) -> Path:
    """Returns the final translation response path, ready for accept_translation."""
    from .pipeline import _timeline

    segments = _timeline(job)
    ensure_context(job, cfg, segments, providers, before_invoke)
    request_path = export_translation(job, cfg)
    request = read_json(request_path)
    root = job.dir / "handoff"

    def invoke(role: str, req: dict, current: dict | None) -> dict:
        spec = require_provider(resolve_role(providers, role), role)
        return invoke_batches(spec, req, root, role, current, cfg, before_invoke=before_invoke)

    draft = invoke("translation", request, None)
    english = {int(row["id"]): row["english"].strip() for row in draft["segments"]}
    audit = None
    if review_settings(cfg):
        english, audit = run_review(job.data["job_id"], request, english, invoke, cfg)
    final = {
        "schema": draft["schema"],
        "job_id": request["job_id"],
        "translator": draft["translator"],
        "segments": [{"id": int(row["id"]), "english": english[int(row["id"])]} for row in request["segments"]],
    }
    if audit is not None:
        audit["request_identity"] = fingerprint(request)
        audit["context_identity"] = (read_json(job.dir / "handoff/context/context.json") or {}).get("identity")
        write_json(root / "translation_audit.json", audit)
    path = root / "translation_reviewed_response.json"
    write_json(path, final)
    return path


def review_pending_repairs(job: Job, cfg: dict, providers: dict, before_invoke=None) -> bool:
    """Review repaired text before it can reuse an earlier translation's verdict.

    Called with the unattended runner's owned lock, before scheduling/finalization.
    Saved responses are keyed by exact repaired English and source evidence.
    """
    from .pipeline import _timeline, build_translation_request, _save_timeline
    segments=_timeline(job)
    pending=repairs_needing_review(segments,cfg)
    if not pending:
        return False
    if not review_settings(cfg):
        return False  # stays at the review handoff; no unconfigured call
    duration=read_json(job.dir/"inspect/probe.json")["described"]["video"]["duration"]
    request=build_translation_request(job,cfg,segments,duration)
    ids={int(s["id"]) for s in pending}
    english={int(s["id"]):s["english"] for s in pending}
    request["segments"]=[r for r in request["segments"] if int(r["id"]) in ids]
    alignment_path=job.dir/"extract/alignment.json"
    mic_sha=read_json(alignment_path)["mic_sha256"] if alignment_path.is_file() else None
    for row in request["segments"]:
        seg=next(s for s in pending if s["id"]==row["id"])
        if resolution_source_current(seg,mic_sha):
            resolution=seg["source_resolution"]
            row["resolved_source"]={"assessment":resolution["assessment"],"evidence_id":resolution["evidence"]["identity"],
                                    "note":"Evidence-bound source reading; original alternatives remain in history."}
        for side in ("context_before","context_after"):
            for neighbor in row.get(side,[]):
                neighbor["english"]=next(s.get("english") for s in segments if s["id"]==neighbor["id"])
    request["delivery_policy"]=(request.get("delivery_policy") or "")+(
        "\nThis draft is a compact timing repair. Compare it with the original Spanish again. "
        "Preserve tense, subjects, hedges, connectors and repeated reactions. Do not accept missing meaning to fit a window.")
    identity=fingerprint({"request":request,"english":english,"review":review_settings(cfg),"version":1})
    root=job.dir/"handoff/repair_reviews"/identity
    write_json(root/"source_request.json",request)
    def invoke(role,req,current):
        spec=require_provider(resolve_role(providers,role),role)
        return invoke_batches(spec,req,root,role,current,cfg,before_invoke=before_invoke)
    final,audit=run_review(job.data["job_id"],request,english,invoke,cfg)
    audit["source_request_identity"]=fingerprint(request)
    audit["orchestration_policy"]="compact_review_before_schedule_v1"
    write_json(root/"audit.json",audit)
    for s in pending:
        sid=int(s["id"]);line=audit["lines"][str(sid)]
        s.setdefault("repair_review_history",[]).append(dict(before=s["english"],after=final[sid],
            audit=str((root/"audit.json").relative_to(job.dir)),status=line["status"]))
        s["english"]=final[sid]
        s["translation_review"]={"status":line["status"],"draft":english[sid],"checked_text":final[sid],
                                 "issues":sorted({i for r in line["rounds"] for i in r.get("issues",[])})}
        if line["status"] in {"accepted_draft","revised_confirmed"}:
            reconfirm_resolution(s,mic_sha,final[sid],str((root/"audit.json").relative_to(job.dir)))
    for stage in ("schedule","mix","validate"):
        job.stage(stage).update(status="pending",fingerprint=None)
    _save_timeline(job)
    print(f"compact repair reviewed: {len(pending)} lines; unresolved verdicts remain unvoiced")
    return True
