# Use Claude and Codex subscriptions in Quarry: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans to
> implement this plan task by task. Checkboxes track implementation work.

**Goal:** Run Quarry prompts and recipe tidying against your existing Claude
Code or Codex subscription, without requiring a provider API key.

**Architecture:** Add a step-level runtime interface alongside the existing
raw-model provider interface. Codex app-server and the Claude Agent SDK run
fresh native sessions; their tool callbacks invoke Quarry's existing
`ToolExecutor`. Quarry continues to own the kernel, transcripts, lineage and
replay.

**Tech stack:** Python 3.11, existing FastAPI server, installed Codex CLI,
installed unmodified Claude Code CLI, Python Claude Agent SDK, subprocess
JSON-RPC and Model Context Protocol (MCP).

**Spec:** [Current design](../specs/2026-10-08-quarry-design.md), especially
sections 5, 6, 8, 10, 11 and 12. This is a proposed plan. Its changes to the
design become binding only when accepted and implemented. No application code
changed during planning.

## Recommendation and alternatives

Use native runtimes with their own login first. Implement Codex, then Claude
against the same execution contract. The first task must prove capability
control before either integration ships.

| Approach                                      | Benefit                                                                             | Cost                                                                                             | Recommendation                                                             |
| --------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| Installed, authenticated runtimes             | Reuses your existing login and provider-maintained authentication                   | Full agents need a tool bridge and explicit lifecycle handling                                   | First release                                                              |
| OpenAI Sign in with ChatGPT plan usage        | Explicit app consent; eligible Responses calls could retain Quarry's raw-model loop | Registration, host IDs, credential storage, renewal and preview restrictions; covers OpenAI only | Separate follow-up or Codex alternative if native capability control fails |
| Extract CLI tokens and call private endpoints | Appears to preserve the current provider interface                                  | Couples Quarry to credential internals and bypasses supported authentication boundaries          | Exclude                                                                    |

