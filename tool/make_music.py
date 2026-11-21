"""Compose original, royalty-free background tracks for the Reels (no samples, no third-party audio).

usage: python tool/make_music.py            # writes tool/music/bgm_01.m4a ... bgm_06.m4a

v2 (2026-11-22): calm, fuller "lo-fi / ambient piano" sound - soft piano and Rhodes-style keys
with 7th/9th chords, warm pad, round bass, gentle brushed beat on some tracks, stereo
convolution reverb and soft mastering. Everything is synthesized here with numpy, so the
account owns the result outright and nothing can be claimed by copyright matching.
render.py picks one track per day by date.
"""
import subprocess, sys, wave
from pathlib import Path
import numpy as np

SR = 44100
SECONDS = 27.0
OUT = Path(__file__).resolve().parent / "music"

# ---------- helpers ----------
def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)

def tt(dur):
    return np.arange(int(dur * SR)) / SR

def lowpass(x, fc, order=2):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X / np.sqrt(1 + (f / fc) ** (2 * order)), len(x))

def highpass(x, fc, order=2):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR) + 1e-9
    return np.fft.irfft(X / np.sqrt(1 + (fc / f) ** (2 * order)), len(x))

def fade(n, a, r):
    e = np.ones(n)
    a, r = min(int(a * SR), n), min(int(r * SR), n)
    if a:
        e[:a] = np.linspace(0, 1, a) ** 2
    if r:
        e[-r:] *= np.linspace(1, 0, r) ** 2
    return e

class Bus:
    """Stereo bus; place() pans a mono sound into it."""
    def __init__(self, n):
        self.L, self.R = np.zeros(n), np.zeros(n)
    def place(self, x, at, gain=1.0, pan=0.0):
        i = int(at * SR)
        if i >= len(self.L):
            return
        j = min(len(self.L), i + len(x))
        seg = x[: j - i] * gain
        self.L[i:j] += seg * np.cos((pan + 1) * np.pi / 4)
        self.R[i:j] += seg * np.sin((pan + 1) * np.pi / 4)
    def arr(self):
        return np.stack([self.L, self.R])

# ---------- instruments ----------
def piano(f, dur, vel=1.0):
    t = tt(dur + 1.2)
    B = 0.00035
    x = np.zeros_like(t)
    for k in range(1, 9):
        fk = f * k * np.sqrt(1 + B * k * k)
        if fk > 12000:
            break
        decay = 0.6 + 0.9 * k + f / 600
        x += (1 / k ** 1.25) * np.sin(2 * np.pi * fk * t) * np.exp(-t * decay)
    x += 0.15 * np.sin(2 * np.pi * f * 1.003 * t) * np.exp(-t * 0.8)  # slight chorus
    x *= fade(len(t), 0.004, 0.35)
    return x * vel

def rhodes(f, dur, vel=1.0):
    t = tt(dur + 0.8)
    idx = 1.3 * vel * np.exp(-t * 4) + 0.25
    x = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * t))
    x += 0.12 * np.sin(2 * np.pi * f * 7.0 * t) * np.exp(-t * 12)  # tine "ping"
    x *= np.exp(-t * 1.1) * (1 + 0.12 * np.sin(2 * np.pi * 4.5 * t))  # gentle tremolo
    return x * fade(len(t), 0.006, 0.4) * vel

def pad(freqs, dur):
    t = tt(dur)
    x = np.zeros_like(t)
    for f in freqs:
        for det in (-0.006, 0.0, 0.0055):
            ph = np.random.default_rng(int(f * 10)).random() * 6.28
            for k in range(1, 9):
                x += np.sin(2 * np.pi * f * (1 + det) * k * t + ph * k) / (k * 1.6)
    return x * fade(len(t), 0.5, 1.6) / (len(freqs) * 3)

def bass(f, dur):
    t = tt(dur)
    x = np.sin(2 * np.pi * f * t) + 0.18 * np.sin(4 * np.pi * f * t)
    return x * fade(len(t), 0.012, 0.12) * (0.75 + 0.25 * np.exp(-t * 3))

