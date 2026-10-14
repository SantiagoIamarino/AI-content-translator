# Codex CLI provider

The quality preset can call a local Codex CLI instead of the Cursor agent adapter. The pipeline core is unchanged: each role is still a `command` provider, and `context`, `review`, and `back_translation` stay explicit aliases of translation or repair.

`config/local.json` stays on Cursor. Put the Codex command in a separate ignored file, for example `config/codex-luna.local.json` (`config/*.local.json` is gitignored), and select it only for a new job:

```bash
bin/aidub --config config/codex-luna.local.json auto /absolute/path/recording.mp4 \
  --name NEW_JOB --mic-ordinal N --game-ordinal N --mixed-ordinal N --preset quality
```

`--config` belongs before the subcommand. The launcher also reads it there when it chooses the Qwen interpreter.

An existing job keeps the provider command in its `jobs/NAME/config.json`. Do not point an old snapshot at Codex if its saved responses should stay bound to the previous provider.

## Install a pinned CLI

Use a versioned install directory, not the `npx --prefer-online` wrapper and not a cache path that package managers may delete. This checkout was exercised with Codex CLI `0.162.1` and model `gpt-6-luna`.

```bash
mkdir -p "$HOME/.local/opt/codex-cli/0.162.1"
cd "$HOME/.local/opt/codex-cli/0.162.1"
npm init -y
npm install --no-fund --no-audit --omit=dev @openai/codex@0.162.1
CODEX="$HOME/.local/opt/codex-cli/0.162.1/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex"
"$CODEX" --version
```

On another platform, use that platform's package instead of `codex-linux-x64`. The config must pass that binary as `--codex` and the same version as `--expect-version`. The adapter checks the version before any model call.

Sign in once with `codex login`. ChatGPT sign-in uses the plan's Codex allowance. Do not set `CODEX_API_KEY` or `OPENAI_API_KEY` for these calls: the adapter removes those variables from the child environment so a surrounding shell cannot switch the call onto API-key billing. Authentication stays in the Codex home directory. The adapter does not read or print that file.

## Command

Both `providers.translation` and `providers.repair` use the same argv, with the three quality aliases beside them. The model and reasoning effort are part of the command, so they are part of the response identity. `timeout_sec` must be long enough for one reasoning turn; the adapter's `--timeout` should be slightly shorter so it can exit before the pipeline kills the process group.

```json
{
  "kind": "command",
  "command": [
    "python3",
    "scripts/provider_codex_exec.py",
    "--codex", "/absolute/path/to/codex-0.162.1",
    "--model", "gpt-6-luna",
    "--reasoning", "high",
    "--expect-version", "0.162.1",
    "--request", "{request}",
    "--response", "{response}",
    "--role", "{role}",
    "--timeout", "1740"
  ],
  "timeout_sec": 1800,
  "max_attempts": 2
}
```

```json
{
  "context": {"kind": "same_as", "role": "translation"},
  "review": {"kind": "same_as", "role": "repair"},
  "back_translation": {"kind": "same_as", "role": "repair"}
}
```

`--preset quality` writes those same aliases over the selected config. Cursor remains available by running without `--config`, which selects `config/local.json`.

## What one call does

The adapter makes one `codex exec` invocation. It does not call `exec resume` and it does not start a second CLI process after a failure. The prompt is the request JSON on stdin. Transcript lines and validator diagnostics are data. The final message is accepted only when it is a single JSON object. That object is written unchanged: missing fields, extra ids, and empty lines stay intact and fail the existing role validator.

A validation failure is stored with the attempt. The next attempt, within `max_attempts`, receives `validation_feedback` in the request. A timeout or a nonzero exit without a response file is an uncertain outcome. With attempts still remaining, the pipeline starts a new turn; it does not continue the old Codex thread. `--ephemeral` is set so the CLI does not keep a session for later resume. Do not raise `max_attempts` to retry an uncertain call until that resume behavior has been verified.

The CLI is started with `--ignore-user-config`, `--ignore-rules`, `--sandbox read-only`, `approval_policy="never"`, web search disabled, and the shell, unified-exec, computer-use, and browser-use features disabled. `codex exec` does not accept the top-level `--ask-for-approval` flag. The working directory is an empty temporary directory outside the checkout, so this repository's `AGENTS.md` is not the agent workspace. `--dangerously-bypass-approvals-and-sandbox` is not used. A parent sandbox variable such as `CODEX_SANDBOX_NETWORK_DISABLED` is left set; this adapter does not grant network access the parent already removed.

Stderr from the adapter records the requested model, reasoning effort, event model when Codex reports one, token usage when the CLI emits it, and the process exit code. Credential-shaped strings are redacted. The pipeline still stores the command stdout and stderr logs next to the attempt.

## Limits

Structured output and the role validators check the handoff JSON. They do not prove a line is faithful or speakable. Qwen's model, English ICL, reference, generation settings, trim rule, and maximum tempo stay where the quality preset left them. A different translator does not by itself change the voice's emotional delivery.

On Codex CLI 0.162.1, a one-line smoke call used about 11,000 input tokens. Most of that is the CLI preamble, not the cue text, so a quality job's several role calls consume much more plan usage than the transcript length suggests. Those smoke events were `thread.started`, `turn.started`, `item.completed`, and `turn.completed`, with an empty workspace. The events did not include a model field. The invocation's `--model` flag is the record of which model was requested; `translator.model` is whatever the structured response contains.
