"""High-level AbletonOSC API.

Wraps the raw OSC address patterns in a typed Python interface. Getter replies
from AbletonOSC echo back the id arguments first (e.g. track_id), so the helpers
here strip those and return just the value(s) of interest.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from .notes import note_to_midi
from .osc_client import OSCClient


class Live:
    def __init__(self, client: OSCClient) -> None:
        self.c = client

    # ---- application ----
    def version(self) -> str:
        major = self.c.query("/live/application/get/version")
        return ".".join(str(x) for x in major)

    def test_connection(self) -> bool:
        try:
            self.c.query("/live/test", timeout=1.5)
            return True
        except Exception:
            return False

    # ---- transport / song ----
    def get_tempo(self) -> float:
        return float(self.c.query("/live/song/get/tempo")[0])

    def set_tempo(self, bpm: float) -> None:
        self.c.send("/live/song/set/tempo", float(bpm))

    def is_playing(self) -> bool:
        return bool(self.c.query("/live/song/get/is_playing")[0])

    def play(self) -> None:
        self.c.send("/live/song/start_playing")

    def stop(self) -> None:
        self.c.send("/live/song/stop_playing")

    def continue_playing(self) -> None:
        self.c.send("/live/song/continue_playing")

    def stop_all_clips(self) -> None:
        self.c.send("/live/song/stop_all_clips")

    def set_metronome(self, on: bool) -> None:
        self.c.send("/live/song/set/metronome", 1 if on else 0)

    def undo(self) -> None:
        self.c.send("/live/song/undo")

    def redo(self) -> None:
        self.c.send("/live/song/redo")

    def num_tracks(self) -> int:
        return int(self.c.query("/live/song/get/num_tracks")[0])

    def num_scenes(self) -> int:
        return int(self.c.query("/live/song/get/num_scenes")[0])

    def track_names(self) -> List[str]:
        return list(self.c.query("/live/song/get/track_names"))

    def create_midi_track(self, index: int = -1) -> None:
        self.c.send("/live/song/create_midi_track", index)

    def create_audio_track(self, index: int = -1) -> None:
        self.c.send("/live/song/create_audio_track", index)

    def create_scene(self, index: int = -1) -> None:
        self.c.send("/live/song/create_scene", index)

    def delete_track(self, index: int) -> None:
        self.c.send("/live/song/delete_track", index)

    # ---- tracks ----
    def get_track_name(self, track: int) -> str:
        return self.c.query("/live/track/get/name", track)[1]

    def set_track_name(self, track: int, name: str) -> None:
        self.c.send("/live/track/set/name", track, name)

    def set_track_color(self, track: int, color_index: int) -> None:
        self.c.send("/live/track/set/color_index", track, color_index)

    def get_track_volume(self, track: int) -> float:
        return float(self.c.query("/live/track/get/volume", track)[1])

    def set_track_volume(self, track: int, volume: float) -> None:
        self.c.send("/live/track/set/volume", track, float(volume))

    def set_track_panning(self, track: int, panning: float) -> None:
        self.c.send("/live/track/set/panning", track, float(panning))

    def set_track_mute(self, track: int, mute: bool) -> None:
        self.c.send("/live/track/set/mute", track, 1 if mute else 0)

    def set_track_solo(self, track: int, solo: bool) -> None:
        self.c.send("/live/track/set/solo", track, 1 if solo else 0)

    def set_track_arm(self, track: int, arm: bool) -> None:
        self.c.send("/live/track/set/arm", track, 1 if arm else 0)

    def get_track_devices(self, track: int) -> List[str]:
        reply = self.c.query("/live/track/get/devices/name", track)
        return list(reply[1:])  # strip track_id

    def get_track_clip_names(self, track: int) -> List[str]:
        reply = self.c.query("/live/track/get/clips/name", track)
        return list(reply[1:])

    # ---- clip slots / clips ----
    def has_clip(self, track: int, clip: int) -> bool:
        return bool(self.c.query("/live/clip_slot/get/has_clip", track, clip)[2])

    def create_clip(self, track: int, clip: int, length: float) -> None:
        self.c.send("/live/clip_slot/create_clip", track, clip, float(length))

    def delete_clip(self, track: int, clip: int) -> None:
        self.c.send("/live/clip_slot/delete_clip", track, clip)

    def fire_clip(self, track: int, clip: int) -> None:
        self.c.send("/live/clip/fire", track, clip)

    def stop_clip(self, track: int, clip: int) -> None:
        self.c.send("/live/clip/stop", track, clip)

    def set_clip_name(self, track: int, clip: int, name: str) -> None:
        self.c.send("/live/clip/set/name", track, clip, name)

    def set_clip_color(self, track: int, clip: int, color_index: int) -> None:
        self.c.send("/live/clip/set/color_index", track, clip, color_index)

    def set_clip_loop(self, track: int, clip: int, start: float, end: float) -> None:
        self.c.send("/live/clip/set/loop_start", track, clip, float(start))
        self.c.send("/live/clip/set/loop_end", track, clip, float(end))

    def get_clip_length(self, track: int, clip: int) -> float:
        return float(self.c.query("/live/clip/get/length", track, clip)[2])

    def add_notes(self, track: int, clip: int, notes: Sequence[Tuple]) -> None:
        """Add MIDI notes. Each note is (pitch, start_time, duration, velocity, mute).

        ``pitch`` may be a note name (e.g. 'C3') or a MIDI int.
        """
        args: List[Any] = [track, clip]
        for n in notes:
            pitch, start, duration = n[0], n[1], n[2]
            velocity = n[3] if len(n) > 3 else 100
            mute = n[4] if len(n) > 4 else 0
            args += [
                note_to_midi(pitch),
                float(start),
                float(duration),
                int(velocity),
                int(bool(mute)),
            ]
        self.c.send("/live/clip/add/notes", *args)

    def get_notes(self, track: int, clip: int) -> List[Tuple]:
        """Return notes as (pitch, start_time, duration, velocity, mute) tuples."""
        reply = self.c.query("/live/clip/get/notes", track, clip)
        data = reply[2:]  # strip track_id, clip_id
        notes = []
        for i in range(0, len(data) - 4, 5):
            notes.append(tuple(data[i : i + 5]))
        return notes

    def remove_notes(self, track: int, clip: int) -> None:
        """Remove all notes from a clip (full pitch and time span)."""
        self.c.send("/live/clip/remove/notes", track, clip, 0, 127, 0.0, 1_000_000.0)

    # ---- scenes ----
    def fire_scene(self, scene: int) -> None:
        self.c.send("/live/scene/fire", scene)
