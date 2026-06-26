"""Musical note helpers — convert between note names and MIDI pitch numbers.

Lets the CLI accept human/AI-friendly note names like ``C3``, ``F#4``, ``Bb2``
instead of raw MIDI integers. Uses the convention where MIDI note 60 == C3
(Ableton's display convention).
"""

from __future__ import annotations

import re
from typing import Union

_NOTE_OFFSETS = {
    "C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11,
}
_ACCIDENTALS = {"#": 1, "s": 1, "b": -1, "f": -1}

# Ableton displays MIDI note 60 as "C3".
_OCTAVE_OFFSET = 2  # midi = (octave + _OCTAVE_OFFSET) * 12 + semitone

_NOTE_RE = re.compile(r"^([A-Ga-g])([#sbf]?)(-?\d+)$")


def note_to_midi(value: Union[str, int]) -> int:
    """Convert a note name (e.g. 'C3', 'F#4', 'Bb2') or int to a MIDI number."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)

    m = _NOTE_RE.match(value.strip())
    if not m:
        raise ValueError(f"Invalid note name: {value!r}")
    letter, accidental, octave = m.groups()
    semitone = _NOTE_OFFSETS[letter.upper()]
    if accidental:
        semitone += _ACCIDENTALS[accidental]
    midi = (int(octave) + _OCTAVE_OFFSET) * 12 + semitone
    if not 0 <= midi <= 127:
        raise ValueError(f"Note {value!r} is out of MIDI range (0-127): {midi}")
    return midi


_PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_to_note(midi: int) -> str:
    """Convert a MIDI number to a note name like 'C3'."""
    octave = midi // 12 - _OCTAVE_OFFSET
    return f"{_PITCH_NAMES[midi % 12]}{octave}"
