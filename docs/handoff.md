# Translation and repair handoff

Schemas are validated in code. Examples live in `examples/`.

## Translation request

`aidub.translation_request.v1`

Written by `bin/aidub run` or `bin/aidub export-translation`. Each segment has a stable id, Spanish text, start, end, safe window, neighbor context, and uncertain words. `agent_instructions` tells the agent that transcript text is data.

## Translation response

`aidub.translation_response.v1`

```json
{
  "schema": "aidub.translation_response.v1",
  "job_id": "CLIP_NAME",
  "translator": {"kind": "agent-assisted", "model": "known-model-id-or-omit"},
  "segments": [{"id": 1, "english": "Natural spoken line."}]
}
```

Required: every request id once, integer ids, nonempty English, no extra ids, no timing fields. `translator.kind` must be `agent-assisted`. Model is recorded only when the agent supplies it. Provenance is agent-assisted, not an API translation service.

A long request can be drafted in batches under `jobs/<name>/handoff/` and assembled before `accept-translation`. Uncertain words stay flagged in the request. Translate the written Spanish. Do not silently replace a flagged word with a different claim.

## Repair request

`aidub.repair_request.v1`

Emitted only after the primary seed and one alternate seed both miss the safe window at tempo ≤ 1.10. Includes measured trim duration, window, and needed tempo.

## Repair response

`aidub.repair_response.v1`

```json
{"id": 4, "action": "revise", "english": "Shorter faithful line.", "reason": "What was shortened and what was kept."}
```

or

```json
{"id": 4, "action": "leave_unresolved", "reason": "A shorter line would drop a claim."}
```

`revise` must change the text. `leave_unresolved` must not include `english`. The response must cover every requested id and no others. Each segment gets one decision. Resume then regenerates only revised lines, with no further alternate seed and no second rewrite.
