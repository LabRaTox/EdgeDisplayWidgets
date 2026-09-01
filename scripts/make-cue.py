#!/usr/bin/env python3
"""Writes the pomodoro cue as a WAV file.

The sound was synthesised with the Web Audio API once: three sine
bursts at 880 Hz, a 10 ms attack to 0.25 and a decay to silence after 180 ms,
one every 250 ms. QML has no oscillator, so the same tone is written once to
shell/qml_kiosk/assets/cue.wav and played from there.

    python3 scripts/make-cue.py
"""

import math
import pathlib
import struct
import wave

RATE = 44100
FREQ = 880.0
BURSTS = 3
SPACING = 0.25
ATTACK = 0.01
DECAY_TO = 0.18
PEAK = 0.25

OUT = pathlib.Path(__file__).resolve().parent.parent / "shell/qml_kiosk/assets/cue.wav"


def main() -> None:
    total = int(RATE * (SPACING * (BURSTS - 1) + 0.2))
    samples = [0.0] * total
    for i in range(BURSTS):
        start = int(RATE * i * SPACING)
        for n in range(int(RATE * 0.2)):
            t = n / RATE
            if t < ATTACK:
                gain = PEAK * (t / ATTACK)
            else:
                # exponential ramp down
                gain = PEAK * math.exp(math.log(0.0004 / PEAK) * (t - ATTACK) / (DECAY_TO - ATTACK))
            index = start + n
            if index < total:
                samples[index] += gain * math.sin(2 * math.pi * FREQ * t)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(s * 32767)))) for s in samples
        ))
    print(f"{OUT} ({OUT.stat().st_size} Bytes)")


if __name__ == "__main__":
    main()
