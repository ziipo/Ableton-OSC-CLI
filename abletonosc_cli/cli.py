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
import sys
from typing import Any, List

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

    # scene
    sc = sub.add_parser("scene", help="Scene operations")
    sc_sub = sc.add_subparsers(dest="scene_cmd", required=True)
    sc_fire = sc_sub.add_parser("fire")
    sc_fire.add_argument("index", type=int)

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
