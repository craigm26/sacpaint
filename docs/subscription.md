# Running the agent policy on a Claude subscription

`inspect-robots run --policy agent` talks to an LLM over HTTP. Normally that
means a metered `ANTHROPIC_API_KEY`. On a machine that has the Claude Code CLI
logged in but no API credits, `sacpaint-claude-shim` stands in: it serves an
OpenAI Chat Completions endpoint on localhost and answers each request with one
`claude -p` invocation, so the owner's own subscription drives the robot.

> [!WARNING]
> **Results from the shim are not comparable to API results.** Every answer is
> produced inside Claude Code's own harness and system prompt, not by the raw
> Messages API. Responses are labelled `wire=claude-code-cli` for exactly this
> reason. Do not put a shim run on a leaderboard, do not compare its score with
> an API run, and do not cite it as a model capability measurement. This is a
> development and personal-use path on the owner's own subscription.

## The one-flag way

```bash
sacpaint run --subscription --model haiku --policy agent --embodiment sacpaint_plotter --max-llm-calls 40
```

`sacpaint run --subscription` starts the shim on a free port, waits for its
health check, points the agent policy at it, labels every score artifact with
`wire: claude-code-cli`, and stops the shim when the run ends. Everything below
is what that flag does by hand.

## Install

`pip install sacpaint` installs the `sacpaint-claude-shim` console script;
`python -m sacpaint.claude_shim` works identically.

## Start it

```bash
sacpaint-claude-shim --port 8931 --model haiku \
    --claude-bin ~/.local/bin/claude --max-turns 6
```

`--claude-bin` matters when `PATH` is odd; pass the full path. Check it is up:

```bash
curl -s http://127.0.0.1:8931/healthz
# {"status": "ok", "model": "haiku", "calls": 0, "wire": "claude-code-cli"}
```

## Point the policy at it

```bash
export SACPAINT_SHIM_KEY=unused   # the shim ignores it; the flag needs a name

inspect-robots run --task sacpaint/line-v0 --policy agent \
    -P base_url=http://127.0.0.1:8931/v1 \
    -P api_key_env=SACPAINT_SHIM_KEY \
    -P model=haiku \
    -P images=on_demand \
    -P max_llm_calls=6 \
    --embodiment sacpaint_plotter --no-rerun --no-prompt \
    -T epochs=1 -T max_steps=300
```

`-P base_url=` is the first rung of the plugin's provider ladder, so no
provider key is consulted at all. `-P api_key_env=` names a variable the shim
does not check; point it at anything.

**Always set `-P max_llm_calls=`.** Each call spends subscription usage, and
the plugin's default is 100. A handful is enough to prove a rig.

## Verified run

That exact command was run on 2026-09-08 against `claude` 2.1.263 on a Pi with
no `ANTHROPIC_API_KEY`:

```
run status: completed
outcome: gave up            # LLM call budget exhausted, as configured
scenes: 1  trials: 1
  composite: 0
  discipline: 0
  efficiency: 0.8133
  landmark_geometry: 0
  structure: 0
log: .../shimlogs-sacpaint/sacpaint-line-v0_287b8911.json
```

Six shim calls, six valid tool calls, zero malformed replies, zero shim errors,
`llm_usage.llm_calls = 6`, `errored_trials = 0`. The model called `take_pic`
first, read the reference and overhead frames, and drove five `move_to` motions
that executed on the plotter (19, 16, 15 and 5 interpolated steps), lowering the
pen to `z=0.002` to draw the top horizontal line it had seen in the reference.

**`composite: 0` is the honest result of a six-call budget, not a shim fault.**
Six model turns cannot draw a skyline; the rollout stopped at step 55 of 300
with barely any ink down, so every geometry scorer reads zero. `efficiency`
is nonzero only because the trial used few steps. The run proves the transport,
not the model. Raise `max_llm_calls` for a scoring run and expect it to cost
accordingly.

## What the shim actually does

One HTTP request becomes one `claude -p`. Nothing is cached or carried between
requests: `inspect-robots` resends the whole conversation every turn, which is
what makes a stateless one-shot CLI call a faithful stand-in for the API.

