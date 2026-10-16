# Luna through ChatGPT authentication

The primary configuration for new unattended jobs uses the installed Codex CLI,
model `gpt-6-luna`, reasoning `medium`, and ChatGPT authentication for all five
roles. Initial setup must be completed before an overnight run. This repository
does not install/update the CLI, open login prompts, or switch to API billing.

Prerequisites: an already installed CLI supporting `exec --strict-config`,
`--ignore-user-config`, `--ignore-rules`, `--ephemeral`, `--output-schema`, and the
confinement controls in `aidub/codex_provider.py`; an existing ChatGPT login;
local models/reference and runtime configuration. Development verified CLI
0.163.0. Configure an installed executable directly, avoiding package launchers
that install or update themselves. Run its `login status` separately; do not
inspect or copy credential files.

In your ignored local configuration, configure each role explicitly:

```json
{
  "providers": {
    "context": {"kind":"codex_chatgpt","codex":"codex","model":"gpt-6-luna","reasoning":"medium","auth":"chatgpt","timeout_sec":900,"max_attempts":2},
    "translation": {"kind":"codex_chatgpt","codex":"codex","model":"gpt-6-luna","reasoning":"medium","auth":"chatgpt","timeout_sec":900,"max_attempts":2},
    "review": {"kind":"codex_chatgpt","codex":"codex","model":"gpt-6-luna","reasoning":"medium","auth":"chatgpt","timeout_sec":900,"max_attempts":2},
    "back_translation": {"kind":"codex_chatgpt","codex":"codex","model":"gpt-6-luna","reasoning":"medium","auth":"chatgpt","timeout_sec":900,"max_attempts":2},
    "repair": {"kind":"codex_chatgpt","codex":"codex","model":"gpt-6-luna","reasoning":"medium","auth":"chatgpt","timeout_sec":900,"max_attempts":2}
  }
}
```

`codex` above is a portable placeholder for your installed executable, resolved
through PATH or an explicit local path. Portable defaults remain unconfigured.
Quality/performance preset aliases fill missing roles and retain explicitly
configured roles. Run the normal `bin/aidub auto ... --preset performance` after
setup. Each job snapshots the effective configuration; editing local config
does not migrate existing jobs.

## Authentication and capabilities

Before each fresh request, `login status` must report ChatGPT. The adapter strips
inherited API keys, API gateways and remote-session overrides, forces the built-in
OpenAI provider and `forced_login_method=chatgpt`, and never selects an alternative
provider. A known mismatch fails before a model attempt. The old supervisor
fallback cannot change a `codex_chatgpt` provider. Existing legacy Cursor fallback
configuration is retained for historical compatibility only.

Execution uses a fresh temporary working directory, read-only sandbox, ignored
user configuration/rules, no project instructions, disabled shell, web search,
apps, plugins, hooks, browser/computer/image capabilities and multi-agent tools.
The response is rejected if execution events reveal a prohibited tool. These
controls supplement the prompt's transcript-as-data policy; a prompt alone is
not confinement. System-managed requirements still apply and conflicting
requirements must fail rather than be bypassed.

## Identity, recovery and review

`aidub.codex_chatgpt.v2` provenance binds effective model/reasoning/auth,
CLI version/binary hash, adapter/configuration source hashes, decision contract,
review code and confinement controls. It is stored in responses and attempt state
and checked on reuse. This is configured execution provenance, not an independent
server attestation of model internals. The adapter rejects a mismatched reported
model. It atomically saves normalized JSON before optional session diagnostics.

Existing request validators check exact IDs, changed revisions, source-supported
events and response sizes. `aidub.review_decision.v2` separates source uncertainty
from translation fidelity: `ok` cannot carry unresolved translation issues;
`uncertain_source` requires `disputed=true`; disputed decisions require a reason.
Schema-valid contradictions receive validation feedback under the existing
bounded attempt budget. Normal and targeted acceptance share a reducer: source
disputes remain blocked and changed English requires another exact-text review.
This adds no acoustic source-resolution coordinator.

Saved valid responses are recovered before authentication preflight/new calls,
including a response written before state acceptance. Missing durable results
remain uncertain outcomes; interrupted/exhausted attempts retain their budget.
Known authentication/quota/configuration failures stop actionably. A permanent
failure after an attempt remains blocked on resume; after fixing the cause,
explicitly increase `max_attempts` (at most five) to authorize another attempt.
Authentication preflight failures consume no model attempt. The outer process
timeout and group cleanup remain in force, including CLI-internal retries.

Historical accepted translations/context/takes retain their original provenance;
they are not renamed Luna output. New review requests use a versioned decision
contract; older incompatible reviews cannot stand in for those requests. No
historical job is migrated automatically. An authorized stopped-job migration
must retain its original config/responses, record the transition under its owned
lock, and distinguish retained historical results from new pending calls.
Rollback uses the prior code and retained snapshot, without deleting histories
or silently substituting providers. A CLI/adapter/model/contract change creates
a distinct pending-call identity; raw synthesis/hearing evidence is unaffected.

References: [official authentication](https://learn.chatgpt.com/docs/auth),
[CLI flags](https://learn.chatgpt.com/docs/cli/reference), and
[configuration controls](https://learn.chatgpt.com/docs/config-file/config-reference).