def kick():
    t = tt(0.45)
    f = 48 + 70 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)

def brush_snare(rng):
    n = rng.standard_normal(int(0.32 * SR))
    n = lowpass(highpass(n, 900), 5500)
    return n * np.exp(-tt(0.32) * 11) * 0.6

def shaker(rng):
    n = highpass(rng.standard_normal(int(0.07 * SR)), 6000)
    return n * np.sin(np.linspace(0, np.pi, len(n))) ** 2 * 0.5

def reverb_ir(seconds, seed):
    rng = np.random.default_rng(seed)
    t = tt(seconds)
    env = np.exp(-t * 6.9 / seconds)
    pre = int(0.022 * SR)
    irs = []
    for _ in range(2):
        n = rng.standard_normal(len(t)) * env
        n = lowpass(n, 5200)
        n[:pre] = 0
        irs.append(n / np.sqrt(np.sum(n ** 2)))
    return irs

def convolve(x, ir):
    n = len(x) + len(ir)
    size = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)
    return y[: len(x)]

# ---------- harmony ----------
CH = {  # semitones from the chord root
    "maj7": [0, 4, 7, 11], "maj9": [0, 4, 7, 11, 14], "m7": [0, 3, 7, 10], "m9": [0, 3, 7, 10, 14],
    "7sus": [0, 5, 7, 10], "add9": [0, 4, 7, 14], "6": [0, 4, 7, 9],
}
# name, key root (midi), bpm, beat?, progression [(degree semitones, quality), ...], lead instrument
STYLES = [
    ("lofi_morning", 62, 80, True, [(0, "maj7"), (9, "m9"), (5, "maj7"), (7, "7sus")], "rhodes"),
    ("soft_cafe", 65, 76, True, [(2, "m9"), (7, "7sus"), (0, "maj9"), (9, "m7")], "rhodes"),
    ("piano_dawn", 60, 70, False, [(5, "maj7"), (4, "m7"), (9, "m9"), (0, "maj7")], "piano"),
    ("calm_breeze", 67, 72, False, [(0, "maj9"), (5, "maj9"), (0, "maj9"), (5, "add9")], "piano"),
    ("warm_window", 63, 82, True, [(9, "m9"), (5, "maj7"), (0, "maj7"), (7, "6")], "rhodes"),
    ("quiet_walk", 64, 74, True, [(0, "maj7"), (4, "m7"), (5, "maj9"), (2, "m9")], "piano"),
]

def voicing(root, deg, q):
    base = root + deg
    while base > root + 5:
        base -= 12
    notes = [base + s for s in CH[q]]
    return [n if n >= 55 else n + 12 for n in notes]  # keep the chord warm, not muddy

