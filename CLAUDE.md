# abletest — AbletonOSC + CLI

Control Ableton Live 12 from the command line (and from Claude Code) via
[AbletonOSC](https://github.com/ideoforms/AbletonOSC).

## Docs for agents (read these before operating)
- **`AGENT_GUIDE.md`** — how to drive these tools effectively: value semantics
  (normalized vs. real units), browser-loading recipes, exit-code/JSON contract,
  safe-operation checklist. **Read this before composing or mixing.**
- **`testProjects/TipsNTricks.md`** — accumulated lessons learned, gotchas, and
  workaround techniques discovered while composing. **ALWAYS read this before
  starting a new composition, and ALWAYS append to it** whenever you discover a
  new gotcha, workaround, or non-obvious technique. Keep it current.
- **`BUILD_NOTES.md`** — what was built, design decisions, and the
  browser-handler restart gotcha.
- **`build_plan.md`** — roadmap (tiers 1/2/4 done; tier 3 deferred).

## Layout
- `abletonosc_cli/` — the CLI package
  - `osc_client.py` — synchronous OSC request/response transport (send 11000, recv 11001)
  - `live.py` — high-level typed API over AbletonOSC address patterns
  - `notes.py` — note-name <-> MIDI conversion (C3 == MIDI 60, Ableton convention)
  - `device_specs.py` — friendly param aliases per device `class_name` (typed `fx`)
  - `cli.py` — argparse CLI, JSON output, `raw` escape hatch
- `.venv/` — virtualenv with `python-osc`; the `abletonosc` console script lives here

AbletonOSC itself is installed at:
`~/Music/Ableton/User Library/Remote Scripts/AbletonOSC`

## Running
Use the venv's console script:
```
.venv/bin/abletonosc status
```

## One-time setup in Ableton (required)
AbletonOSC must be enabled as a Control Surface:
1. Restart Ableton Live (so it detects the newly installed script).
2. Preferences > Link, Tempo & MIDI (the "Link / MIDI" tab).
3. Under **Control Surface**, pick **AbletonOSC** from the dropdown.
4. `abletonosc status` should then report `"connected": true`.

When active, Live listens on UDP 11000. Verify with:
`lsof -nP -iUDP:11000`

## CLI cheat sheet
```
abletonosc status                              # connection + transport
abletonosc tempo set 128
abletonosc track create-midi --name Bass
abletonosc clip create 0 0 --length 4          # track 0, slot 0, 4 beats
abletonosc clip add-notes 0 0 --notes "C3:0:1,E3:1:1,G3:2:1"
                                               # pitch:start:duration[:velocity]
abletonosc clip fire 0 0
abletonosc transport play
abletonosc song tracks
abletonosc raw /live/song/get/tempo --query    # escape hatch for any address

# --- mixing, loading & helpers (build_plan tiers 1, 2, 4) ---
abletonosc doctor                              # diagnose connection/version/ports
abletonosc device list 0                       # devices on track 0
abletonosc device params 0 0                   # params of track 0 / device 0
abletonosc device set 0 0 Volume 0.5           # set by index OR name (case-insens.)

abletonosc return create                       # add a return track
abletonosc return delete 0                     # delete return track 0
abletonosc track send 0 0 0.4                  # send 0 of track 0 -> 0.4 (omit to get)

abletonosc browser categories                  # instruments, drums, audio_effects, ...
abletonosc browser list instruments            # immediate children of a path
abletonosc browser search Operator --category instruments
abletonosc browser load 0 "query:Synths#Operator"   # load by URI onto track 0
                                               # (selects the track, polls until loaded)

abletonosc fx eq8 0 0 --low-gain -3 --high-freq 0.9  # typed device params by alias
abletonosc fx reverb 0 1 --decay 0.8 --dry-wet 0.35

abletonosc clip duplicate 0 0 0 1              # copy track0 slot0 -> track0 slot1
printf 'tempo set 120\nsong info\n' | abletonosc batch   # many cmds, one socket

# --- hearing your own work: audio capture + Gemini critique ---
abletonosc audio devices                       # list inputs; flags loopback device
abletonosc audio capture-clip 0 0 --out c.wav  # fire clip 0/0, record its length
abletonosc audio review-clip 0 0               # capture-clip + Gemini critique (one step)
abletonosc audio review-clip 0 0 --ask "is the bass muddy?"   # specific question
abletonosc audio critique c.wav                # critique an existing WAV (structured JSON)
                                               # default model gemini-3.5-flash;
                                               # --model gemini-3.1-flash-lite = cheaper, qualitative only
```

All commands accept `--json` (place it **before** the subcommand:
`abletonosc --json status`). Indices are 0-based. Note names accept `#`/`s`
(sharp) and `b`/`f` (flat), e.g. `F#4`, `Bb2`.

## Notes for composing
- Times and durations are in **beats**. A 4/4 bar = 4 beats.
- Create a clip before adding notes; `--length` sets the clip/loop length.
- `clip get-notes` returns notes with both `pitch` (name) and `midi` number.

## Notes for loading & mixing
- **Browser loading is a Live-side handler** (`abletonosc/browser.py` in the
  install — added beyond stock AbletonOSC). Adding/replacing handler modules
  requires a full **Ableton restart** (the in-place `/live/api/reload` can't
  register a brand-new handler module).
- Address browser items by **`uri`** (stable), not index. Find a uri with
  `browser search` or `browser list`, then `browser load <track> <uri>`.
- Loading targets the selected track; `browser load` selects it for you, then
  **polls `num_devices`** to confirm (loading is async). `--no-wait` skips the poll.
- **Device parameters are often normalized 0.0–1.0**, not Hz/seconds (e.g. EQ
  Eight `Frequency`, Reverb `Decay Time`). Gains are in dB. `device params`
  reports each param's real `min`/`max` — values outside the range are rejected.
- **Typed `fx` helpers** map friendly aliases to real parameter names, resolved
  **at runtime** (never hard-coded indices). Aliases live in `device_specs.py`,
  keyed by device `class_name`. `fx` refuses to run if the device class doesn't
  match (e.g. `fx reverb` on an EQ Eight).

## Notes for audio self-critique (hearing your own work)
- The `audio` commands let Claude **hear** its output: capture Live via a
  **loopback device** (one-time BlackHole + Multi-Output setup — see
  `AGENT_GUIDE.md` §10b), then critique with Gemini's native audio models.
- `doctor` reports `audio_loopback` and `gemini_key` as **advisory** checks; both
  must be `ok` for the loop to work. Key comes from `GEMINI_API_KEY` (env/`.env`).
- Every capture flags `silent: true` if nothing played — check it before trusting
  feedback. Default model `gemini-3.5-flash` is accurate; `gemini-3.1-flash-lite`
  is qualitative-only (don't trust it for pitch/tuning). Modules: `audio.py`
  (capture) and `gemini.py` (critique).
