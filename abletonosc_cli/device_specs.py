"""Friendly parameter aliases for common Ableton stock devices.

Tier 2 of the build plan: an ergonomic layer over raw device-parameter control.
The hard rule (from the plan) is that we resolve parameters by their **real
name at runtime** — we never hard-code parameter indices, which drift between
Live versions. This registry only supplies:

  * friendly alias -> real parameter name (what the CLI flag maps to), and
  * an optional ``(min, max)`` safe range for documentation / validation.

Lookups are keyed by the device's ``class_name`` (as reported by
``/live/track/get/devices/class_name``), which is stable across localisations,
unlike the display ``name``.

Each spec entry maps an alias to either:
  * a string  -> the real parameter name, or
  * a dict    -> {"param": <real name>, "range": (min, max), "help": <str>}

Parameter names were verified against Ableton Live 12.4 stock devices.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple, Union

AliasSpec = Union[str, Dict[str, object]]


def _p(param: str, range_: Optional[Tuple[float, float]] = None,
       help_: Optional[str] = None) -> Dict[str, object]:
    spec: Dict[str, object] = {"param": param}
    if range_ is not None:
        spec["range"] = range_
    if help_ is not None:
        spec["help"] = help_
    return spec


#--------------------------------------------------------------------------------
# EQ Eight: 8 bands, each with Frequency/Gain/Q (A channel by default).
# Frequency and Q are normalised 0..1; Gain is in dB (-15..15).
# We expose per-band aliases band1..band8 plus convenience low/lowmid/.../high.
#--------------------------------------------------------------------------------
def _eq_eight_aliases() -> Dict[str, AliasSpec]:
    aliases: Dict[str, AliasSpec] = {}
    for band in range(1, 9):
        aliases[f"band{band}-freq"] = _p(f"{band} Frequency A", (0.0, 1.0))
        aliases[f"band{band}-gain"] = _p(f"{band} Gain A", (-15.0, 15.0))
        aliases[f"band{band}-q"] = _p(f"{band} Q A", (0.0, 1.0))
        aliases[f"band{band}-on"] = _p(f"{band} Filter On A", (0.0, 1.0))
        aliases[f"band{band}-type"] = _p(f"{band} Filter Type A", (0.0, 7.0))
    # Friendly names for the common bands.
    aliases["low-gain"] = aliases["band1-gain"]
    aliases["low-freq"] = aliases["band1-freq"]
    aliases["lowmid-gain"] = aliases["band3-gain"]
    aliases["mid-gain"] = aliases["band4-gain"]
    aliases["highmid-gain"] = aliases["band6-gain"]
    aliases["high-gain"] = aliases["band8-gain"]
    aliases["high-freq"] = aliases["band8-freq"]
    aliases["output"] = _p("Output", (-12.0, 12.0))
    return aliases


DEVICE_SPECS: Dict[str, Dict[str, AliasSpec]] = {
    # class_name -> {alias -> spec}
    "Eq8": _eq_eight_aliases(),
    "Compressor2": {
        "threshold": _p("Threshold", (0.0, 1.0)),
        "ratio": _p("Ratio", (0.0, 1.0)),
        "attack": _p("Attack", (0.0, 1.0)),
        "release": _p("Release", (0.0, 1.0)),
        "makeup": _p("Makeup", (0.0, 1.0)),
        "knee": _p("Knee", (0.0, 18.0)),
        "output": _p("Output", (-36.0, 36.0)),
        "dry-wet": _p("Dry/Wet", (0.0, 1.0)),
    },
    "Reverb": {
        "decay": _p("Decay Time", (0.0, 1.0)),
        "predelay": _p("Predelay", (0.0, 1.0)),
        "size": _p("Room Size", (0.0, 1.0)),
        "diffusion": _p("Diffusion", (0.0, 1.0)),
        "density": _p("Density", (0.0, 3.0)),
        "stereo": _p("Stereo Image", (0.0, 1.0)),
        "dry-wet": _p("Dry/Wet", (0.0, 1.0)),
    },
    "AutoFilter": {
        "freq": _p("Frequency", (0.0, 1.0)),
        "resonance": _p("Resonance", (0.0, 1.0)),
        "type": _p("Filter Type", (0.0, 9.0)),
        "drive": _p("Drive", (0.0, 1.0)),
        "lfo-amount": _p("LFO Amount", (0.0, 1.0)),
        "env-amount": _p("Env Amount", (0.0, 1.0)),
        "dry-wet": _p("Dry/Wet", (0.0, 1.0)),
    },
    "Limiter": {
        "ceiling": _p("Ceiling", (0.0, 1.0)),
        "gain": _p("Input Gain", (0.0, 1.0)),
        "release": _p("Release", (0.0, 1.0)),
    },
    "StereoGain": {  # Utility
        "width": _p("Stereo Width", (0.0, 2.0)),
        "gain": _p("Output", (-1.0, 1.0)),
        "balance": _p("Balance", (-1.0, 1.0)),
        "bass-mono": _p("Bass Mono", (0.0, 1.0)),
        "mono": _p("Mono", (0.0, 1.0)),
    },
}

# Map the friendly ``fx`` subcommand name to the device class_name(s) it targets.
# Multiple class names because Live's class_name can vary; the first that matches
# the device on the track wins.
FX_COMMANDS: Dict[str, Tuple[str, ...]] = {
    "eq8": ("Eq8",),
    "compressor": ("Compressor2",),
    "reverb": ("Reverb",),
    "autofilter": ("AutoFilter",),
    "limiter": ("Limiter",),
    "utility": ("StereoGain",),
}


def resolve_alias(class_name: str, alias: str) -> Optional[Dict[str, object]]:
    """Return the spec dict for ``alias`` on a device of ``class_name``."""
    table = DEVICE_SPECS.get(class_name)
    if not table:
        return None
    spec = table.get(alias)
    if spec is None:
        return None
    if isinstance(spec, str):
        return {"param": spec}
    return dict(spec)
