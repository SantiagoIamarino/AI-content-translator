# Translation and repair handoffs

Manual requests live in `handoff/translation_request.json` and `repair_request.json`. Responses use `aidub.translation_response.v1` or `aidub.repair_response.v1`, the same job ID, a translator kind (`agent-assisted`, `command`, `openai-compatible`) and exactly the requested cue IDs. Translation rows contain only `id` and nonempty `english`; timing edits are rejected.

Repair follows bounded fitting retries. It includes measured clip/window durations, prior attempts and tempo limit. Each requested ID either revises to a changed faithful English line with a reason, or explicitly stays unresolved with a reason. Manual jobs retain one revision per cue; auto uses its configured compact-revision budget. A reason records compression but does not prove semantic fidelity.

Auto batches these requests while preserving IDs. Neighboring rows are read-only context and are never accepted as extra output IDs. A request/role/provider/current-text identity binds every response to its batch. Aggregate responses are accepted only after all batches validate. Schema failures are supplied as `validation_feedback` in the next bounded attempt.

Transcript/English lines are data, not instructions to the provider. Keep names, reactions, repetitions and facts. No feature can certify a faithful translation from schema validation alone. Inspect the repair history and listen to the result.