def compose(idx):
    name, root, bpm, beat_on, prog, lead = STYLES[idx]
    rng = np.random.default_rng(2026 + idx)
    beat = 60 / bpm
    bar = 4 * beat
    n = int(SECONDS * SR)
    keys, pads, low, drums, mel = Bus(n), Bus(n), Bus(n), Bus(n), Bus(n)
    kicks = []
    swing = beat / 2 * 0.58  # lazy swung 8ths
    t, bi = 0.0, 0
    prev_top = None
    while t < SECONDS:
        deg, q = prog[bi % len(prog)]
        ch = voicing(root, deg, q)
        # pad holds the chord a little past the barline
        pads.place(pad([hz(m - 12) for m in ch[:4]], bar + 1.8), max(0.0, t - 0.3), 0.75)  # overlapping, no gaps
        # bass: root on 1, fifth or root on the "and" of 3
        r = root + deg - 24
        while r < 36:
            r += 12
        low.place(bass(hz(r), beat * 2.5), t, 0.26)
        low.place(bass(hz(r + (7 if bi % 2 else 0)), beat * 1.5), t + 2.5 * beat, 0.20)
        # keys: rolled chord on 1, soft re-hit on the "and" of 2
        inst = rhodes if lead == "rhodes" else piano
        for i, m in enumerate(ch):
            keys.place(inst(hz(m), beat * 2.2, 0.55), t + i * 0.018, 0.30, pan=-0.35 + 0.7 * i / max(1, len(ch) - 1))
        for i, m in enumerate(ch[1:]):
            keys.place(inst(hz(m), beat * 1.2, 0.35), t + beat + swing + i * 0.012, 0.22, pan=0.2)
        # melody: sparse, high, gentle - 2 or 3 notes a bar from chord tones + 9th
        cand = sorted({m + 12 for m in ch} | {ch[0] + 14})
        cand = [c for c in cand if 67 <= c <= 86] or [ch[-1] + 12]
        slots = [0.0, 1.5, 2.0, 3.0] if bi % 2 == 0 else [0.5, 2.0, 3.5]
        for s in slots:
            if rng.random() < 0.3:
                continue
            m = min(cand, key=lambda c: abs(c - (prev_top or c)) + rng.random() * 4)
            prev_top = m
            mel.place(piano(hz(m), beat * 1.4, 0.5), t + s * beat, 0.16, pan=0.25)
        # beat (lo-fi tracks only; starts after the first bar, very soft)
        if beat_on and bi >= 1:
            for b in (0, 2.5):
                drums.place(kick(), t + b * beat, 0.55)
                kicks.append(t + b * beat)
            for b in (1, 3):
                drums.place(brush_snare(rng), t + b * beat, 0.22)
            for e in range(8):
                at = t + (e // 2) * beat + (swing if e % 2 else 0)
                drums.place(shaker(rng), at, 0.10 if e % 2 else 0.06, pan=0.4)
        t += bar
        bi += 1

    # gentle "breathing" on the pad from the kick (lo-fi pump)
    duck = np.ones(n)
    for k in kicks:
        i = int(k * SR)
        seg = np.arange(min(n - i, int(0.5 * SR)))
        duck[i:i + len(seg)] *= 1 - 0.22 * np.exp(-seg / SR / 0.16)

    padA = np.stack([lowpass(pads.L, 1800), lowpass(pads.R, 1800)]) * duck
    keysA, melA, lowA, drumsA = keys.arr(), mel.arr(), low.arr(), drums.arr()
    lowA = np.stack([lowpass(lowA[0], 400), lowpass(lowA[1], 400)])
    drumsA = np.stack([lowpass(drumsA[0], 7000), lowpass(drumsA[1], 7000)])

    dry = padA + keysA + melA + lowA + drumsA
    send = padA * 0.6 + keysA * 0.8 + melA * 1.0 + drumsA * 0.15
    irL, irR = reverb_ir(2.6, 7 + idx)
    wet = np.stack([convolve(send[0], irL), convolve(send[1], irR)])
    mix = dry + wet * 0.55

    # very quiet tape hiss for warmth on lo-fi tracks
    if beat_on:
        hiss = lowpass(highpass(rng.standard_normal(n), 2000), 8000) * 0.0025
        mix += np.stack([hiss, np.roll(hiss, 337)])

    # master: tame highs, soft saturation, loudness to ~-16 dBFS RMS, peak safety, fades
    mix = np.stack([lowpass(mix[0], 11000, 1), lowpass(mix[1], 11000, 1)])
    mix /= np.max(np.abs(mix)) + 1e-9
    mix = np.tanh(mix * 1.3) / np.tanh(1.3)
    rms = np.sqrt(np.mean(mix ** 2))
    mix *= 10 ** (-16 / 20) / (rms + 1e-9)
    peak = np.max(np.abs(mix))
    if peak > 0.89:
        mix *= 0.89 / peak
    mix *= fade(n, 0.6, 1.5)
    return name, (mix.T * 32767).astype(np.int16)

def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from render import find_ffmpeg
    ff = find_ffmpeg()
    OUT.mkdir(exist_ok=True)
    for i in range(len(STYLES)):
        name, pcm = compose(i)
        wav = OUT / f"bgm_{i + 1:02d}.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
        m4a = wav.with_suffix(".m4a")
        subprocess.run([ff, "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "192k", str(m4a)],
                       check=True, capture_output=True)
        wav.unlink()
        print("ok", m4a.name, name)

if __name__ == "__main__":
    main()
