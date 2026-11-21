"""Compose original, royalty-free background tracks for the Reels (no samples, no third-party audio).

usage: python tool/make_music.py            # writes tool/music/bgm_01.m4a ... bgm_06.m4a

Each track is ~26 s of light, cheerful music (soft pad, bass, marimba-like melody, quiet beat),
built from simple synthesis with numpy, so the account owns it outright and nothing can be
claimed by copyright matching. render.py picks one track per day by date.
"""
import subprocess, sys, wave
from pathlib import Path
import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent / "music"

def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)

def env_adsr(n, a, d, s, r):
    a, d, r = int(a * SR), int(d * SR), int(r * SR)
    e = np.full(n, s, dtype=np.float64)
    e[:a] = np.linspace(0, 1, a, endpoint=False) if a else e[:a]
    e[a:a + d] = np.linspace(1, s, d, endpoint=False)[: max(0, min(d, n - a))]
    if r and n > r:
        e[-r:] *= np.linspace(1, 0, r)
    return e

def tone(freq, dur, kind="sine"):
    t = np.arange(int(dur * SR)) / SR
    if kind == "pad":  # three detuned soft triangles
        x = sum(2 / np.pi * np.arcsin(np.sin(2 * np.pi * freq * (1 + dt) * t)) for dt in (-0.004, 0, 0.004)) / 3
        return x * env_adsr(len(t), 0.25, 0.3, 0.8, 0.4)
    if kind == "mallet":  # marimba/bell: fundamental + 4th partial, fast decay
        e = np.exp(-t * 5.5)
        return (np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * freq * 4.0 * t) * np.exp(-t * 14)) * e
    if kind == "bass":
        return np.sin(2 * np.pi * freq * t) * env_adsr(len(t), 0.01, 0.15, 0.6, 0.08)
    return np.sin(2 * np.pi * freq * t)

def kick(dur=0.25):
    t = np.arange(int(dur * SR)) / SR
    f = 110 * np.exp(-t * 18) + 45
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14)

def hat(rng, dur=0.05):
    n = rng.standard_normal(int(dur * SR))
    n = np.diff(n, prepend=0)  # crude high-pass
    return n * np.exp(-np.arange(len(n)) / SR * 70) * 0.25

def snap(rng, dur=0.12):
    n = rng.standard_normal(int(dur * SR))
    return n * np.exp(-np.arange(len(n)) / SR * 30) * 0.35

def place(buf, x, at, gain):
    i = int(at * SR)
    j = min(len(buf), i + len(x))
    if i < len(buf):
        buf[i:j] += x[: j - i] * gain

def reverb(x, mix=0.22):
    y = x.copy()
    for d, g in ((0.031, 0.5), (0.047, 0.42), (0.071, 0.35), (0.113, 0.28)):
        k = int(d * SR)
        z = np.zeros_like(x)
        for i in range(1, 6):
            if k * i < len(x):
                z[k * i:] += x[: -k * i] * (g ** i)
        y += z * mix
    return y

# (root midi, scale offsets for major pentatonic, chord progression in scale degrees, bpm)
STYLES = [
    (60, [0, 4, 7], [[0, 4, 7], [7, 11, 14], [9, 12, 16], [5, 9, 12]], 104),   # C: I V vi IV
    (62, [0, 4, 7], [[0, 4, 7], [9, 12, 16], [5, 9, 12], [7, 11, 14]], 98),   # D: I vi IV V
    (65, [0, 4, 7], [[0, 4, 7], [5, 9, 12], [9, 12, 16], [7, 11, 14]], 110),  # F: I IV vi V
    (67, [0, 4, 7], [[0, 4, 7], [4, 7, 11], [5, 9, 12], [7, 11, 14]], 100),   # G: I iii IV V
    (64, [0, 4, 7], [[5, 9, 12], [7, 11, 14], [4, 7, 11], [9, 12, 16]], 106), # E: IV V iii vi
    (63, [0, 4, 7], [[0, 4, 7], [7, 11, 14], [5, 9, 12], [5, 9, 12]], 96),    # Eb: I V IV IV
]
PENTA = [0, 2, 4, 7, 9, 12, 14, 16]

def compose(idx, seconds=26.0):
    root, _, prog, bpm = STYLES[idx]
    rng = np.random.default_rng(1000 + idx)
    beat = 60 / bpm
    bar = 4 * beat
    n = int(seconds * SR)
    mix = np.zeros(n)
    t, bar_i = 0.0, 0
    while t < seconds:
        chord = prog[bar_i % len(prog)]
        # pad chord
        for c in chord:
            place(mix, tone(midi_hz(root + c - 12), bar + 0.3, "pad"), t, 0.10)
        # bass on beats 1 and 3
        for b in (0, 2):
            place(mix, tone(midi_hz(root + chord[0] - 24), beat * 0.9, "bass"), t + b * beat, 0.30)
        # beat: kick 1/3, snap 2/4, hats on 8ths (enter after the first bar)
        if bar_i >= 1:
            for b in range(4):
                if b in (0, 2):
                    place(mix, kick(), t + b * beat, 0.45)
                else:
                    place(mix, snap(rng), t + b * beat, 0.18)
            for e in range(8):
                place(mix, hat(rng), t + e * beat / 2, 0.22 if e % 2 else 0.12)
        # melody: 8th-note mallet line on pentatonic notes, leaning on chord tones, with rests
        prev = PENTA[rng.integers(2, 5)]
        for e in range(8):
            if rng.random() < 0.28 and e not in (0, 4):
                continue
            if e in (0, 4):
                cand = [p for p in PENTA if (p % 12) in [c % 12 for c in chord]] or PENTA
                note = min(cand, key=lambda p: abs(p - prev) + rng.random())
            else:
                step = int(rng.choice([-2, -1, 1, 1, 2]))
                note = PENTA[int(np.clip(PENTA.index(prev) + step, 0, len(PENTA) - 1))] if prev in PENTA else PENTA[3]
            prev = note
            place(mix, tone(midi_hz(root + 12 + note), 0.9, "mallet"), t + e * beat / 2, 0.20)
        t += bar
        bar_i += 1
    mix = reverb(mix)
    fade = int(0.8 * SR)
    mix[:int(0.05 * SR)] *= np.linspace(0, 1, int(0.05 * SR))
    mix[-fade:] *= np.linspace(1, 0, fade)
    mix /= np.max(np.abs(mix)) + 1e-9
    return (mix * 0.85 * 32767).astype(np.int16)

def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from render import find_ffmpeg
    ff = find_ffmpeg()
    OUT.mkdir(exist_ok=True)
    for i in range(len(STYLES)):
        pcm = compose(i)
        wav = OUT / f"bgm_{i + 1:02d}.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
        m4a = wav.with_suffix(".m4a")
        subprocess.run([ff, "-y", "-i", str(wav), "-ac", "2", "-c:a", "aac", "-b:a", "160k", str(m4a)],
                       check=True, capture_output=True)
        wav.unlink()
        print("ok", m4a.name)

if __name__ == "__main__":
    main()
