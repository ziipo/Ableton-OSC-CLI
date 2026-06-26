# abletest — AbletonOSC + CLI

Control Ableton Live 12 from the command line (and from Claude Code) via
[AbletonOSC](https://github.com/ideoforms/AbletonOSC).

## Layout
- `abletonosc_cli/` — the CLI package
  - `osc_client.py` — synchronous OSC request/response transport (send 11000, recv 11001)
  - `live.py` — high-level typed API over AbletonOSC address patterns
  - `notes.py` — note-name <-> MIDI conversion (C3 == MIDI 60, Ableton convention)
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
```

All commands accept `--json` for compact machine-readable output. Indices are
0-based. Note names accept `#`/`s` (sharp) and `b`/`f` (flat), e.g. `F#4`, `Bb2`.

## Notes for composing
- Times and durations are in **beats**. A 4/4 bar = 4 beats.
- Create a clip before adding notes; `--length` sets the clip/loop length.
- `clip get-notes` returns notes with both `pitch` (name) and `midi` number.
