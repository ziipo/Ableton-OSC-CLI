# Operating abletest — Guide for AI Agents

A task-oriented reference for an agent (Claude Code, Codex, etc.) driving Ableton
Live 12 through the `abletonosc` CLI. Read this before composing or mixing. The
short cheat sheet lives in `CLAUDE.md`; this file covers the **semantics,
gotchas, and recipes** you need to operate reliably.

---

## 0. The mental model

```
your shell  →  abletonosc CLI  →  OSC/UDP (send 11000, recv 11001)  →  AbletonOSC
            (python, this repo)                                      (Remote Script in Live)
```

- The CLI is a **synchronous request/response** wrapper. Each invocation opens a
  socket, sends, (optionally) waits for a reply, prints, and exits.
- Live must be **running** with the **AbletonOSC control surface enabled**
  (Preferences → Link/Tempo/MIDI → Control Surface → AbletonOSC). If it isn't,
  every command times out with a clear message.
- **Always run `abletonosc doctor` first** in a fresh session. If
  `connected: false`, stop and tell the user to enable the control surface —
  nothing else will work.

## 1. Invocation rules (these bite if you get them wrong)

- **`--json` goes BEFORE the subcommand**: `abletonosc --json status`, *not*
  `abletonosc status --json`. The flag is global. Always use `--json` when
  parsing output programmatically.
- Other globals (also before the subcommand): `--host`, `--send-port`,
  `--recv-port`, `--timeout`.
- **All indices are 0-based** (tracks, clip slots, devices, scenes, sends).
- Use the venv binary: `.venv/bin/abletonosc`. (Per `CLAUDE.md`.)

## 2. Output contract & exit codes

Every command prints one JSON object (with `--json`). Two shapes:

- **Success**: either a data object (`{"tracks": [...]}`) or `{"ok": true, ...}`.
- **Failure**: `{"error": "..."}` (transport/OSC error, exit code **2**) or,
  for logic failures that still completed the round-trip,
  `{"ok": false, "error": "..."}` (exit code **0** — check the body, not just
  the code!).

Exit codes: `0` success, `1` bad input/usage (ValueError), `2` OSC/transport
error. **Do not trust exit code alone for `browser load` / `fx` — inspect `ok`.**

Errors that come straight from Live look like:
`{"error": "AbletonOSC error: ('Error handling OSC message: Index out of range',)"}`
— almost always a bad track/device/clip index.

## 3. Value semantics — THE most common mistake

Many device parameters are **normalized 0.0–1.0**, NOT in Hz / seconds / dB.
Examples on stock Live 12 devices:

| Looks like… | Actually… |
|---|---|
| EQ Eight `Frequency`, `Q` | normalized 0.0–1.0 |
| EQ Eight `Gain` | **dB**, −15.0…15.0 |
| Reverb `Decay Time`, `Room Size`, `Dry/Wet` | normalized 0.0–1.0 |
| Compressor `Threshold`, `Ratio`, `Attack` | normalized 0.0–1.0 |
| Track `volume`, `send` | normalized 0.0–1.0 (0.85 ≈ 0 dB) |
| Track `panning` | −1.0 (L) … 1.0 (R) |