| Wire concept | How the shim carries it |
|---|---|
| `system` messages | `claude --system-prompt` (replaces Claude Code's prompt) |
| conversation history | re-rendered into the prompt on stdin, every request |
| assistant `tool_calls` | replayed as `you called <tool> with arguments {...}` |
| `tool` results | replayed as `### TOOL RESULT (for call id ...)` |
| `tools` | described in prose **and** pinned by `claude --json-schema` |
| model's tool call | `{"tool": name, "arguments": {...}}` parsed back into `tool_calls` |
| images | written to a scratch file, read by the CLI's `Read` tool |
| usage | the CLI's `usage` block mapped to OpenAI token counters |

The prompt goes in on **stdin**, not argv: a long conversation would blow past
the argv size cap.

### Images do work

An image cannot ride inside a `claude -p` prompt. The shim decodes each
`image_url` data URL, writes it to a per-request scratch directory, and refers
to it by absolute path:

```
[image #1 saved at /tmp/sacpaint-shim-xxxx/ab12/frame_001.png
 -- call the Read tool on that exact path to see it]
```

The CLI is launched with `--allowedTools Read` and `--add-dir <scratch>` only
when the request carries an image, so the model can open it and nothing else.
This was verified end to end: the model read a real reference frame and moved
the pen toward the top line it saw. Frames are deleted after each request
unless `--keep-frames` is passed.

The cost is turns. A text-only request answers in one CLI turn; an image
request spends one turn on `Read` first, which is why `--max-turns` defaults to
6 rather than 1.

### Tool calls are never executed

The shim asks the model to *name* a tool and returns that name to
`inspect-robots`, which executes it and sends the result back — exactly as a
real API does. The shim has no robot access and runs nothing. `--restricted`
strips Bash and every other code-running tool from the CLI session, so a
prompt-injected instruction in an observation cannot reach a shell.

### Tolerant parsing, on purpose

`--json-schema` pins the answer to `{"tool": ..., "arguments": {...}}` and the
CLI returns it pre-parsed in `structured_output`. The parser still accepts
`name` instead of `tool`, `input`/`parameters` instead of `arguments`, a
stringified arguments object, a bare `{"done": {...}}`, and a JSON object
embedded in prose or a code fence. A step lost to a spelling difference is a
wasted robot turn. A tool name that is not in the request's tool list is
**not** smuggled through: the turn comes back as plain text and the policy
nudges, which is the safe failure.

## Cost

Every request re-sends the whole conversation and pays for Claude Code's
harness prompt again — about 10k cache-creation tokens per call even with
`--restricted`, which roughly halves it. Observed on a real image-bearing
request: 20,355 prompt tokens (9,699 cached) and 897 completion tokens.

The shim reports these back in the response's `usage` block. Note that the
plugin's `chat` wire records `llm_calls` only and drops per-token counts —
that is an `inspect-robots-agent` limitation, not a shim one. Read the shim's
own log for token counts.

## Limits and gotchas

- **The CLI exits non-zero while still printing a good answer.** Seen live: a
  complete envelope with `stop_reason: end_turn` and 3,115 output tokens
  alongside exit code 1. The shim parses stdout *before* judging the exit code
  for exactly this reason. An earlier version trusted the exit code, turned a
  paid call into a 502, and the policy's 5xx retry then spent a second one.
  Never reintroduce an exit-code-first check here.
- **`--restricted` is load-bearing.** It drops the code-running tools and cuts
  the harness prompt. Removing it roughly doubles the per-call token cost.
- **No streaming.** The endpoint answers only when the CLI process exits.
  Latency per step is the CLI's full round trip, several seconds at least.
- **One CLI process per request**, so throughput is low. Fine for a single
  rollout; do not point a sweep at it.
- **`--model` takes CLI aliases** (`haiku`, `sonnet`, `opus`, `fable`) or a
  full model id. A request's own `model` field wins over the server default,
  so `-P model=haiku` selects the model per run.
- **The shim strips `ANTHROPIC_API_KEY`** from the CLI's environment. The
  point is the subscription; a stray key would silently meter the run.
- **Bind address stays `127.0.0.1`.** There is no authentication: anything that
  can reach the port can spend the subscription.
- **`inspect-robots` logs record `wire=chat`**, because that is the wire the
  plugin spoke. The `claude-code-cli` label lives in the shim's own responses
  and in this document. When you save a result, write the label down yourself.

## Anthropic Messages endpoint

`POST /v1/messages` is served too, for callers that need `-P wire=messages`:
`system` (string or blocks), `tool_use`/`tool_result` blocks, and native
`input_schema` tool declarations are all understood, and the reply carries
`tool_use` blocks with Anthropic-shaped `usage`. Note the plugin's Messages
wire also wants `-P max_output_tokens=`, which the CLI ignores.

## Tests

`tests/test_claude_shim.py` covers both directions of the translation against a
**fake** `claude` binary — a script that records its argv and stdin and echoes
canned JSON. The real CLI is never invoked by the suite: it costs subscription
usage, needs a login and network, and its latency would make the tests
useless.

```bash
pytest tests/test_claude_shim.py
```
