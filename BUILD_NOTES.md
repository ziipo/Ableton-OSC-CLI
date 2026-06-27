# Build Notes — what we built & how it fits together

Implementation record for the work in `build_plan.md`. Covers what shipped, the
key design decisions, and the gotchas worth remembering. For *operating* the
tools, see `AGENT_GUIDE.md`; for the quick command list, see `CLAUDE.md`.

## What shipped

Implemented build_plan tiers **1, 2, and 4**. Tier 3 (audio analysis/mastering,
FFmpeg-dependent) was **deliberately deferred** per the plan ("build only if
needed").

| Tier / item | What | Where | Live-side change? |
|---|---|---|---|
| 4 — `doctor` | Connection/version/port diagnostic | `cli.py:_doctor` | No |
| 1a — device params | `device list/params/set` (by index or name) | `live.py`, `cli.py` | No |
| 1b — sends/returns | `return create/delete`, `track send` | `live.py`, `cli.py` | No |
| 1c — browser | `browser categories/list/search/load` | **`abletonosc/browser.py`** + CLI | **Yes** |
| 2 — typed fx | `fx eq8/compressor/reverb/...` | `device_specs.py`, `cli.py` | No |
| 4 — clip dup | `clip duplicate` | `live.py`, `cli.py` | No |
| 4 — batch | `batch` (many cmds, one socket) | `cli.py:_run_batch` | No |

All commands keep the existing contract: `--json` (before the subcommand),
`{ok: true, ...}` / `{error: ...}` bodies, exit codes 0/1/2.

## Architecture (unchanged core)

```
abletonosc_cli/
  osc_client.py   synchronous OSC transport (send 11000 / recv 11001, per-address reply queues)
  live.py         typed high-level API over AbletonOSC addresses
  notes.py        note-name <-> MIDI (C3 = 60)
  device_specs.py NEW: friendly param aliases per device class_name (Tier 2)
  cli.py          argparse CLI + JSON output + dispatch
```

The custom Live-side handler lives in the AbletonOSC install:
`~/Music/Ableton/User Library/Remote Scripts/AbletonOSC/abletonosc/browser.py`,
registered in that package's `__init__.py` and in `manager.py`'s handler list
(and in `reload_imports`).

## Key design decisions

- **Resolve device parameters by NAME at runtime, never by hard-coded index.**
  Indices drift between Live versions; names are stable. `device set` accepts an
  index *or* a name (exact match preferred, then unique substring; ambiguous
  names error). `device_specs.py` only maps friendly aliases → real names +
  documented ranges — it never stores indices.

- **Browser items addressed by `uri`.** Stable across the session; indices are
  not. `browser load` resolves the uri by walking the tree depth-first.

- **Browser load is async; confirm by polling.** Live returns from `load_item`
  before the device exists. `browser load` records `num_devices` before, fires
  the load, then polls until the count increases (or ~5s timeout), reporting
  `confirmed`. `--no-wait` skips the poll.

- **`fx` is guarded by `class_name`.** It refuses to apply (e.g.) reverb params
  to an EQ Eight, so a wrong device index fails loudly instead of corrupting a
  device.

- **`batch` reuses one open socket** and re-enters the same `dispatch()` per
  line, so generative runs don't pay per-command socket setup. Nested batch is
  rejected.

## The browser-handler reload gotcha (important)

Adding `browser.py` as a **new** handler module cannot be picked up by
AbletonOSC's in-place `/live/api/reload`. Why: `manager.reload_imports()` calls
`importlib.reload(abletonosc.browser)`, but on the first reload that attribute
doesn't exist yet (the *old* `__init__.py` loaded at Live startup never imported
it), so the reload raises `AttributeError`, is swallowed by the surrounding
try/except, and aborts before `importlib.reload(abletonosc)` re-runs `__init__`.

**Consequence:** after adding/replacing a handler module, you must **fully
restart Ableton Live**. Editing an *existing* handler's internals is fine to hot-
reload; adding a new module is not. Symptom of forgetting:
`{"error": "AbletonOSC error: ('Unknown OSC address: /live/browser/...',)"}`.

## How it was verified

Each tier was tested against a live Ableton 12.4 set:
- device set→read-back on a real instrument; range-rejection confirmed.
- return created, send set to 0.4 and read back.
- browser spike: loaded Operator (195 params), an 808 Core Kit drum rack, and a
  Reverb onto an occupied track; async `confirmed: true` each time.
- typed fx: `low-gain` → real param `1 Gain A`; values landed in Live; range
  guard and class-name guard both fired correctly.
- clip duplicate and batch (stdin) confirmed.

All scratch tracks/returns created during testing were deleted; the set was left
as found.

## Stock vs. custom AbletonOSC

`browser.py` (and its registration) is the **only** change to the AbletonOSC
install — everything else uses stock addresses. If AbletonOSC is ever
reinstalled/updated, re-add `browser.py` and its three registrations
(`__init__.py` import, `manager.py` handler list, `manager.py` `reload_imports`).
The CLI degrades gracefully without it: only the `browser` commands fail (with
`Unknown OSC address`); all other commands keep working.
```
