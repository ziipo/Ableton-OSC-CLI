# abletest — Build Plan

Roadmap for fleshing out the AbletonOSC-based CLI control surface. The goal:
keep the **dependable OSC core** (our CLI → OSC → AbletonOSC → Live), and fill
the capability gaps — primarily **instrument/effect loading** and **mixing** —
that currently force manual steps in Ableton.

## Guiding principles
- **Keep the OSC core.** Stay on the standard AbletonOSC address surface so we
  remain interoperable (TouchOSC, Max, other OSC tools).
- **Wrap, don't rebuild.** Where AbletonOSC already exposes an address, just
  surface it in our CLI. Add a new AbletonOSC handler **only** where the address
  genuinely doesn't exist.
- **Consistent contract.** Every command ships behind `--json` with the existing
  `{ok: true, ...}` / `{error: ...}` shape and stable exit codes.
- **Dependency-light core.** Heavy/optional dependencies (e.g. FFmpeg) live in
  separate modules, not the core.

## What already exists in AbletonOSC (verified by reading the installed source)
These need **CLI-only** work — no Live-side changes:
- **Device parameters** — `/live/device/get|set/parameter[s]/...` (full get/set).
- **Track sends** — `/live/track/get/send`, `/live/track/set/send`.
- **Return tracks** — `create_return_track` / `delete_return_track` in song.py.
- **View / selected track** — `/live/view/set/selected_track` (needed to target
  a load).
- **Clip duplicate** — `/live/clip_slot/duplicate_clip_to`.

Genuinely **missing** (needs a new AbletonOSC handler):
- **Browser** (instrument / effect / drum-kit loading). No `browser` address
  exists in AbletonOSC today.
- **Session → Arrangement commit** (no direct address; needs handler or macro).

## Prior art
`6uclz1/ableton-cli` (a separate, non-OSC CLI using its own TCP/JSONL Remote
Script) already implements browser loading, typed effects, and audio analysis.
We are **not** adopting its stack, but we port its proven LOM browser recipe:

