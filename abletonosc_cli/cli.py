"""Command-line interface for AbletonOSC.

Designed to be both human- and agent-friendly: every command prints a result
(JSON with --json), and queries return structured data. Run with no Ableton
running and you'll get a clear connection-error message.

Examples:
    abletonosc status
    abletonosc tempo set 128
    abletonosc track create-midi --name Bass
    abletonosc clip create 0 0 --length 4
    abletonosc clip add-notes 0 0 --notes "C3:0:1,E3:1:1,G3:2:1"
    abletonosc transport play
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, List

from .device_specs import DEVICE_SPECS, FX_COMMANDS, resolve_alias
from .live import Live
from .notes import midi_to_note
from .osc_client import AbletonOSCError, OSCClient


def _parse_notes(spec: str) -> List[tuple]:
    """Parse a note spec string into note tuples.

    Format: comma-separated notes, each "pitch:start:duration[:velocity]".
    e.g. "C3:0:1,E3:1:0.5:80" -> [(C3, 0, 1, 100), (E3, 1, 0.5, 80)]
    """
    notes = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) < 3:
            raise ValueError(
                f"Bad note {chunk!r}: expected pitch:start:duration[:velocity]"
            )
        pitch = parts[0]
        start = float(parts[1])
        duration = float(parts[2])
        velocity = int(parts[3]) if len(parts) > 3 else 100
        notes.append((pitch, start, duration, velocity))
    return notes


def _emit(result: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result))
    elif isinstance(result, (dict, list)):
        print(json.dumps(result, indent=2))
    elif result is not None:
        print(result)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="abletonosc", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--send-port", type=int, default=11000)
    p.add_argument("--recv-port", type=int, default=11001)
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--json", action="store_true", help="Emit compact JSON")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show connection + transport status")
    sub.add_parser("version", help="Show Live version")
    sub.add_parser("doctor", help="Diagnose connection, version, and ports")

    # transport
    t = sub.add_parser("transport", help="Playback control")
    t.add_argument("action", choices=["play", "stop", "continue", "stop-all-clips"])

    # tempo
    tp = sub.add_parser("tempo", help="Get/set tempo")
    tp_sub = tp.add_subparsers(dest="tempo_cmd", required=True)
    tp_sub.add_parser("get")
    tp_set = tp_sub.add_parser("set")
    tp_set.add_argument("bpm", type=float)

    # song
    sg = sub.add_parser("song", help="Song-level info")
    sg_sub = sg.add_subparsers(dest="song_cmd", required=True)
    sg_sub.add_parser("tracks", help="List track names")
    sg_sub.add_parser("info", help="Track + scene counts")
    sg_sub.add_parser("undo")
    sg_sub.add_parser("redo")
    sg_scene = sg_sub.add_parser("create-scene")
    sg_scene.add_argument("--index", type=int, default=-1)

    # track
    tr = sub.add_parser("track", help="Track operations")
    tr_sub = tr.add_subparsers(dest="track_cmd", required=True)
    tr_cm = tr_sub.add_parser("create-midi")
    tr_cm.add_argument("--index", type=int, default=-1)
    tr_cm.add_argument("--name")
    tr_ca = tr_sub.add_parser("create-audio")
    tr_ca.add_argument("--index", type=int, default=-1)
    tr_ca.add_argument("--name")
    tr_del = tr_sub.add_parser("delete")
    tr_del.add_argument("index", type=int)
    tr_name = tr_sub.add_parser("name")
    tr_name.add_argument("track", type=int)
    tr_name.add_argument("value", nargs="?", help="If given, set the name")
    for cmd, _help in [("mute", "mute"), ("solo", "solo"), ("arm", "arm")]:
        tc = tr_sub.add_parser(cmd)
        tc.add_argument("track", type=int)
        tc.add_argument("state", choices=["on", "off"])
    tr_vol = tr_sub.add_parser("volume")
    tr_vol.add_argument("track", type=int)
    tr_vol.add_argument("value", type=float, nargs="?", help="0.0-1.0; omit to get")
    tr_pan = tr_sub.add_parser("pan")
    tr_pan.add_argument("track", type=int)
    tr_pan.add_argument("value", type=float, help="-1.0 to 1.0")
    tr_dev = tr_sub.add_parser("devices")
    tr_dev.add_argument("track", type=int)
    tr_send = tr_sub.add_parser("send", help="Get/set a track send level")
    tr_send.add_argument("track", type=int)
    tr_send.add_argument("send", type=int, help="Send index (0 = return A, ...)")
    tr_send.add_argument("value", type=float, nargs="?", help="0.0-1.0; omit to get")

    # clip
    cl = sub.add_parser("clip", help="Clip operations")
    cl_sub = cl.add_subparsers(dest="clip_cmd", required=True)
    cl_cr = cl_sub.add_parser("create")
    cl_cr.add_argument("track", type=int)
    cl_cr.add_argument("clip", type=int)
    cl_cr.add_argument("--length", type=float, default=4.0)
    cl_del = cl_sub.add_parser("delete")
    cl_del.add_argument("track", type=int)
    cl_del.add_argument("clip", type=int)
    for cmd in ["fire", "stop"]:
        cf = cl_sub.add_parser(cmd)
        cf.add_argument("track", type=int)
        cf.add_argument("clip", type=int)
    cl_an = cl_sub.add_parser("add-notes")
    cl_an.add_argument("track", type=int)
    cl_an.add_argument("clip", type=int)
    cl_an.add_argument("--notes", required=True,
                       help='"C3:0:1,E3:1:0.5:80" = pitch:start:dur[:vel]')
    cl_gn = cl_sub.add_parser("get-notes")
    cl_gn.add_argument("track", type=int)
    cl_gn.add_argument("clip", type=int)
    cl_rn = cl_sub.add_parser("clear-notes")
    cl_rn.add_argument("track", type=int)
    cl_rn.add_argument("clip", type=int)
    cl_nm = cl_sub.add_parser("name")
    cl_nm.add_argument("track", type=int)
    cl_nm.add_argument("clip", type=int)
    cl_nm.add_argument("value")
    cl_lp = cl_sub.add_parser("loop")
    cl_lp.add_argument("track", type=int)
    cl_lp.add_argument("clip", type=int)
    cl_lp.add_argument("start", type=float)
    cl_lp.add_argument("end", type=float)
    cl_dup = cl_sub.add_parser("duplicate", help="Duplicate a clip to another slot")
    cl_dup.add_argument("track", type=int)
    cl_dup.add_argument("clip", type=int)
    cl_dup.add_argument("to_track", type=int, help="Destination track")
    cl_dup.add_argument("to_clip", type=int, help="Destination clip slot")

    # scene
    sc = sub.add_parser("scene", help="Scene operations")
    sc_sub = sc.add_subparsers(dest="scene_cmd", required=True)
    sc_fire = sc_sub.add_parser("fire")
    sc_fire.add_argument("index", type=int)

    # device parameters
    dv = sub.add_parser("device", help="Device parameter control")
    dv_sub = dv.add_subparsers(dest="device_cmd", required=True)
    dv_list = dv_sub.add_parser("list", help="List devices on a track")
    dv_list.add_argument("track", type=int)
    dv_par = dv_sub.add_parser("params", help="List a device's parameters")
    dv_par.add_argument("track", type=int)
    dv_par.add_argument("device", type=int)
    dv_set = dv_sub.add_parser("set", help="Set a device parameter (by index or name)")
    dv_set.add_argument("track", type=int)
    dv_set.add_argument("device", type=int)
    dv_set.add_argument("param", help="Parameter index or name")
    dv_set.add_argument("value", type=float)

    # browser (instrument / effect / preset loading)
    br = sub.add_parser("browser", help="Browse and load instruments/effects/presets")
    br_sub = br.add_subparsers(dest="browser_cmd", required=True)
    br_sub.add_parser("categories", help="List top-level browser categories")
    br_ls = br_sub.add_parser("list", help="List items under a path")
    br_ls.add_argument("path", nargs="?", default="",
                       help='e.g. "instruments" or "instruments/Operator"')
    br_se = br_sub.add_parser("search", help="Search loadable items by name")
    br_se.add_argument("term")
    br_se.add_argument("--category", default="",
                       help="Restrict to one category (e.g. instruments)")
    br_se.add_argument("--max", type=int, default=50, dest="max_results")
    br_ld = br_sub.add_parser("load", help="Load an item by uri onto a track")
    br_ld.add_argument("track", type=int)
    br_ld.add_argument("uri")
    br_ld.add_argument("--no-wait", action="store_true",
                       help="Don't poll for the device to appear")

    # typed fx helpers (Tier 2): friendly aliases over device parameters
    fx = sub.add_parser("fx", help="Typed effect helpers (friendly param names)")
    fx_sub = fx.add_subparsers(dest="fx_cmd", required=True)
    for fx_name, class_names in FX_COMMANDS.items():
        fp = fx_sub.add_parser(fx_name, help="Set %s parameters by name" % fx_name)
        fp.add_argument("track", type=int)
        fp.add_argument("device", type=int, help="Device index on the track")
        # One optional --flag per alias for this device's class(es).
        seen = set()
        for class_name in class_names:
            for alias, spec in DEVICE_SPECS.get(class_name, {}).items():
                if alias in seen:
                    continue
                seen.add(alias)
                rng = spec.get("range") if isinstance(spec, dict) else None
                help_txt = ("range %s" % (rng,)) if rng else None
                fp.add_argument("--%s" % alias, type=float, default=None,
                                help=help_txt)

    # return tracks
    rt = sub.add_parser("return", help="Return-track operations")
    rt_sub = rt.add_subparsers(dest="return_cmd", required=True)
    rt_sub.add_parser("create", help="Create a return track")
    rt_del = rt_sub.add_parser("delete", help="Delete a return track")
    rt_del.add_argument("index", type=int, help="Return-track index (0-based)")

    # batch / streaming execution
    bt = sub.add_parser("batch", help="Run many commands over one socket")
    bt.add_argument("file", nargs="?",
                    help="File of commands (one per line); omit to read stdin")
    bt.add_argument("--stop-on-error", action="store_true",
                    help="Abort on the first command that errors")

    # audio capture + Gemini critique (the self-critique loop)
    au = sub.add_parser("audio", help="Capture Live's output and critique it via Gemini")
    au_sub = au.add_subparsers(dest="audio_cmd", required=True)
    au_sub.add_parser("devices", help="List input devices (flags loopback ones)")
    au_cap = au_sub.add_parser("capture", help="Record N seconds from the loopback device")
    au_cap.add_argument("--seconds", type=float, required=True)
    au_cap.add_argument("--out", required=True, help="Output WAV path")
    au_cap.add_argument("--device", help="Force a capture device by name substring")
    au_cc = au_sub.add_parser("capture-clip",
                              help="Fire a clip and record exactly its length")
    au_cc.add_argument("track", type=int)
    au_cc.add_argument("clip", type=int)
    au_cc.add_argument("--out", required=True, help="Output WAV path")
    au_cc.add_argument("--device", help="Force a capture device by name substring")
    au_cc.add_argument("--tail", type=float, default=0.4,
                       help="Extra seconds recorded after the clip ends")
    au_cm = au_sub.add_parser("capture-master",
                              help="Play and record N bars of the master output")
    au_cm.add_argument("--bars", type=float, required=True)
    au_cm.add_argument("--out", required=True, help="Output WAV path")
    au_cm.add_argument("--device", help="Force a capture device by name substring")
    au_cm.add_argument("--beats-per-bar", type=float, default=4.0, dest="beats_per_bar")
    au_cm.add_argument("--tail", type=float, default=0.4)

    def _add_gemini_flags(sp):
        sp.add_argument("--ask", help="Ask a specific question instead of a general critique")
        sp.add_argument("--model", default=None,
                        help="Gemini model (default gemini-3.5-flash; "
                             "use gemini-3.1-flash-lite for cheap qualitative checks)")
        sp.add_argument("--api-key", default=None, dest="api_key")

    au_cr = au_sub.add_parser("critique", help="Send an existing audio file to Gemini")
    au_cr.add_argument("file", help="Audio file (WAV/MP3/FLAC, <20 MB)")
    _add_gemini_flags(au_cr)
    au_rc = au_sub.add_parser("review-clip",
                              help="capture-clip then critique, in one step")
    au_rc.add_argument("track", type=int)
    au_rc.add_argument("clip", type=int)
    au_rc.add_argument("--out", default=None,
                       help="WAV path (default: a temp file)")
    au_rc.add_argument("--device", help="Force a capture device by name substring")
    au_rc.add_argument("--tail", type=float, default=0.4)
    _add_gemini_flags(au_rc)

    # raw escape hatch
    rw = sub.add_parser("raw", help="Send a raw OSC message")
    rw.add_argument("address")
    rw.add_argument("args", nargs="*", help="Args (auto-typed: int/float/str)")
    rw.add_argument("--query", action="store_true", help="Wait for a reply")

    return p


def _coerce(token: str) -> Any:
    for cast in (int, float):
        try:
            return cast(token)
        except ValueError:
            continue
    return token


def _doctor(live: Live) -> dict:
    """One-shot diagnostic: connection, version, ports, control surface."""
    checks = []
    connected = live.test_connection()
    checks.append({
        "check": "control_surface",
        "ok": connected,
        "detail": ("AbletonOSC responding on UDP %d/%d"
                   % (live.c.send_port, live.c.recv_port)) if connected else
                  ("No reply on UDP %d. Is Ableton running with the AbletonOSC "
                   "control surface enabled?" % live.c.send_port),
    })
    version = None
    if connected:
        try:
            version = live.version()
            checks.append({"check": "live_version", "ok": True, "detail": version})
        except AbletonOSCError as e:
            checks.append({"check": "live_version", "ok": False, "detail": str(e)})
    checks.append({
        "check": "ports",
        "ok": True,
        "detail": "send=%d recv=%d host=%s"
                  % (live.c.send_port, live.c.recv_port, live.c.host),
    })

    # Audio self-critique loop: loopback capture device + Gemini key (advisory;
    # absence doesn't fail the OSC connection, just the audio feature).
    try:
        from . import audio as audio_mod
        loop_dev = audio_mod.find_loopback_device()
        checks.append({"check": "audio_loopback", "ok": True,
                       "detail": "capture via %r" % loop_dev["name"]})
    except Exception as e:
        checks.append({"check": "audio_loopback", "ok": False,
                       "detail": str(e), "advisory": True})
    from . import gemini as gemini_mod
    has_key = bool(os.environ.get("GEMINI_API_KEY")
                   or gemini_mod._load_dotenv_key())
    checks.append({"check": "gemini_key", "ok": has_key, "advisory": True,
                   "detail": "GEMINI_API_KEY set" if has_key else
                             "GEMINI_API_KEY not set (audio critique unavailable)"})

    return {
        # Advisory checks (audio loopback / Gemini key) don't fail core health.
        "ok": all(c["ok"] for c in checks if not c.get("advisory")),
        "connected": connected,
        "version": version,
        "checks": checks,
    }


def _dispatch_fx(args: argparse.Namespace, live: Live) -> dict:
    """Apply friendly-aliased parameters to a device, resolving names at runtime."""
    fx_name = args.fx_cmd
    class_names = FX_COMMANDS[fx_name]

    actual_class = live.get_device_class_name(args.track, args.device)
    if actual_class not in class_names:
        return {
            "ok": False,
            "error": "device %d on track %d is %r, not a %s (expected %s)"
                     % (args.device, args.track, actual_class, fx_name,
                        "/".join(class_names)),
        }

    # Collect the alias flags the user actually supplied (non-None floats).
    aliases = {}
    for class_name in class_names:
        aliases.update(DEVICE_SPECS.get(class_name, {}))

    applied = []
    for alias in aliases:
        attr = alias.replace("-", "_")
        value = getattr(args, attr, None)
        if value is None:
            continue
        spec = resolve_alias(actual_class, alias)
        param_name = spec["param"]
        rng = spec.get("range")
        if rng is not None and not (rng[0] <= value <= rng[1]):
            return {"ok": False,
                    "error": "%s=%s out of range %s for %s"
                             % (alias, value, rng, param_name)}
        index = live.set_device_param_by_name(args.track, args.device, param_name, value)
        applied.append({"alias": alias, "param": param_name,
                        "index": index, "value": value})

    if not applied:
        return {"ok": False, "error": "no parameters given; pass at least one --flag"}
    return {"ok": True, "track": args.track, "device": args.device,
            "fx": fx_name, "applied": applied}


def _dispatch_audio(args: argparse.Namespace, live: Live) -> dict:
    """Capture Live's output and/or critique it via Gemini.

    Imported lazily so the heavy audio/HTTP deps aren't needed for other commands.
    Audio/Gemini errors are raised as AbletonOSCError so main() maps them to the
    transport exit code (2) and the {"error": ...} JSON shape.
    """
    from . import audio as audio_mod
    from . import gemini as gemini_mod

    def _gem(path):
        try:
            return gemini_mod.critique_audio(
                path, ask=args.ask, api_key=args.api_key,
                model=args.model or gemini_mod.DEFAULT_MODEL)
        except gemini_mod.GeminiError as e:
            raise AbletonOSCError(str(e))

    try:
        ac = args.audio_cmd
        if ac == "devices":
            return {"devices": audio_mod.list_input_devices()}
        if ac == "capture":
            return audio_mod.record(args.seconds, args.out, device=args.device)
        if ac == "capture-clip":
            return audio_mod.capture_clip(live, args.track, args.clip, args.out,
                                          device=args.device, tail=args.tail)
        if ac == "capture-master":
            return audio_mod.capture_master(
                live, args.bars, args.out, device=args.device,
                beats_per_bar=args.beats_per_bar, tail=args.tail)
        if ac == "critique":
            return _gem(args.file)
        if ac == "review-clip":
            out = args.out
            if out is None:
                import tempfile
                fd, out = tempfile.mkstemp(prefix="abletest_clip_", suffix=".wav")
                os.close(fd)
            cap = audio_mod.capture_clip(live, args.track, args.clip, out,
                                         device=args.device, tail=args.tail)
            result = _gem(out)
            result["capture"] = cap
            return result
    except audio_mod.AudioError as e:
        raise AbletonOSCError(str(e))
    raise SystemExit("Unhandled audio command")


def _run_batch(args: argparse.Namespace, live: Live) -> dict:
    """Run many CLI commands over a single open socket.

    Reads one command line per input line (shell-style tokens); blank lines and
    lines starting with '#' are skipped. Reuses the already-connected ``live``
    so we don't re-spawn a socket per command.
    """
    import shlex

    if args.file:
        with open(args.file, "r") as fd:
            lines = fd.readlines()
    else:
        lines = sys.stdin.readlines()

    results = []
    parser = build_parser()
    ok = True
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            sub_args = parser.parse_args(shlex.split(line))
            if sub_args.command == "batch":
                raise ValueError("nested batch is not allowed")
            result = dispatch(sub_args, live)
            results.append({"line": lineno, "command": line, "result": result})
        except (AbletonOSCError, ValueError, SystemExit) as e:
            ok = False
            results.append({"line": lineno, "command": line, "error": str(e)})
            if args.stop_on_error:
                break
    return {"ok": ok, "count": len(results), "results": results}


def dispatch(args: argparse.Namespace, live: Live) -> Any:
    cmd = args.command

    if cmd == "status":
        connected = live.test_connection()
        result = {"connected": connected}
        if connected:
            result.update(
                tempo=live.get_tempo(),
                is_playing=live.is_playing(),
                num_tracks=live.num_tracks(),
                num_scenes=live.num_scenes(),
            )
        return result

    if cmd == "version":
        return {"version": live.version()}

    if cmd == "doctor":
        return _doctor(live)

    if cmd == "transport":
        {"play": live.play, "stop": live.stop,
         "continue": live.continue_playing,
         "stop-all-clips": live.stop_all_clips}[args.action]()
        return {"ok": True, "action": args.action}

    if cmd == "tempo":
        if args.tempo_cmd == "get":
            return {"tempo": live.get_tempo()}
        live.set_tempo(args.bpm)
        return {"ok": True, "tempo": args.bpm}

    if cmd == "song":
        if args.song_cmd == "tracks":
            return {"tracks": live.track_names()}
        if args.song_cmd == "info":
            return {"num_tracks": live.num_tracks(), "num_scenes": live.num_scenes()}
        if args.song_cmd == "undo":
            live.undo(); return {"ok": True}
        if args.song_cmd == "redo":
            live.redo(); return {"ok": True}
        if args.song_cmd == "create-scene":
            live.create_scene(args.index); return {"ok": True}

    if cmd == "track":
        tc = args.track_cmd
        if tc == "create-midi":
            live.create_midi_track(args.index)
            if args.name:
                idx = live.num_tracks() - 1 if args.index < 0 else args.index
                live.set_track_name(idx, args.name)
            return {"ok": True, "name": args.name}
        if tc == "create-audio":
            live.create_audio_track(args.index)
            if args.name:
                idx = live.num_tracks() - 1 if args.index < 0 else args.index
                live.set_track_name(idx, args.name)
            return {"ok": True, "name": args.name}
        if tc == "delete":
            live.delete_track(args.index); return {"ok": True}
        if tc == "name":
            if args.value is None:
                return {"track": args.track, "name": live.get_track_name(args.track)}
            live.set_track_name(args.track, args.value)
            return {"ok": True, "track": args.track, "name": args.value}
        if tc in ("mute", "solo", "arm"):
            on = args.state == "on"
            {"mute": live.set_track_mute, "solo": live.set_track_solo,
             "arm": live.set_track_arm}[tc](args.track, on)
            return {"ok": True, "track": args.track, tc: on}
        if tc == "volume":
            if args.value is None:
                return {"track": args.track, "volume": live.get_track_volume(args.track)}
            live.set_track_volume(args.track, args.value)
            return {"ok": True, "track": args.track, "volume": args.value}
        if tc == "pan":
            live.set_track_panning(args.track, args.value)
            return {"ok": True, "track": args.track, "pan": args.value}
        if tc == "devices":
            return {"track": args.track, "devices": live.get_track_devices(args.track)}
        if tc == "send":
            if args.value is None:
                return {"track": args.track, "send": args.send,
                        "value": live.get_send(args.track, args.send)}
            live.set_send(args.track, args.send, args.value)
            return {"ok": True, "track": args.track, "send": args.send,
                    "value": args.value}

    if cmd == "clip":
        cc = args.clip_cmd
        if cc == "create":
            live.create_clip(args.track, args.clip, args.length)
            return {"ok": True, "track": args.track, "clip": args.clip,
                    "length": args.length}
        if cc == "delete":
            live.delete_clip(args.track, args.clip); return {"ok": True}
        if cc in ("fire", "stop"):
            (live.fire_clip if cc == "fire" else live.stop_clip)(args.track, args.clip)
            return {"ok": True, "action": cc}
        if cc == "add-notes":
            notes = _parse_notes(args.notes)
            live.add_notes(args.track, args.clip, notes)
            return {"ok": True, "added": len(notes)}
        if cc == "get-notes":
            raw = live.get_notes(args.track, args.clip)
            notes = [
                {"pitch": midi_to_note(int(n[0])), "midi": int(n[0]),
                 "start": n[1], "duration": n[2], "velocity": n[3],
                 "mute": bool(n[4])}
                for n in raw
            ]
            return {"track": args.track, "clip": args.clip, "notes": notes}
        if cc == "clear-notes":
            live.remove_notes(args.track, args.clip); return {"ok": True}
        if cc == "name":
            live.set_clip_name(args.track, args.clip, args.value)
            return {"ok": True, "name": args.value}
        if cc == "loop":
            live.set_clip_loop(args.track, args.clip, args.start, args.end)
            return {"ok": True, "start": args.start, "end": args.end}
        if cc == "duplicate":
            live.duplicate_clip_to(args.track, args.clip, args.to_track, args.to_clip)
            return {"ok": True, "from": [args.track, args.clip],
                    "to": [args.to_track, args.to_clip]}

    if cmd == "device":
        dc = args.device_cmd
        if dc == "list":
            return {"track": args.track, "devices": live.get_track_devices(args.track)}
        if dc == "params":
            return {"track": args.track, "device": args.device,
                    "parameters": live.get_device_params(args.track, args.device)}
        if dc == "set":
            idx = live.set_device_param_by_name(
                args.track, args.device, args.param, args.value)
            return {"ok": True, "track": args.track, "device": args.device,
                    "param": args.param, "index": idx, "value": args.value}

    if cmd == "fx":
        return _dispatch_fx(args, live)

    if cmd == "browser":
        bc = args.browser_cmd
        if bc == "categories":
            return {"categories": live.browser_categories()}
        if bc == "list":
            return {"path": args.path, "items": live.browser_items(args.path)}
        if bc == "search":
            results = live.browser_search(args.term, args.category, args.max_results)
            return {"term": args.term, "count": len(results), "results": results}
        if bc == "load":
            before = live.get_num_devices(args.track)
            found = live.browser_load(args.uri, args.track)
            if not found:
                return {"ok": False, "error": "uri not found or not loadable",
                        "uri": args.uri}
            loaded = True
            if not args.no_wait:
                # Loading is async; poll for the device count to increase.
                loaded = False
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    if live.get_num_devices(args.track) > before:
                        loaded = True
                        break
                    time.sleep(0.1)
            return {"ok": loaded, "track": args.track, "uri": args.uri,
                    "devices_before": before,
                    "devices_after": live.get_num_devices(args.track),
                    "confirmed": loaded}

    if cmd == "return":
        if args.return_cmd == "create":
            live.create_return_track(); return {"ok": True}
        if args.return_cmd == "delete":
            live.delete_return_track(args.index); return {"ok": True}

    if cmd == "audio":
        return _dispatch_audio(args, live)

    if cmd == "batch":
        return _run_batch(args, live)

    if cmd == "scene":
        if args.scene_cmd == "fire":
            live.fire_scene(args.index); return {"ok": True}

    if cmd == "raw":
        coerced = [_coerce(a) for a in args.args]
        if args.query:
            reply = live.c.query(args.address, *coerced)
            return {"address": args.address, "reply": list(reply)}
        live.c.send(args.address, *coerced)
        return {"ok": True, "sent": args.address, "args": coerced}

    raise SystemExit(f"Unhandled command: {cmd}")


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    client = OSCClient(host=args.host, send_port=args.send_port,
                       recv_port=args.recv_port, timeout=args.timeout)
    live = Live(client)
    try:
        result = dispatch(args, live)
        _emit(result, args.json)
        return 0
    except AbletonOSCError as e:
        _emit({"error": str(e)}, args.json) if args.json else print(
            f"error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
