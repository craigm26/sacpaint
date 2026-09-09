# Running sacpaint on a real arm (OpenCastor + SO-ARM101)

The `opencastor` embodiment drives a pen bolted to an SO-ARM101 wrist. Every
motion goes through the [robot-md-gateway](https://github.com/craigm26/robot-md-gateway)
`/v1/invoke`, so every stroke leaves an Ed25519-signed receipt and a refusal is
a signed promise that nothing moved. The overhead camera can be the robot's own
console, a phone bridge, or the OpenCastor iOS app — anything that answers an
HTTP GET with the latest JPEG.

The policy still speaks the same canvas-frame metres the mock plotter speaks, so
a run that works against `sacpaint_plotter` works here with one flag changed.

Budget ten minutes. Most of it is taping down a sheet.

---

## 1. Install (1 min)

```bash
pip install 'sacpaint[opencastor]'
```

The extra pulls in nothing: the adapter talks HTTP with `urllib` from the
standard library and decodes frames with the OpenCV that `sacpaint` already
needs. It exists so `[opencastor]` stays a stable install target if that ever
changes.

Check the body registered:

```bash
inspect-robots list | grep opencastor
```

## 2. Set the fixture (3 min)

- Tape a **150 × 200 mm sheet, portrait**, flat on the desk in front of the arm.
  A5 or half a sheet of letter paper, trimmed. The whole sheet is inside an
  SO-ARM101's reach, so no part of the drawing is unreachable. Flat matters
  more than square: the calibration handles rotation and offset, but it assumes
  the sheet is a plane.
- Fit the pen to the wrist and take the cap off. **On an SO-ARM101, mount it at
  an angle**, not straight down the wrist axis — see the note in step 4. You
  want the tip near vertical when the arm is in its natural reaching pose.
- Point a camera at the sheet. Any angle. **No printed markers are needed** —
  the scorer rectifies from the corners you tap in the phone app, or finds the
  ArUco markers if you happen to use them, or falls back to the largest bright
  quadrilateral (a white sheet on a darker desk).
- Find the camera's snapshot URL and check it returns a picture:

  ```bash
  curl -s -o /tmp/f.jpg -w '%{http_code} %{content_type}\n' \
      -H "Authorization: Bearer $CONSOLE_TOKEN" \
      http://<robot>:8002/camera/<name>/snapshot
  ```

  `200 image/jpeg` is what you want. List the cameras with
  `curl -s -H "Authorization: Bearer $CONSOLE_TOKEN" http://<robot>:8002/camera/list`.

  > **Not `/api/snapshot/latest`.** That OpenCastor endpoint returns a JSON
  > state snapshot with no pixels in it. The frame endpoints are the console's
  > `/camera/<name>/snapshot` (port 8002 on Bob) and the runtime's
  > `/api/detection/frame`.

## 3. Teach the canvas corners (4 min)

The arm has to know where the sheet is, to about a millimetre. Bob's OAK-D
extrinsic has a 142 mm residual — fine for a gripper, useless for a pen — so the
transform is *taught*, not derived.

Jog the pen to each corner and record where the arm says it is:

```bash
python -m sacpaint.opencastor.calibrate \
    --out canvas.json \
    --pair-payload /path/to/pair-payload.json \
    --start 180,0,-60
```

It walks the corners in order **bl, br, tr, tl** (bottom-left first; the same
order the sheet reads). At each one you nudge in arm-base millimetres until the
pen tip sits exactly on the corner, then press `r`:

```
  x+ / x- / y+ / y- / z+ / z-   nudge by the step size
  s <mm>                        set the step size (default 5 mm)
  g <x,y,z>                     go to an absolute base position
  r                             record this corner and move on
  q                             give up
```

Three corners are enough. Four make the reported residual worth reading.
Nothing moves without a keystroke, and the first move waits for a confirmation.

If you already know the numbers, skip the arm entirely:

```bash
python -m sacpaint.opencastor.calibrate --out canvas.json \
    --corner bl=120,75,-95 --corner br=120,-75,-95 --corner tl=320,75,-95
```

That example puts the sheet flat in front of the arm with canvas x running
toward base −y and canvas y running away from the base. It fits a right-handed
frame with the canvas normal pointing up, which is what the guard below checks.
Its far corner sits 329 mm from the base, inside the SO-ARM101's ~370 mm reach,
so the arm covers the whole sheet.

Add `--reference NAME` for a custom reference with a different sheet size; the
tool takes its corner positions from that reference's spec.

Either way it prints the fit quality:

```
wrote canvas.json
  corners      ['bl', 'br', 'tl']
  rms residual 0.41 mm
  max residual 0.63 mm
```

**Over 2 mm and it warns you.** Take the warning seriously: the pen will miss by
that much everywhere, and `landmark_geometry` scores position, so a systematic
2 mm offset is a real score loss. Re-teach the worst corner.

Two failures the fit catches for you:

- *"the taught canvas points are collinear"* — you taught three corners along
  one edge. Teach corners that span the sheet.
- *"the fitted canvas normal points down"* — two corner labels are swapped.
  Lifting the pen would drive it into the paper. `bl br tr tl` run
  anticlockwise as the drawing is read.

## 4. Run (2 min)

```bash
inspect-robots run \
    --task sacpaint/photo-v1 \
    --policy agent \
    --embodiment opencastor \
    -P model=anthropic/claude-fable-5 \
    -E pair_payload=/path/to/pair-payload.json \
    -E calibration=canvas.json \
    -E overhead_url="http://192.168.68.90:8002/eval/frame/latest?stream=overhead&max_age_s=3" \
    -E corners_url="http://192.168.68.90:8002/eval/corners?stream=overhead" \
    -E actuator_name=so-arm101 \
    -E move_tool=arm.reach_point \
    -E move_args=reach_point \
    -E speed=0.3
```

> **Why `arm.reach_point` on an SO-ARM101.** The default `arm.move_to` holds the
> tool pointing straight down, and on this arm that needs `wrist_flex` at about
> +1.47 rad against a measured safe ceiling of +0.41 rad. A 25,480-point sweep
> found **zero usable poses**: `arm.move_to` denies *every* target with
> `actuator_policy/unsafe_pose`, and nothing moves. `arm.reach_point` reaches
> the same points with no tool-orientation constraint, which is why the pen is
> mounted at an angle in step 2 — the mount, not the wrist, is what makes the
> tip vertical. Keep the `arm.move_to` default on an arm whose wrist can
> actually point down.

The adapter asks before it moves:

```
Fresh sheet taped down, pen capped off, hands clear of the arm — press Enter to start:
```

For an unattended run add `-E no_prompt=true` — **the arm then starts moving
with no confirmation**. The gate also skips itself when there is no TTY, rather
than hanging an overnight eval on a dead stdin.

The `sacpaint run` wrapper turns on artifacts and frame storage for you:

```bash
sacpaint run --embodiment opencastor --model anthropic/claude-fable-5 \
    -- -E pair_payload=/path/to/pair-payload.json -E calibration=canvas.json
```

---

## No paper or pen: the virtual easel (`-E medium=virtual`)

When the rig has an arm but nothing to draw with, the same body runs the whole
benchmark loop with the sheet replaced by telemetry. The arm makes every motion
for real through the gateway (signed receipts and all); after each pen-down
move the adapter asks `arm.state` where the tip actually is and inks the
segment on a canonical canvas. That canvas is the `overhead` frame (marked
`canonical_canvas`, nothing to rectify), and every score is labelled
`medium=virtual`, never comparable with a mark on paper.

```bash
sacpaint run --policy sacpaint_trace --embodiment opencastor --no-rerun --no-prompt \
  -- -E pair_payload=/home/craigm26/bob/pair-payload.json \
     -E medium=virtual -E calibration=easel \
     -E move_tool=arm.reach_point -E move_args=reach_point \
     -E tolerance_mm=5 -E strict_reach=false
```

`calibration=easel` is a sheet that is not there, so it is refused with a real
pen. Where it stands was measured on Bob on 2026-09-09: with his calibrated
joint limits the tip reaches a thin shell roughly 300–370 mm from the base,
which no flat sheet on the desk fits inside, but an upright 150 × 200 mm sheet
325 mm straight ahead, centred at base height, does (every point within 0.5 mm
of a reachable pose; 8 of 9 probe points reached within 5 mm, the ninth at
5.9 mm). Move it with `-E easel_distance_mm`, `-E easel_elevation_deg` (the
sheet leans back with it) and `-E easel_azimuth_deg`.

Two things this mode changed in the driver, both live on Bob and in
`so-arm101-actuator` main: `arm.reach_point` now warm-starts from a table of
the safe envelope, waits for the joints to settle before measuring, and
compensates the servos' static error, because before that 0 of 27 reachable
points arrived. A miss now walks the arm back to the closest point it measured
and reports the error history; with `strict_reach=false` the adapter inks to
that measured point and carries on (the observation's `misses` counts them).

## The iPhone as the overhead camera (OpenCastor iOS build 76, Eval mode)

Open the OpenCastor app, pick the robot, open **Eval**, point the rear camera
at the sheet, tap **Stream**, then **Mark corners** (TL, TR, BR, BL). The app
posts JPEG frames and the corners to the robot console; the embodiment polls
them. Nothing is written to disk on the Pi; frames live in memory, one per
stream. The console URL is the robot's console port (Bob: 8002) and the token
is the read-only `CONSOLE_TOKEN` from `~/bob/tokens.env`.

| Purpose | URL |
|---|---|
| latest overhead frame (404 when absent or older than `max_age_s`) | `GET /eval/frame/latest?stream=overhead&max_age_s=3` |
| tapped corners, normalized 0..1 against the posted JPEG, TL TR BR BL | `GET /eval/corners?stream=overhead` |
| operator speech or typed lines (evidence, not commands) | `GET /eval/feedback?since=0` |
| the reference the app shows the operator | `GET /eval/reference.png` |
| one-poll summary, episode reset | `GET /eval/status`, `POST /eval/reset` |

So the two flags are `-E overhead_url="http://<robot>:8002/eval/frame/latest?stream=overhead&max_age_s=3"`
and `-E corners_url="http://<robot>:8002/eval/corners?stream=overhead"`, with
`-E camera_token_env=CONSOLE_TOKEN`. Full endpoint doc: `opencastor-runtime/docs/eval-eyes.md`.

## Every `-E` flag

### Gateway

| Flag | Default | What it does |
|---|---|---|
| `pair_payload` | — | Path to a `pair-payload.json`. **The shortcut:** fills `gateway_url`, `manifest_path`, the actuate bearer, the console URL and the console token from one file. Everything below overrides it. |
| `gateway_url` | `http://127.0.0.1:8080` | Gateway base URL. `/v1/invoke` is appended. |
| `manifest_path` | — | **Required.** Absolute path of `ROBOT.md` *on the robot*, e.g. `/home/you/bob/ROBOT.md`. The client sends no key id; the gateway verifies this file's signature and echoes back the kid it verified. |
| `manifest_kid` | — | Assert the gateway verified this key id. A mismatch aborts before the receipts could attest to a different manifest than the run claims. |
| `token` | — | Actuate-tier bearer. Prefer `token_env` or `pair_payload`; a token on a command line lands in your shell history. |
| `token_env` | `ROBOT_MD_TOKEN` | Environment variable to read the bearer from. |
| `ruri` | `rcan://demo.local/bob` | RCAN resource id. Also settable as `$ROBOT_MD_RURI`. |
| `actuator_name` | `so-arm101` | Which actuator on a multi-actuator gateway. Omitting it on Bob risks a `422 actuator_name_required`. |
| `timeout_s` | `30` | Per-invoke HTTP timeout. A long stroke at low speed needs headroom. |
| `move_tool` | `arm.move_to` | The cartesian tool to call. **Use `arm.reach_point` on an SO-ARM101** — see step 4. |
| `move_args` | `move_to` | Argument spelling: `move_to` sends `{x_mm, y_mm, z_mm, speed?}`; `reach_point` sends `{target_mm: [x,y,z], tolerance_mm}`. Must match `move_tool`. |
| `state_tool` | `arm.state` | Tool asked for the tip position at reset; returns `{joint_positions_rad, eef_mm, tool}` under scope `OBSERVE`. Set `-E state_tool=` (empty) on a gateway that has none — the adapter then uses the commanded pose. |
| `home_tool` | `arm.home` | Tool called by `reset()`. |
| `speed` | — | Passed through to `arm.move_to` when set; omitted entirely when not. |
| `tolerance_mm` | `3.0` | Arrival tolerance, `move_args=reach_point` only. |
| `strict_reach` | `true` | Halt when the arm reports `reached: false`. Set `false` to score runs whose targets were missed — the pen's position is then not what the transcript says it is. |

### Geometry

| Flag | Default | What it does |
|---|---|---|
| `calibration` | — | **Required.** Path to the `canvas.json` from step 3, or `easel` (virtual medium only). |
| `medium` | `pen` | `pen` (a pen on a photographed sheet) or `virtual` (no paper: the canvas is inked from the arm's measured tip; see above). |
| `easel_distance_mm` / `easel_elevation_deg` / `easel_azimuth_deg` | `325` / `0` / `0` | Where the virtual easel stands: distance from the base to the sheet's centre, its elevation above the base plane, its bearing left of straight ahead. |
| `reference` | `sacramento-photo-v1` | Which reference to serve on the `reference` camera. Match the task. |
| `pen_down_z` | `0.002` | Canvas-frame height at or below which the pen marks (metres). |
| `travel_z` | `0.005` | Height that travels without marking. Must be above `pen_down_z`. |
| `park_x`, `park_y` | `0.0`, `0.0` | Where `observe_parked()` parks, in canvas metres. Move it if the arm blocks the camera's view of the sheet there. |
| `park_z` | `0.03` | How far the pen lifts for the final, scored photograph. |

### Cameras

| Flag | Default | What it does |
|---|---|---|
| `overhead_url` | `<console_url>/camera/overhead/snapshot` | Any HTTP endpoint returning the latest JPEG or PNG. A JSON reply is accepted too: the adapter reads `image_b64` (or a `data:` URI), or follows a single `image`/`url` field. |
| `overhead_prime_url` | — | Fetched and discarded immediately before each frame, for rigs whose latest-frame file is only written as a side effect. The carbot phone bridge needs `-E overhead_prime_url=http://<pi>:8100/look -E overhead_url=http://<pi>:8100/snapshot.jpg`. |
| `camera_token` | — | Bearer for the camera endpoint (Bob's console wants `CONSOLE_TOKEN`). |
| `camera_token_env` | `CONSOLE_TOKEN` | Environment variable to read it from. |
| `camera_timeout_s` | `5.0` | Per-frame HTTP timeout. |
| `corners_url` | — | Where the iOS app posts the four tapped sheet corners. Fetched once per trial and attached to every observation as `extra["canvas_corners"]`, which is the scorer's first and best rectification route. |
| `canvas_corners` | — | The same four corners typed in: `-E canvas_corners=x,y,x,y,x,y,x,y`, normalised 0..1, order **TL TR BR BL**. Use it when there is no corner service. |

### Operator and logs

| Flag | Default | What it does |
|---|---|---|
| `no_prompt` | `false` | Skip the readiness gate. The arm moves with no confirmation. |
| `receipts_dir` | `logs/receipts` | Where `close()` writes the receipts if no trial hook ever fires (see below). |

---

## What a run leaves on disk

```
logs/
 ├── sacpaint-line-v0_<id>.json          # the EvalLog: config, git rev, package versions,
 │                                       #   per-scorer scores, and the full transcript
 ├── frames/<run>/                       # what the model saw each step (with --store-frames)
 ├── actions/<run>.jsonl                 # the executed action sequence
 └── receipts/
     └── opencastor-<timestamp>.jsonl    # one signed gateway receipt per motion
canvas.json                              # your calibration, unchanged by the run
```

Each line of the receipts file is one gateway call — allowed or denied — with
the tool, the arguments actually sent, the `msg_id` (the gateway's replay key),
the HTTP status, and the gateway's whole response including
`envelope_signature` and `outcome`. **The bearer is never written.** Verify one
with the gateway's own `scripts/verify_receipt.py`.

A note on where that file lands: the Inspect Robots core offers `on_trial_start`
/ `on_trial_end` to *policies*, not to embodiments, and `TaskEnvelope` carries
no log directory. The adapter implements both hooks anyway — a wrapper or a
future core that calls them gets receipts written to
`<log_dir>/receipts/<run_id>/<scene>-epoch<n>.jsonl`, beside the eval log. Until
then `close()` is the guarantee, writing to `receipts_dir`. Either way,
`embodiment.receipts` holds every call in memory for the life of the run.

To publish:

```bash
sacpaint export logs --out submission --label opus
```

---

## When it goes wrong

Every failure names the URL or the tool and tells you the fix. The ones you will
actually hit:

| Message | Meaning |
|---|---|
| `gateway denied 'arm.move_to': tool_allowlist` | The tool is not in the gateway's operator allowlist. Add it to `ROBOT_MD_TOOL_ALLOWLIST` **and** `ROBOT_MD_TOOL_MIN_TIER` in the gateway's policy env and restart the gateway. Nothing moved. |
| `gateway denied ...: tier_policy` | An unknown or missing bearer degrades to the `anon` tier, which may not actuate. Check `-E token_env`. |
| `gateway denied ...: safety_state` | The software stop is engaged. Clear it at the console. |
| `gateway denied ...: actuator_policy/unsafe_pose` | The pose needed to satisfy the tool-orientation constraint is outside the arm's safe joint range. On an SO-ARM101 this denies **every** `arm.move_to` target: use `-E move_tool=arm.reach_point -E move_args=reach_point` and angle the pen mount. |
| `gateway denied ...: actuator_policy/unreachable` (or `out_of_workspace`) | The arm's links cannot span to that point. Move the sheet closer to the base and re-teach the calibration. Nothing moved — the driver clamps nothing. |
| `gateway denied ...: actuator_policy/joint_limits` | Reaching that point needs a joint past its safe range. Move or rotate the sheet. |
| `the gateway at ... has no 'arm.move_to' (404)` | An older gateway. Use `-E move_tool=arm.reach_point -E move_args=reach_point`. |
| `the driver failed 'arm.move_to': OutOfRangeError ...` | An unsigned 500: the arm's position is **unknown**. Check the robot before re-running. Reachability now normally arrives as a signed `unreachable` deny instead. |
| `the arm reports it did not reach ...` | The move completed but missed. Every later stroke would start from somewhere unknown, so the run halts. |
| `camera 'overhead' at ... returned HTTP 503` | The camera is cold or absent. Start it. A missing frame is not a blank canvas, and the adapter refuses to score one as if it were. |
| `camera 'overhead' at ... is unreachable` | Wrong host or port, or the console is not running. |
| `no canvas calibration` | Step 3. |

`SafetyAbort` (a deny) and `EmbodimentFault` (a camera or driver failure) both
halt the whole eval, by design: a faulted or refused robot must never
auto-advance to the next sheet unattended.

## What this body deliberately does not do

- **It never sets `canonical_canvas`.** A photograph of a sheet is not a
  canonical canvas, and claiming otherwise would skip the rectification that
  makes the score comparable to the mock plotter's.
- **It never moves on `close()`.** An adapter that moves after the operator
  thinks the run is over is an adapter nobody can stand next to.
- **It clamps every target to the canvas box before the transform**, so a model
  asking for a point 9 metres off the sheet gets the sheet's edge, not a
  gateway deny and a dead run.