OpenAI currently permits continued app-server authentication for local and
open-source applications while recommending Sign in with ChatGPT. Commercial or
hosted services have a separate integration path. Anthropic's current
subscription billing guidance includes the Agent SDK and print mode, while its
credential rules require native sign-in and prohibit credential intermediation.
See the [official authentication sources](#official-sources). The intended
deployment here is your own Quarry process under your OS account.

## What T3 Code establishes

I inspected `pingdotgg/t3code` at `cdba9a038e41c6c807a2b58bd43e83dcf98d74b7` on
October 14, 2026. It supports both providers through their native runtimes:

- Codex: an `app-server` subprocess, JSON-RPC over stdin/stdout, native login,
  thread creation and `turn/interrupt`. See its
  [launch arguments](https://github.com/pingdotgg/t3code/blob/cdba9a038e41c6c807a2b58bd43e83dcf98d74b7/apps/server/src/provider/codexLaunchArgs.ts#L12-L15)
  and
  [login guide](https://github.com/pingdotgg/t3code/blob/cdba9a038e41c6c807a2b58bd43e83dcf98d74b7/docs/user/providers-codex.md#L22-L26).
- Claude: the TypeScript Agent SDK driving an installed Claude executable. See
  its
  [query setup](https://github.com/pingdotgg/t3code/blob/cdba9a038e41c6c807a2b58bd43e83dcf98d74b7/apps/server/src/orchestration-v2/Adapters/ClaudeAdapterV2.ts#L731-L808)
  and
  [login guide](https://github.com/pingdotgg/t3code/blob/cdba9a038e41c6c807a2b58bd43e83dcf98d74b7/docs/user/providers-claude.md#L1-L35).
- Both: injected authenticated HTTP MCP tools. See the
  [Codex configuration](https://github.com/pingdotgg/t3code/blob/cdba9a038e41c6c807a2b58bd43e83dcf98d74b7/apps/server/src/orchestration-v2/Adapters/CodexAdapterV2.ts#L1327-L1355)
  and
  [Claude configuration](https://github.com/pingdotgg/t3code/blob/cdba9a038e41c6c807a2b58bd43e83dcf98d74b7/apps/server/src/orchestration-v2/Adapters/ClaudeAdapterV2.ts#L1213-L1250).

Borrow login ownership and adapter lifecycle. Quarry can share tool schemas and
dispatch without copying T3's HTTP transport, multiple-account machinery or
persistent native conversation management.

## Quarry boundaries and proposed changes

`Provider.complete()` in `agent/types.py` returns one raw model response.
`run_agent_step()` in `agent/loop.py` controls its conversation and dispatch. A
subscription runtime owns an inner agent loop, so hiding it behind `complete()`
would introduce pending tool replies and hidden session state.

Introduce `AgentRuntime` in `agent/runtime.py` with two operations:

- `run_step(*, prompt: str, system: str, summary: str, tools: ToolExecutor, cancel: threading.Event) -> StepOutcome`
- `complete_text(*, system: str, prompt: str, cancel: threading.Event) -> AssistantTurn`

The API implementation wraps the current loop and provider. Text completion
preserves `AssistantTurn.stop` and raises `ProviderError` on failure or
cancellation; it never returns a successful string from a failed or truncated
run. Existing recipe validation remains in `projects/tidy.py`.

Move only shared dispatch and outcome construction from `loop.py` into a
`StepExecution` owner there. It records tool calls/results, serializes tool
execution, applies the Python repair rule and builds `StepOutcome`. Each adapter
owns its transport and native completion semantics. Do not build a controller
that pretends to control every provider's inference loop.

Use Codex dynamic tool requests and Claude SDK in-process MCP first. Their
definitions come from `TOOL_DEFS`, and both call
`StepExecution.dispatch(call: ToolCall) -> ToolResult`. Dynamic tools are
experimental, so pin a tested Codex version. If direct registration cannot
represent the existing schemas or lifecycle, use one authenticated HTTP MCP
bridge as an explicit revision to this plan.

Each Quarry step starts a fresh native conversation with `build_system()` and
`build_summary()`. Native sessions do not survive between Quarry steps.
Completed Python executions remain authoritative even if the native process dies
before acknowledging a tool result. Never automatically repeat such a step.

Protocol cleanup and kernel execution have separate lifetimes. Before saving an
outcome or releasing the session, await any executing tool callback until it
returns or the existing kernel restart kills it. On runtime failure, request the
existing kernel interrupt; if Python does not stop, retain the busy session
until it settles or the researcher restarts. Do not snapshot `tools.runs` while
an executing callback can still append to it.

## Global constraints

These requirements apply to every task:

- One researcher, one server, one session at a time, on a shared development
  machine reached by SSH. Steps in a session are linear.
- The server binds `127.0.0.1` only, and every API request carries a per-run
  bearer token.
- Python 3.11, managed with uv; Linux deployment and macOS development.
- Every result must be reproducible as plain Python a researcher can run in a
  notebook.
- All Python, datasets and views go through the existing five Quarry tools. No
  native shell, file writes, subagents, inherited MCP tools or hooks may perform
  unrecorded work.
- Subscription authentication belongs to the installed runtime on the server,
  under the same OS user. Quarry stores status metadata, never OAuth tokens.
- A subscription selection never switches to API billing automatically.
- The existing API modes and historical session files continue to work.
- The UI continues polling; native event streaming is internal to the adapter.
- Routine verification uses fixtures and local kernels without paid calls. Live
  subscription checks require an explicit opt-in and a fixed request cap.

The proposed design amendments are provider choices in sections 1 and 11,
step-level runtime execution and limits in section 8, recipe completion in
section 10, and native authentication ownership in section 12. Amend those
sections during implementation, then record the accepted choices in
`docs/context/decisions.md` and module responsibilities in `code-map.md`.

## Limits and stopping

Keep the API loop's current 12 `Provider.complete()` invocation limit. It is not
a count of underlying HTTP attempts, since provider clients can retry.

For subscriptions, propose a maximum of 12 Quarry tool dispatches per step.
Reject a thirteenth before execution and end the step as an error. This is a
different, measurable policy and needs the section 8 amendment above. Apply a
documented native turn limit too where available; do not claim it counts model
calls. Make `StepOutcome.iterations` optional for native runtimes whose
inference count is unavailable, rather than repurposing the field.

The second consecutive `run_python` failure ends further Quarry execution. Other
tools do not reset that counter; a successful Python run does. Serialize the
callbacks so a queued third run cannot begin after the second failure. Then
interrupt the native runtime. This stops further Quarry operations; it does not
establish zero further model computation before interruption arrives.

Cancellation owns runtime cleanup. Send the native interrupt, stop queued
dispatch and wait up to 2 seconds for exit, then terminate the subprocess and
reap it within another 2 seconds. These are runtime cleanup bounds, not a
timeout on the researcher's Python. Existing kernel interrupt and restart
semantics continue to apply. Surface a known subscription-limit event as a step
error and stop the runtime instead of holding Quarry busy until reset. The
cleanup bounds apply to the native process, not completion of a callback already
running in the kernel.

`ProjectService` owns cancel events and completion signals for its active
text-only tidy operations. Add `ProjectService.shutdown() -> None`, called by
the app lifespan alongside `SessionService.shutdown()`, to cancel and await
their runtime cleanup. Tidying remains outside the session's kernel hold, so a
subsequent session step can start while a save tidies its recipe. Cancelling a
tidy must not interrupt that later step's kernel.

## Review focus

The implementation must exercise these conditions:

1. Native or inherited tools bypassing recorded Python: expose only the five
   Quarry tools, including under hostile inherited user configuration.
2. Concurrent calls around failure or cancellation: stop further execution at
   the serialized boundary, preserving runs already completed.
3. Disconnect after a tool executes: save its run and lineage once, without
   automatically repeating the operation.
4. Wrong authentication source: report a subscription/API mismatch before
   inference, including environment overrides.
5. Provider failure during recipe tidying: retain raw-recipe saving, and do not
   accept truncated output as a valid tidy result.

## Task 1: Prove the native runtime boundaries

Run this before committing to either adapter's protocol. Local inspection
already confirmed Codex CLI `0.162.1`, Claude Code `2.1.299`, app-server schema
generation and Claude's capability/configuration flags. It did not establish
subscription auth, model access or live tool exclusion.

**Files:** inspect `agent/loop.py`, `agent/tools.py`, `server/service.py` and
`projects/tidy.py`; use temporary probe files outside the repository.

**Produces:** tested version ranges, exact runtime options and event traces that
determine whether Tasks 3 and 5 can use the proposed direct transports.

- [ ] Inspect the pinned schemas and SDK options for native-tool exclusion,
      inherited configuration control, cancellation and terminal results.
- [ ] Check native auth status under the server user; confirm subscription
      billing with the effective child environment. Do not print credentials.
- [ ] In an explicit live check, use at most three synthetic prompts per
      provider: tools disabled, an injected harmless tool, and cancellation. Use
      no firm datasets. Confirm that tool inventories contain only intended
      tools.
- [ ] Replay captured events offline for concurrent calls, malformed arguments,
      two Python failures separated by another tool, and queued-call
      cancellation.
- [ ] Confirm which native limit counts what, and verify the proposed 12-tool
      policy independently. If capability exclusion cannot be proved, stop that
      native integration and use the documented alternative; do not rely on a
      prompt instruction or filesystem sandbox as a substitute.

## Task 2: Introduce the runtime and shared execution boundary

Wrap current behavior before adding a native provider. Deletion and relocation
come first: move dispatch policy and outcome construction from `loop.py`; delete
their old copies rather than duplicate the loop.

**Files:** create `src/quarry/agent/runtime.py`; modify `agent/loop.py`; extend
`tests/agent/test_loop.py`; create `tests/agent/test_runtime.py`.

**Interfaces:** produce `AgentRuntime`, its API implementation and
`StepExecution.dispatch(call: ToolCall) -> ToolResult`. Preserve the existing
`ToolExecutor` and `AssistantTurn` models.

- [ ] Write tests proving the API wrapper returns the same outcomes, transcript
      order and invocation count as the existing fake-provider tests.
- [ ] Add shared-dispatch tests: non-Python tools do not reset Python failures;
      Python success resets them; queued calls cannot execute after halt; native
      dispatch 13 never executes; a completed run survives adapter failure.
- [ ] Run the focused tests to establish failures, implement only this boundary,
      rerun them, then commit the independently working API wrapper.

## Task 3: Add the Codex subscription runtime

Drive the installed CLI directly from Python; no Node service is required.

**Files:** create `src/quarry/agent/codex_runtime.py` and
`tests/agent/test_codex_runtime.py`; extend shared runtime tests.

**Interfaces:** implement `AgentRuntime`; dispatch dynamic requests through Task
2's boundary; normalize text, calls and results to existing `Message`s.

- [ ] Write a fake app-server executable that exercises initialization,
      correlated requests, dynamic tools, interleaved notifications and exit.
- [ ] Implement `initialize`, `initialized`, subscription `account/read`, fresh
      `thread/start`, `turn/start`, tool responses and terminal-status mapping.
      Enable experimental dynamic tools only for the pinned supported versions.
- [ ] Keep protocol reading and cancellation separate from blocking kernel
      execution, so a running tool cannot prevent an interrupt or process
      cleanup.
- [ ] Require ChatGPT authentication and the intended provider configuration.
      Record the runtime-resolved model when reported. A catalog entry alone
      does not establish account access.
- [ ] Prove dataset/view creation, text-only completion, unknown tool exclusion,
      auth and quota errors, malformed output, process death, and no duplicate
      text from partial and completed messages.
- [ ] Verify `turn/interrupt` and subprocess cleanup during model wait and
      queued tool requests. Kill the fake runtime during gated Python execution;
      the outcome must wait and include the run exactly once. Test cancellation
      when execution outlasts native cleanup, then release the callback or kill
      its kernel. Run the focused tests and commit.

## Task 4: Wire configuration, prompts and recipe tidying

Deliver a usable Codex path through both model consumers.

**Files:** modify `src/quarry/config.py`, `server/service.py`,
`server/projects.py`, `server/app.py` and `projects/tidy.py`; extend
`tests/test_config.py`, `tests/server/test_app.py`,
`tests/server/test_projects_service.py` and `tests/projects/test_tidy.py`.

**Interfaces:** produce
`runtime_from_config(config: QuarryConfig) -> AgentRuntime` and the
corresponding injectable `RuntimeFactory`. Replace the service-level
`ProviderFactory` wiring; keep raw providers inside API runtimes.

- [ ] Extend `provider.name` with `codex` and `claude-code`, preserving
      `anthropic` and `openai`. Add an optional `cli_path` for installed
      binaries. Require an explicit model for native modes so Codex cannot
      inherit the Anthropic API default. Reject `api_key_file` in a subscription
      configuration.
- [ ] Run prompts through `run_step()` and tidying through `complete_text()`.
      Keep raw-recipe fallback and local recipe validation. Ensure runtime
      resources close when either operation finishes or fails.
- [ ] Track active tidy cancellation/completion in `ProjectService`, and wire
      its `shutdown()` into the app lifespan. Test shutdown during a blocked
      tidy and prove a session step can start after the save releases its kernel
      hold; tidy cancellation must leave that step untouched.
- [ ] Test model-wait interrupt, restart, process crash after Python execution,
      next-step context, replay, saving without an API key, and shutdown
      cleanup. Preserve existing single-operation and HTTP 409 behavior.
- [ ] Add the Codex setup example to the existing README, including login on the
      Linux server and the tested CLI version. Amend the relevant design
      sections and context docs. Run focused checks and commit the working Codex
      path.

The proposed configuration is explicit about subscription billing:

```toml
[provider]
name = "codex"
model = "gpt-6.1-sol"
```

Select a model available to your account; the example does not establish your
entitlement. Sign in with `codex login` on the Quarry host. Use device login
where browser callbacks over SSH are unsuitable.

## Task 5: Add Claude Code against the same contract

Use the Python Agent SDK to drive the installed, unmodified binary. Keep
authentication inside Claude Code's native flow. The SDK is optional for people
using another backend.

**Files:** create `src/quarry/agent/claude_runtime.py` and
`tests/agent/test_claude_runtime.py`; modify `pyproject.toml`, `uv.lock`,
`agent/runtime.py`, existing setup/context docs and provider tests.

**Interfaces:** implement `AgentRuntime`; use `TOOL_DEFS` for in-process MCP
tools and Task 2's serialized dispatcher for execution.

- [ ] Add a tested, locked `claude-agent-sdk` optional dependency compatible
      with Python 3.11; document its installation through uv.
- [ ] Use the installed binary explicitly. Verify native subscription auth with
      `claude auth status`; setup remains `claude auth login`. Preserve normal
      `HOME` and keychain access. Exclude API/gateway overrides from this mode's
      effective environment so print-mode API-key precedence cannot change
      billing.
- [ ] Register only Quarry MCP tools, disable built-ins, exclude inherited MCP
      and executable customizations using Task 1's tested configuration options.
      `allowed_tools` sets approvals, not availability. Do not use `--bare`,
      which excludes OAuth/keychain authentication.
- [ ] Test SDK final status, refusal, truncation, quota/auth errors, text-only
      tidying, sequential callbacks and interruption/close. Do not resume native
      conversations between Quarry steps.
- [ ] Run the same real-kernel contract tests as Codex, update setup docs with
      `name = "claude-code"` and an explicitly chosen Claude model, then commit.

If the pinned SDK cannot supply the required binary/configuration controls, use
documented `claude -p` NDJSON with an authenticated local MCP bridge. Revise the
transport task before implementing it; authentication ownership and Quarry's
execution boundary stay the same.

## Task 6: Verify the complete paths

Use real local kernels and fake native runtimes for routine verification.

**Files:** extend existing server/agent integration tests and
`tests/agent/test_live_providers.py`; update existing README and context docs.

- [ ] Run the contract suite for both native modes: dataset, view, second-step
      context, repair, interrupt, restart/replay, disconnect after execution,
      tidy, unknown tools and cleanup. Existing API suites must also pass.
- [ ] Run `uv run ruff check src tests`, `uv run ruff format --check src tests`,
      `uv run mypy src tests`, `uv run pytest -q` and `uv lock --check`.
- [ ] Check Markdown with Prettier; run existing web checks and the built-UI
      browser tests for the server integration. No new UI is needed for TOML
      setup.
- [ ] Complete at most two additional synthetic live requests per provider,
      explicitly opted in: one dataset/view step and one text-only tidy. Verify
      subscription usage, then record versions, results and platform limits.
- [ ] Update `docs/working-state.md`. Review the final diff before creating a
      PR; use the repository's existing verification gates if a PR is requested.

## Official sources

These pages were opened and checked on October 14, 2026. Recheck them at
implementation because authentication and subscription policies can change:

- [Codex app-server protocol and local-app authentication](https://learn.chatgpt.com/docs/app-server)
- [Codex authentication and cached login ownership](https://learn.chatgpt.com/docs/auth)
- [Sign in with ChatGPT plan usage](https://developers.openai.com/siwc/token-sharing-open-source)
- [Plan usage preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [Claude SDK subscription billing update](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
- [Claude authentication and credential boundaries](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use)
- [Claude Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python)
- [Claude custom tools](https://code.claude.com/docs/en/agent-sdk/custom-tools)
- [Claude CLI options](https://code.claude.com/docs/en/cli-reference)
- [Claude programmatic execution](https://code.claude.com/docs/en/headless)

## Advisor report

The Codex advisor reviewed the local architecture through the installed
`codex-advisor` skill. Its raw report follows; the plan above incorporates its
changes. It did not independently verify T3 or vendor sources.

<details>
<summary>Read the advisor's original report</summary>

context: caller prompt only

**proceed-with-changes**

1. **Do not promise an exact 12-model-call cap for subscription runtimes yet.**
   Quarry currently limits 12 calls to `Provider.complete`, not necessarily 12
   underlying requests:
   [loop.py:94](/Users/sunpar/workspace/quarry/src/quarry/agent/loop.py:94)
   increments before calling the provider, while
   [openai_provider.py:34](/Users/sunpar/workspace/quarry/src/quarry/agent/openai_provider.py:34)
   enables retries. Provider-owned turns, assistant messages, and tool callbacks
   are not demonstrated equivalents. Require a documented runtime limit or a
   blocking boundary before each model invocation. Counting notifications and
   then interrupting cannot establish an exact cap. If unavailable, explicitly
   change the subscription policy to a measurable runtime-specific limit; do not
   silently reinterpret `iterations`.

2. **Native-tool exclusion is the architecture’s first gate.** Adding Quarry
   tools does not demonstrate that shell, file writes, subagents, inherited MCP
   servers, or configured hooks cannot execute outside recorded `run_python`.
   That would break replay and lineage. Before choosing either adapter, prove
   that its pinned runtime can expose only the intended capabilities and control
   inherited configuration. A prompt instruction or filesystem sandbox alone is
   insufficient.

3. **The two-failure rule belongs at a serialized execution boundary.** Current
   behavior stops the rest of the tool batch immediately, and intervening
   non-Python calls do not reset the failure counter:
   [loop.py:112](/Users/sunpar/workspace/quarry/src/quarry/agent/loop.py:112).
   Concurrent callbacks could otherwise execute a third operation before
   interruption arrives. The shared dispatcher must serialize execution, record
   the second failure, close further dispatch, and then request runtime
   interruption. Distinguish “no further Quarry tool execution” from “no further
   model computation”; only promise the latter with runtime evidence.

4. **I would use a step-level interface, but defer the broad controller
   refactor.** Adapting `Provider.complete` through paused callbacks introduces
   hidden runtime state, pending replies, transcript reconciliation, and
   cancellation machinery behind a synchronous raw-response contract. Use that
   approach only if a probe establishes an actual supported
   single-response/pause/resume boundary. Initially wrap the existing API loop
   as one step implementation; extract only shared dispatch policy and outcome
   construction. Let each subscription adapter own its protocol lifecycle. A
   common controller should not pretend to own all three model loops.

5. **Do not choose HTTP MCP merely for transport uniformity.** Dynamic tools
   plus in-process MCP avoid listener lifecycle and shared-host authentication
   work, but their suitability remains unproven. Share tool definitions and
   dispatch semantics first. Prefer those direct transports if both pass the
   capability probes; use HTTP MCP if it resolves a demonstrated integration
   limitation. On a shared machine, loopback binding alone would not
   authenticate callers.

6. **Completion and failure semantics need an explicit contract.** Recipe
   tidying accepts only a completed response and rejects truncation before
   validating code:
   [tidy.py:31](/Users/sunpar/workspace/quarry/src/quarry/projects/tidy.py:31).
   A text-only method returning just a string loses that distinction. Return
   text plus terminal status, with all tools disabled. For steps, preserve
   executed runs even when the runtime crashes after execution but before
   acknowledging its result;
   [service.py:387](/Users/sunpar/workspace/quarry/src/quarry/server/service.py:387)
   already preserves this evidence. Never automatically rerun a step after such
   an ambiguous failure.

Before committing to architecture, put these bounded probes first in the plan:

- **Auth and configuration:** pinned runtime versions, same-user Linux
  subscription authentication, explicit billing mode, inherited configuration
  control, and no API-key fallback.
- **Tool boundary:** register all five tools; demonstrate native-tool exclusion;
  exercise concurrent requests, malformed Python arguments, two failures
  separated by another tool, and cancellation with queued calls.
- **Runtime lifecycle:** establish what limits actually count; interrupt while
  waiting on the model and during tool execution; verify process cleanup and
  preservation of completed execution after disconnect.
- **Result mapping:** capture successful completion, refusal, truncation,
  quota/auth failure, and text-only tidying; define their Quarry statuses and
  transcript representation.
- **Then implementation tasks:** one Codex step adapter, minimal shared
  execution policy, configuration/factory wiring for both prompt and tidy paths,
  replay/cancellation verification, followed by Claude using the established
  contract.

I verified the local Quarry claims. The supplied T3 and vendor capability claims
remain caller-provided evidence: this review made no network calls, and no
protocol traces or pinned SDK capability results were supplied. Those missing
results prevent a firm commitment to tool exclusion, exact limits, or either
transport.

</details>