**Never assume units.** Run `abletonosc --json device params <track> <device>`
first — it returns each parameter's real `min`/`max`. Values outside the range
are **silently rejected by Live** (the CLI reports `ok: true`, but the value
won't change). For typed `fx` commands, ranges are validated client-side and you
get `{"ok": false, "error": "... out of range ..."}`.

## 4. Browser loading (the part that needs care)

Loading instruments/effects/presets goes through a **custom Live-side handler**
(`abletonosc/browser.py`, installed beyond stock AbletonOSC). Key facts:

1. **Address items by `uri`, never by index.** URIs are stable
   (e.g. `query:Synths#Operator`, `query:AudioFx#Reverb`,
   `query:Drums#FileId_5483`). Find them with `browser search` or `browser list`.
2. **Loading targets the selected track.** `browser load <track> <uri>` selects
   the track for you, then loads — you don't need a separate select call.
3. **Loading is async.** `browser load` polls `num_devices` (up to ~5s) and
   reports `confirmed`. Trust `confirmed` / `devices_after`, not just `ok`.
4. **Effects append to the device chain** in load order. To get
   `Instrument → EQ → Reverb`, load them in that sequence.
5. If the handler is missing (`Unknown OSC address: /live/browser/...`), Ableton
   needs a **full restart** — the in-place `/live/api/reload` cannot register a
   brand-new handler module. (See `BUILD_NOTES.md`.)

### Recipe: load an instrument onto a new track
```bash
abletonosc --json track create-midi --name "Keys"
# new track index = (num_tracks - 1) after creation
abletonosc --json browser search "E-Piano" --category instruments
abletonosc --json browser load <track> "<uri-from-search>"
# confirm: response.confirmed == true, devices_after > devices_before
```

### Recipe: drum kit
```bash
abletonosc --json browser list drums          # *.adg entries are full kits
abletonosc --json browser load <track> "query:Drums#FileId_5483"   # 808 Core Kit
```

## 5. Typed effects (`fx`) — friendly params

`fx <type> <track> <device> --alias value …` sets device parameters by friendly
alias instead of raw indices. Aliases resolve to **real parameter names at
runtime** (robust across Live versions); they're defined in `device_specs.py`,
keyed by device `class_name`.

- Supported: `eq8`, `compressor`, `reverb`, `autofilter`, `limiter`, `utility`.
- `fx <type> --help` lists that device's aliases **with their ranges**.
- `fx` **refuses to run if the device class doesn't match** (e.g. `fx reverb` on
  an EQ Eight returns `{"ok": false, ...}`). It uses the device's `class_name`,
  so the `<device>` index must point at the right device.
- Values still obey the param's native range/units (see §3): EQ `--low-gain` is
  dB; Reverb `--decay` is normalized 0–1.

```bash
abletonosc --json fx eq8 0 0 --low-gain -3 --high-freq 0.9
abletonosc --json fx reverb 0 1 --decay 0.8 --dry-wet 0.35
```

For any device/param **not** covered by an `fx` helper, fall back to the generic
path, resolving by name: `abletonosc device set <track> <device> "<Param Name>" <value>`.

## 6. Mixing: sends & returns

- `return create` adds a return track; `return delete <i>` removes return `i`
  (0-based among returns).
- `track send <track> <send_idx> [value]` — send index matches return order
  (send 0 → return A). Omit `value` to read. Value is normalized 0.0–1.0.
- Typical reverb-bus recipe: create a return, load a Reverb onto it, then raise
  each dry track's `send 0`.

```bash
abletonosc --json return create
# (load a reverb onto the return track, which is the last track)
abletonosc --json track send 0 0 0.4
```

## 7. Batch execution (fast multi-command)

For generative/iterative work, avoid re-spawning the CLI per command — pipe many
commands over **one socket**:

```bash
printf 'tempo set 120\ntrack create-midi --name Bass\nclip create 4 0 --length 4\n' \
  | abletonosc --json batch
```

- One command per line; `#` lines and blanks are skipped. Lines are shell-tokenized.
- Do **not** put `--json` on individual lines; pass it once to `batch`.
- `--stop-on-error` aborts on the first failure (default: continue, collect all).
- Returns `{"ok", "count", "results": [{line, command, result|error}, ...]}`.
- Nested `batch` is rejected.

## 8. Inspecting state (do this before mutating)

| Want | Command |
|---|---|
| Is Live reachable? | `abletonosc --json doctor` |
| Track list | `abletonosc --json song tracks` |
| Track/scene counts | `abletonosc --json song info` |
| Devices on a track | `abletonosc --json device list <t>` |
| Device class names | `abletonosc --json raw /live/track/get/devices/class_name <t> --query` |
| A device's params (+min/max) | `abletonosc --json device params <t> <d>` |
| Clip names on a track | `abletonosc --json raw /live/track/get/clips/name <t> --query` |
| Notes in a clip | `abletonosc --json clip get-notes <t> <c>` |

## 9. The `raw` escape hatch

Anything not wrapped: `abletonosc raw <address> [args…] [--query]`. Use `--query`
when you expect a reply. Args are auto-typed (int → float → str). AbletonOSC
replies echo the id args first (e.g. `track_id`), so a reply to
`/live/track/get/send 0 0` is `[0, 0, <value>]`. This is the fallback when no
typed command exists.

## 10. Composing notes (MIDI)

