"""Audio capture from Live via a loopback device (BlackHole, Loopback, etc.).

AbletonOSC cannot render audio. To let an agent *hear* its own work we capture
Live's output in realtime through a virtual audio device:

    Live master out  ->  Multi-Output Device (speakers + BlackHole)  ->  here

The agent routes Live's output to a Multi-Output Device that includes a loopback
device (so you still hear it on your speakers), then this module records the
loopback's input for a computed window while a clip/section plays.

One-time setup is documented in AGENT_GUIDE.md. This module only *finds* the
loopback input device and records from it; it never changes system audio config.
"""

from __future__ import annotations

import time
from typing import List, Optional, Tuple

# These are heavy/optional; import lazily so `abletonosc` still runs without them
# for non-audio commands (and gives a clean error if they're missing).
try:
    import numpy as np
    import sounddevice as sd
    import soundfile as sf
    _IMPORT_ERROR: Optional[Exception] = None
except Exception as e:  # pragma: no cover - environment dependent
    np = sd = sf = None  # type: ignore
    _IMPORT_ERROR = e

# Substrings (lowercased) we treat as loopback/virtual capture devices.
LOOPBACK_HINTS = ("blackhole", "loopback", "soundflower", "vb-cable", "vb-audio")

DEFAULT_SAMPLERATE = 48000
DEFAULT_CHANNELS = 2


class AudioError(Exception):
    """Raised for capture-device / recording problems (mapped to exit 2)."""


def _require_deps() -> None:
    if _IMPORT_ERROR is not None:
        raise AudioError(
            "audio capture needs sounddevice/soundfile/numpy: %s. "
            "Install with: .venv/bin/pip install sounddevice soundfile"
            % _IMPORT_ERROR
        )


def list_input_devices() -> List[dict]:
    """All input-capable devices, flagging likely loopback ones."""
    _require_deps()
    out = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) <= 0:
            continue
        name = dev.get("name", "")
        out.append({
            "index": idx,
            "name": name,
            "input_channels": dev["max_input_channels"],
            "default_samplerate": int(dev.get("default_samplerate", 0)),
            "is_loopback": _looks_like_loopback(name),
        })
    return out


def _looks_like_loopback(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in LOOPBACK_HINTS)


def find_loopback_device(prefer: Optional[str] = None) -> dict:
    """Pick the loopback input device, or raise a clear, actionable error.

    ``prefer`` is a name substring to force a particular device.
    """
    devices = list_input_devices()
    if prefer:
        for d in devices:
            if prefer.lower() in d["name"].lower():
                return d
        raise AudioError(
            "no input device matching %r; available: %s"
            % (prefer, ", ".join(d["name"] for d in devices) or "(none)")
        )
    candidates = [d for d in devices if d["is_loopback"]]
    if not candidates:
        raise AudioError(
            "no loopback input device found (looked for: %s). Install BlackHole "
            "(https://existential.audio/blackhole/), create a Multi-Output Device "
            "in Audio MIDI Setup that includes it, and set Live's output to that "
            "device. See AGENT_GUIDE.md > Audio capture setup." % ", ".join(LOOPBACK_HINTS)
        )
    return candidates[0]


def record(
    seconds: float,
    out_path: str,
    *,
    device: Optional[str] = None,
    samplerate: int = DEFAULT_SAMPLERATE,
    channels: int = DEFAULT_CHANNELS,
) -> dict:
    """Record ``seconds`` of audio from the loopback device to a WAV file.

    Returns a dict describing the capture (device, duration, peak level). A near-
    silent capture is flagged so the agent knows nothing was actually playing or
    the routing is wrong.
    """
    _require_deps()
    dev = find_loopback_device(device)
    sr = samplerate or dev["default_samplerate"] or DEFAULT_SAMPLERATE
    frames = int(sr * seconds)

    recording = sd.rec(frames, samplerate=sr, channels=channels,
                       device=dev["index"], dtype="float32")
    sd.wait()

    peak = float(np.max(np.abs(recording))) if frames else 0.0
    rms = float(np.sqrt(np.mean(recording ** 2))) if frames else 0.0
    sf.write(out_path, recording, sr, subtype="PCM_16")

    return {
        "ok": True,
        "path": out_path,
        "device": dev["name"],
        "seconds": round(seconds, 3),
        "samplerate": sr,
        "channels": channels,
        "peak": round(peak, 4),
        "rms": round(rms, 5),
        "silent": peak < 0.001,
    }


def beats_to_seconds(beats: float, bpm: float) -> float:
    """Convert a length in beats to seconds at the given tempo."""
    if bpm <= 0:
        raise AudioError("tempo must be > 0, got %r" % bpm)
    return beats * 60.0 / bpm


def capture_clip(
    live,
    track: int,
    clip: int,
    out_path: str,
    *,
    device: Optional[str] = None,
    tail: float = 0.4,
    lead: float = 0.15,
) -> dict:
    """Fire a clip and record exactly its length (computed from tempo + beats).

    Loops the clip, fires it, waits a short ``lead`` for audio to start, records
    ``length_beats * 60/bpm`` seconds plus a ``tail``, then stops the clip. Fully
    unattended. Restores the prior transport-stopped state when done.
    """
    _require_deps()
    bpm = live.get_tempo()
    length_beats = live.get_clip_length(track, clip)
    duration = beats_to_seconds(length_beats, bpm) + tail

    live.fire_clip(track, clip)
    if lead:
        time.sleep(lead)
    info = record(duration, out_path, device=device)
    live.stop_clip(track, clip)

    info.update(track=track, clip=clip, bpm=bpm,
                length_beats=length_beats, tail=tail)
    return info


def capture_master(
    live,
    bars: float,
    out_path: str,
    *,
    device: Optional[str] = None,
    beats_per_bar: float = 4.0,
    tail: float = 0.4,
    lead: float = 0.15,
) -> dict:
    """Start the transport and record ``bars`` bars of the master output."""
    _require_deps()
    bpm = live.get_tempo()
    duration = beats_to_seconds(bars * beats_per_bar, bpm) + tail

    live.play()
    if lead:
        time.sleep(lead)
    info = record(duration, out_path, device=device)
    live.stop()

    info.update(bars=bars, bpm=bpm, beats_per_bar=beats_per_bar, tail=tail)
    return info