```python
browser = app.browser                      # Live.Application.get_application().browser
# categories: browser.instruments / .drums / .sounds / .audio_effects / .midi_effects
# walk node.children recursively; each item has .name, .uri, .is_loadable, .is_folder
song.view.selected_track = target_track    # load targets the SELECTED track
browser.load_item(item)                    # the actual load (resolve item by .uri)
```
Gotchas inherited: load targets the **selected** track (select first); address
items by **uri** (stable), not index; loading is **async** (confirm by polling
device count, don't assume synchronous success).

---

## Tier 1 — Core gaps (mixing + instrument loading)

Highest-value tier. Three sub-parts.

### 1a. Device parameter control — *CLI-only*
AbletonOSC's `device.py` already exposes get/set parameters; we surface it.
- **`live.py`**: `get_num_devices`, `get_device_params(track, dev)` →
  `[{index, name, value, min, max}]`, `set_device_param(track, dev, idx, value)`,
  `set_device_param_by_name(...)`.
- **`cli.py`**: `device list <track>`, `device params <track> <dev>`,
  `device set <track> <dev> <param> <value>` (param accepts index or name).
- **Effort:** Low (~half day). **Risk:** Low. Verifiable immediately against a
  running set.

### 1b. Track sends + return tracks — *CLI-only*
- **`live.py`**: `create_return_track`, `delete_return_track`,
  `get_send(track, send_idx)`, `set_send(track, send_idx, value)`.
- **`cli.py`**: `return create|delete`, `track send <track> <send_idx> [value]`.
- **Effort:** Low. **Risk:** Low (document send-index ordering).

### 1c. Browser + instrument/effect/drum loading — *NEW handler + CLI*
The one piece needing a Live-side handler. Port the LOM recipe above.
- **New `browser.py` handler** in the AbletonOSC install:
  - `/live/browser/get/categories` → instruments, drums, sounds, audio_effects,
    midi_effects
  - `/live/browser/get/items` (path) → walk `node.children`, return
    `{name, uri, is_loadable, is_folder}`
  - `/live/browser/load` (uri) → select target track via existing
    `/live/view/set/selected_track`, then `browser.load_item(item)`
- **`live.py` / `cli.py`**: `browser categories`, `browser list [path]`,
  `browser search <term>`, `browser load <track> <uri>`, `browser load-drum-kit`.
- **Design decisions:** address by **uri** not index; select track first; loading
  is **async** → confirm by polling `/live/track/get/num_devices`.
- **Effort:** Medium (1–2 days incl. testing on Live 12). **Risk:** Medium —
  browser folder structure varies by install; async confirmation needs care.
- **De-risk first:** throwaway spike that enumerates + loads ONE instrument
  before building the full CLI surface.

**Tier 1 outcome:** the lofi track becomes self-contained — load a Rhodes, a
drum kit, a sub bass, add a reverb return, all from the CLI.

---

## Tier 2 — Typed effect & synth helpers
Ergonomic layer **on top of 1a**. Pure CLI; no Live-side work.
- **`device_specs.py`** registry: friendly param names → param indices/names for
  common devices (EQ Eight, Compressor, Reverb, Auto Filter, Limiter, Utility)
  and synths (Operator, Wavetable, Drift).
- **`cli.py`**: e.g. `fx eq8 <track> <dev> --low-gain -3 --high-freq 8000`,
  `fx reverb <track> <dev> --decay 2.5`.
- **Lookup strategy:** resolve by **parameter name** at runtime (read the device's
  actual params via 1a) rather than hard-coding indices — robust across Live
  versions. The spec only provides friendly aliases + safe ranges.
- **Effort:** Medium, incremental (add devices one at a time). **Risk:** Low.
  **Depends on:** Tier 1a.

---

## Tier 3 — Audio analysis & mastering
Heaviest tier. **FFmpeg-dependent**, mostly **offline** (operates on rendered
audio, not live OSC).
- **Loudness (LUFS)** + **spectrum** analysis via FFmpeg on exported audio.
- **Transient detection** → **audio-to-drum-rack slicing** (this part needs OSC:
  create drum rack via 1c, then place sliced samples — non-trivial).
- **Remix/master workflow:** target → analyze → plan → apply → QA.
- **New dependency:** FFmpeg (document install). Lives in a separate `audio/`
  module so the OSC core stays dependency-light.
- **Effort:** High (multi-day; each sub-feature standalone). **Risk:** Med–High;
  slicing touches the trickiest LOM areas.
- **Recommendation:** build **only if needed**; consider lifting `6uclz1`'s
  implementation rather than rewriting. Lowest priority.

---

## Tier 4 — Arrangement & workflow
Quality-of-life. Mostly existing addresses.
- **Clip duplicate** — `/live/clip_slot/duplicate_clip_to` exists → CLI
  `clip duplicate <track> <from> <to>`. Low effort.
- **Session → Arrangement commit** — record session clips to the timeline. No
  direct address; needs a new handler (LOM arrangement record /
  `capture_and_insert_scene`) or a transport-record macro. Medium effort; needs
  investigation.
- **Batch / streaming execution** — run many commands from a file/stdin over one
  socket (faster than re-spawning the CLI per command); useful for generative
  composition. Pure client-side. Low–medium effort.
- **`doctor` diagnostic** — one command checking connection, AbletonOSC version,
  control-surface enabled, and ports. Low effort, high friction-reduction. Good
  early quick win.

---

## Sequencing & dependencies

```
Tier 1a (device params) ──┬─► Tier 2 (typed fx helpers)
Tier 1b (sends/returns)   │
Tier 1c (browser) ────────┴─► Tier 3 (slicing needs browser)
Tier 4 (doctor, clip-dup, batch — independent, do anytime)
```

| Order | Item | Effort | New Live-side handler? |
|-------|------|--------|------------------------|
| 1 | Tier 4 `doctor` + Tier 1a device params | Low | No |
| 2 | Tier 1b sends/returns | Low | No |
| 3 | Tier 1c browser (spike first) | Medium | **Yes** |
| 4 | Tier 2 typed fx | Medium | No |
| 5 | Tier 4 clip-dup + batch | Low–Med | Mostly no |
| 6 | Tier 3 audio/mastering | High | Partly |

**Recommended start:** steps 1–2 (all CLI-only, verifiable against a running set
today — fast wins), then de-risk Tier 1c with a small browser spike before
committing to its full CLI surface. Defer Tier 3 until there's a concrete need.