- Create the clip first (`clip create <t> <c> --length <beats>`), then add notes.
- Times/durations are **beats**; a 4/4 bar = 4 beats.
- `clip add-notes <t> <c> --notes "C3:0:1,E3:1:0.5:80"` →
  `pitch:start:duration[:velocity]`. Pitch accepts names (`C3`, `F#4`, `Bb2`;
  C3 = MIDI 60, Ableton convention) or raw MIDI ints.
- `clip get-notes` returns both `pitch` (name) and `midi` number.

## 10b. Hearing your own work — audio capture + Gemini critique

The composer can drive Live but can't *hear* the result. The `audio` commands
close that loop: capture Live's output through a loopback device, then send it to
Gemini's native audio-understanding models for feedback. The `/critique-mix`
skill orchestrates the full workflow.

**Audio capture setup (one-time, required for any `audio capture*`):**
AbletonOSC can't render audio, so capture is realtime through a virtual device:

1. Install **BlackHole 2ch** (https://existential.audio/blackhole/).
2. In **Audio MIDI Setup**, create a **Multi-Output Device** that includes both
   your speakers/headphones **and** BlackHole (so you still hear playback while
   it's captured).
3. In Live: Preferences → Audio → set **Audio Output Device** to that
   Multi-Output Device.
4. Verify: `abletonosc --json audio devices` should list a `is_loopback: true`
   entry, and `doctor`'s `audio_loopback` advisory check should be `ok: true`.

**Commands:**
```
abletonosc audio devices                          # list inputs; flags loopback
abletonosc audio capture --seconds 8 --out x.wav  # raw N-second capture
abletonosc audio capture-clip 0 0 --out c.wav     # fire clip 0/0, record its length
abletonosc audio capture-master --bars 8 --out s.wav   # play + record 8 bars
abletonosc audio critique c.wav                   # structured JSON critique
abletonosc audio critique c.wav --ask "is the bass muddy?"   # specific question
abletonosc audio review-clip 0 0                  # capture-clip + critique, one step
abletonosc audio review-clip 0 0 --ask "do the hats swing?"
```

**Semantics & gotchas:**
- Capture timing is computed from **tempo + clip length in beats** (`capture-clip`)
  or `--bars` (`capture-master`); a `--tail` adds release time.
- Every capture reports `peak`/`rms` and a `silent` flag. **If `silent: true`,
  nothing played or routing is wrong — fix that before trusting any critique.**
- The Gemini key is read from `GEMINI_API_KEY` (env) or a `.env` at the repo root
  (gitignored). `doctor` reports `gemini_key` as an advisory check.
- **Model trust (see `testProjects/TipsNTricks.md`):** default
  `gemini-3.5-flash` is accurate and reasons over audio. `--model
  gemini-3.1-flash-lite` is cheaper but **qualitative-only** — don't trust it for
  pitch/tuning/key/octave verdicts. `gemini-3.5-flash` can return transient HTTP
  503 ("high demand"); the client retries with backoff.
- Inline audio limit is **20 MB** (~minutes of WAV); capture a shorter section if
  you hit it (File API upload isn't implemented).

## 11. Safe-operation checklist for agents

1. `doctor` → confirm `connected: true`.
2. `song tracks` / `device list` → learn indices before you mutate.
3. For params: `device params` → read real `min`/`max`; respect units (§3).
4. For loading: `browser search` → `browser load` → verify `confirmed: true`.
5. Prefer creating **new** tracks/clips over editing the user's existing ones
   unless asked; deleting is destructive and not undoable via the CLI’s normal
   flow (there is `song undo`, but don't rely on it for data you didn't create).
6. When you create scratch tracks for probing, **delete them afterward** (delete
   the highest index first to avoid reindex surprises).
7. Parse `--json`; check the `ok`/`error` body, not just the exit code.

## 12. Where things live

- CLI package: `abletonosc_cli/` (`cli.py`, `live.py`, `osc_client.py`,
  `notes.py`, `device_specs.py`).
- Custom Live-side handler: `abletonosc/browser.py` inside the AbletonOSC install
  at `~/Music/Ableton/User Library/Remote Scripts/AbletonOSC/`.
- Build/architecture notes & the restart gotcha: `BUILD_NOTES.md`.
- Roadmap (what's done / deferred): `build_plan.md`.
```
