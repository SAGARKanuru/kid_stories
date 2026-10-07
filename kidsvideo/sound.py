"""Voices (edge-tts), original music, ambience and sound effects — all generated, nothing licensed."""
import asyncio
import hashlib
import os
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

SR = 48000


# ---------------------------------------------------------------- utilities
def decode(path: str | Path) -> np.ndarray:
    """Any audio file -> mono float32 at SR."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def write_wav(path: str | Path, audio: np.ndarray):
    """float32 mono or (n, 2) stereo -> wav via ffmpeg."""
    a = np.asarray(audio, dtype=np.float32)
    ch = 1 if a.ndim == 1 else a.shape[1]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", str(ch),
                    "-i", "-", str(path)], input=a.tobytes(), check=True)


def place(dst: np.ndarray, src: np.ndarray, t: float, gain: float = 1.0):
    i = int(t * SR)
    if i >= len(dst) or i + len(src) <= 0:
        return
    s0 = max(0, -i)
    n = min(len(src) - s0, len(dst) - max(i, 0))
    dst[max(i, 0):max(i, 0) + n] += src[s0:s0 + n] * gain


def _fft_filter(x: np.ndarray, lo: float = 0, hi: float = SR / 2, slope: float = 1.5) -> np.ndarray:
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR) + 1e-6
    g = np.ones_like(f)
    if lo > 0:
        g *= 1 / (1 + (lo / f) ** (2 * slope))
    if hi < SR / 2:
        g *= 1 / (1 + (f / hi) ** (2 * slope))
    return np.fft.irfft(X * g, n=len(x)).astype(np.float32)


def _norm(x, peak=1.0):
    m = np.max(np.abs(x)) + 1e-9
    return (x / m * peak).astype(np.float32)


def _smooth_noise(n, rate_hz, rng):
    """Slowly varying random curve in [0,1]."""
    k = max(2, int(n / SR * rate_hz) + 2)
    pts = rng.random(k)
    return np.interp(np.linspace(0, k - 1, n), np.arange(k), pts).astype(np.float32)


# ---------------------------------------------------------------- voices
async def _edge(text, voice, rate, pitch, out):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(out)


def tts(text: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz", cache: Path | None = None) -> np.ndarray:
    key = hashlib.sha1(f"{voice}|{rate}|{pitch}|{text}".encode()).hexdigest()[:16]
    cache = cache or Path(tempfile.gettempdir())
    cache.mkdir(parents=True, exist_ok=True)
    mp3 = cache / f"tts_{key}.mp3"
    if mp3.exists() and mp3.stat().st_size < 1000:
        mp3.unlink()  # leftover from a failed attempt
    if not mp3.exists() and os.environ.get("TTS_OFFLINE") == "1":  # local testing without network
        return _espeak(text, pitch, cache / f"tts_{key}.wav")
    if not mp3.exists():
        err = None
        for attempt in range(4):
            try:
                asyncio.run(_edge(text, voice, rate, pitch, str(mp3)))
                if mp3.exists() and mp3.stat().st_size > 1000:
                    break
            except Exception as e:  # network hiccups are common; retry
                err = e
            if mp3.exists():
                mp3.unlink()
            time.sleep(1.5 * (attempt + 1))
        else:
            if os.environ.get("ALLOW_ESPEAK") == "1":
                return _espeak(text, pitch, cache / f"tts_{key}.wav")
            raise RuntimeError(f"edge-tts failed for voice {voice}: {err}")
    a = decode(mp3)
    # trim leading/trailing silence
    idx = np.where(np.abs(a) > 0.01)[0]
    if len(idx):
        a = a[max(0, idx[0] - 1200): idx[-1] + 2400]
    return a


def _espeak(text, pitch, wav):
    """Local-test fallback only (robotic). Never used in the daily run."""
    p = 50
    try:
        p = max(0, min(99, 50 + int(pitch.replace("Hz", "").replace("+", "")) // 2))
    except ValueError:
        pass
    subprocess.run(["espeak-ng", "-v", "en-us", "-s", "150", "-p", str(p), "-w", str(wav), text], check=True)
    return decode(wav) * 0.9


def voice_fx(a: np.ndarray, shift: float = 0.0, bright: bool = True) -> np.ndarray:
    """Make a voice sound more like a cartoon child.
    shift: semitones; raising pitch AND formants makes a voice sound smaller/younger (+), lowering makes it
    chubbier/goofier (-). bright: gentle presence lift + warmth so speech is clear on phone/TV speakers."""
    if len(a) == 0 or (not shift and not bright):
        return a
    chain = []
    if shift:
        f = 2 ** (float(shift) / 12)
        chain += [f"asetrate={int(SR * f)}", f"aresample={SR}", f"atempo={1 / f:.5f}"]
    if bright:
        chain += ["highpass=f=90", "equalizer=f=250:t=q:w=1:g=-2", "equalizer=f=3200:t=q:w=1.2:g=3",
                  "equalizer=f=9000:t=h:w=1:g=1.5", "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120"]
    out = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                          "-af", ",".join(chain), "-f", "f32le", "-ar", str(SR), "-ac", "1", "-"],
                         input=np.asarray(a, np.float32).tobytes(), capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def envelope(a: np.ndarray, fps: int) -> np.ndarray:
    """Per-video-frame loudness 0..1, used for lip-sync and music ducking."""
    hop = SR // fps
    n = len(a) // hop + 1
    pad = np.zeros(n * hop, dtype=np.float32)
    pad[:len(a)] = a
    rms = np.sqrt((pad.reshape(n, hop) ** 2).mean(axis=1))
    return rms / (np.percentile(rms, 95) + 1e-6)


# ---------------------------------------------------------------- music
NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}
PROGRESSIONS = [[0, 5, 3, 4], [0, 3, 4, 0], [0, 4, 5, 3], [5, 3, 0, 4], [0, 3, 5, 4]]
MAJOR = [0, 2, 4, 5, 7, 9, 11]


def _hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def _bell(freq, dur, decay=3.0, bright=0.35):
    t = np.arange(int(dur * SR)) / SR
    env = np.exp(-t * decay) * np.minimum(1, t * 400)
    w = np.sin(2 * np.pi * freq * t) + bright * np.sin(2 * np.pi * 2.01 * freq * t) * np.exp(-t * 6) \
        + 0.12 * np.sin(2 * np.pi * 3.98 * freq * t) * np.exp(-t * 9)
    return (w * env).astype(np.float32)


def music(duration: float, seed: int, mood: str = "gentle") -> np.ndarray:
    """Original procedural music-box + warm pad bed. Returns (n, 2)."""
    rng = np.random.default_rng(seed)
    bpm = {"gentle": 72, "playful": 96, "dreamy": 62, "adventurous": 88}.get(mood, 72)
    beat = 60 / bpm
    key = 60 + int(rng.integers(-3, 5))
    prog = PROGRESSIONS[int(rng.integers(len(PROGRESSIONS)))]
    n = int(duration * SR) + SR * 3
    L, R = np.zeros(n, np.float32), np.zeros(n, np.float32)
    bar = 4 * beat
    chord_len = 2 * bar
    t0, ci = 0.0, 0
    motif = [int(x) for x in rng.integers(0, 5, 8)]
    while t0 < duration + 2:
        deg = prog[ci % len(prog)]
        root = key + MAJOR[deg]
        tones = [root, key + MAJOR[(deg + 2) % 7] + (12 if (deg + 2) >= 7 else 0),
                 key + MAJOR[(deg + 4) % 7] + (12 if (deg + 4) >= 7 else 0)]
        # pad
        tt = np.arange(int((chord_len + 1.5) * SR)) / SR
        env = np.minimum(1, tt / 1.2) * np.minimum(1, np.maximum(0, (chord_len + 1.5 - tt) / 1.5))
        pad = np.zeros_like(tt)
        for m in tones:
            f = _hz(m - 12)
            pad += np.sin(2 * np.pi * f * tt) + 0.5 * np.sin(2 * np.pi * f * 1.003 * tt + 1)
        pad = _fft_filter((pad * env).astype(np.float32), hi=1400) * 0.05
        place(L, pad, t0)
        place(R, np.roll(pad, 300), t0)
        # bass
        place(L, _bell(_hz(root - 24), 2.5, decay=1.6, bright=0.1) * 0.10, t0)
        place(R, _bell(_hz(root - 24), 2.5, decay=1.6, bright=0.1) * 0.10, t0)
        place(L, _bell(_hz(root - 24), 2.0, decay=1.8, bright=0.1) * 0.07, t0 + bar)
        place(R, _bell(_hz(root - 24), 2.0, decay=1.8, bright=0.1) * 0.07, t0 + bar)
        # music-box melody (pentatonic around chord), varied motif
        scale = sorted(set([tones[0], tones[1], tones[2], tones[0] + 12, tones[1] + 12]))
        step = beat if mood in ("gentle", "dreamy") else beat / 2
        tt_ = t0
        k = 0
        while tt_ < t0 + chord_len - 0.01:
            if rng.random() < (0.72 if mood != "dreamy" else 0.5):
                idx = (motif[k % len(motif)] + (ci // 4)) % len(scale)
                note = scale[idx] + 12
                b = _bell(_hz(note), 1.8, decay=2.6) * (0.085 if k % 4 == 0 else 0.06)
                pan = 0.5 + 0.3 * np.sin(k * 1.7)
                place(L, b * (1 - pan) * 2, tt_)
                place(R, b * pan * 2, tt_)
            tt_ += step
            k += 1
        t0 += chord_len
        ci += 1
        if ci % 8 == 0:
            motif = [int(x) for x in rng.integers(0, 5, 8)]
    out = np.stack([L, R], axis=1)[:int(duration * SR)]
    # simple reverb: a few decaying echoes
    rev = out.copy()
    for d, g in [(0.031, 0.35), (0.047, 0.3), (0.073, 0.25), (0.11, 0.18), (0.17, 0.12)]:
        k = int(d * SR)
        rev[k:] += out[:-k] * g
    fade = int(3 * SR)
    rev[-fade:] *= np.linspace(1, 0, fade)[:, None]
    rev[:int(1.5 * SR)] *= np.linspace(0, 1, int(1.5 * SR))[:, None]
    return (rev / (np.max(np.abs(rev)) + 1e-9) * 0.8).astype(np.float32)


# ---------------------------------------------------------------- ambience
def ambience(kind: str, duration: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(duration * SR)
    if kind in (None, "", "none"):
        return np.zeros(n, np.float32)
    white = rng.standard_normal(n).astype(np.float32)
    brown = np.cumsum(white) / SR
    brown = _fft_filter(brown - np.mean(brown), lo=20)
    out = np.zeros(n, np.float32)

    def wind(level=0.5):
        w = _fft_filter(brown, hi=500) * (0.4 + 0.6 * _smooth_noise(n, 0.15, rng))
        return _norm(w, level)

    if kind == "wind":
        out += wind(0.7)
    elif kind == "birds":
        out += wind(0.18)
        t = rng.uniform(0.2, 1.5)
        while t < duration - 0.5:
            f0 = rng.uniform(2600, 4800)
            for c in range(int(rng.integers(2, 6))):
                d = rng.uniform(0.05, 0.14)
                tt = np.arange(int(d * SR)) / SR
                sweep = f0 * (1 + rng.uniform(-0.25, 0.35) * tt / d)
                ph = 2 * np.pi * np.cumsum(sweep) / SR
                ch = np.sin(ph) * np.sin(np.pi * tt / d) ** 2
                place(out, ch.astype(np.float32), t + c * rng.uniform(0.09, 0.18), rng.uniform(0.15, 0.4))
            t += rng.uniform(0.8, 3.5)
    elif kind == "night":
        out += wind(0.12)
        tt = np.arange(n) / SR
        for f, rate, g in [(4400, 28, 0.12), (5100, 34, 0.08)]:
            pulse = (np.sin(2 * np.pi * rate * tt) > 0.3).astype(np.float32)
            gate = (_smooth_noise(n, 0.7, rng) > 0.45).astype(np.float32)
            gate = _fft_filter(gate, hi=8)
            out += np.sin(2 * np.pi * f * tt).astype(np.float32) * pulse * np.clip(gate, 0, 1) * g
    elif kind == "rain":
        out += _norm(_fft_filter(white, lo=800, hi=7000), 0.35)
        for _ in range(int(duration * 25)):
            d = _bell(rng.uniform(1500, 4000), 0.04, decay=120, bright=0) * rng.uniform(0.05, 0.2)
            place(out, d, rng.uniform(0, duration))
    elif kind == "stream":
        s = _fft_filter(white, lo=300, hi=3000) * (0.5 + 0.5 * _smooth_noise(n, 9, rng))
        out += _norm(s, 0.45) + wind(0.08)
        for _ in range(int(duration * 3)):
            b = _bell(rng.uniform(500, 1400), 0.08, decay=50, bright=0.2) * 0.12
            place(out, b, rng.uniform(0, duration))
    elif kind == "waves":
        tt = np.arange(n) / SR
        swell = (0.5 + 0.5 * np.sin(2 * np.pi * tt / 7.5)) ** 2
        out += _norm(_fft_filter(white, lo=150, hi=2500) * swell, 0.55) + wind(0.1)
    elif kind == "fire":
        out += _norm(_fft_filter(brown, hi=200), 0.25)
        for _ in range(int(duration * 14)):
            c = (rng.standard_normal(int(0.006 * SR)) * np.exp(-np.arange(int(0.006 * SR)) / 60)).astype(np.float32)
            place(out, _fft_filter(c, lo=1500), rng.uniform(0, duration), rng.uniform(0.1, 0.5))
    elif kind == "indoor":
        out += _norm(_fft_filter(brown, hi=300), 0.08)
        tt = 0.5
        while tt < duration:  # soft clock tick
            place(out, _bell(2200, 0.03, decay=200, bright=0) * 0.06, tt)
            tt += 1.0
    elif kind == "city":
        out += _norm(_fft_filter(brown, hi=400), 0.3) + wind(0.1)
    else:
        out += wind(0.2)
    # fade edges for crossfading between scenes
    f = min(n // 4, int(0.8 * SR))
    if f > 0:
        out[:f] *= np.linspace(0, 1, f)
        out[-f:] *= np.linspace(1, 0, f)
    return _norm(out, 0.9) if np.any(out) else out


# ---------------------------------------------------------------- sound effects
def sfx(name: str, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if name == "chime":
        return _norm(sum(_bell(_hz(m), 2.5, decay=1.8) * g for m, g in [(84, 1), (88, 0.7), (91, 0.6)]), 0.8)
    if name == "twinkle":
        out = np.zeros(int(2.2 * SR), np.float32)
        for i, m in enumerate([84, 88, 91, 96, 100]):
            place(out, _bell(_hz(m), 1.5, decay=3), i * 0.09, 0.5)
        return _norm(out, 0.8)
    if name == "pop":
        t = np.arange(int(0.12 * SR)) / SR
        f = 900 * np.exp(-t * 25) + 300
        return _norm(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 35), 0.8)
    if name == "boing":
        t = np.arange(int(0.6 * SR)) / SR
        f = 180 + 220 * np.exp(-t * 6) + 25 * np.sin(2 * np.pi * 14 * t)
        return _norm(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4), 0.8)
    if name == "whoosh":
        n = int(0.9 * SR)
        w = rng.standard_normal(n).astype(np.float32)
        env = np.sin(np.linspace(0, np.pi, n)) ** 2
        return _norm(_fft_filter(w, lo=400, hi=3000) * env, 0.6)
    if name == "splash":
        n = int(0.8 * SR)
        w = rng.standard_normal(n).astype(np.float32) * np.exp(-np.arange(n) / (0.18 * SR))
        out = _fft_filter(w, lo=500, hi=6000)
        for _ in range(8):
            place(out, _bell(rng.uniform(600, 1500), 0.1, decay=40, bright=0.3) * 0.3, rng.uniform(0.05, 0.5))
        return _norm(out, 0.8)
    if name == "knock":
        out = np.zeros(int(0.9 * SR), np.float32)
        for i in range(3):
            k = _fft_filter(rng.standard_normal(int(0.05 * SR)).astype(np.float32), hi=900)
            k *= np.exp(-np.arange(len(k)) / 300)
            place(out, k, i * 0.22)
        return _norm(out, 0.9)
    if name == "steps":
        out = np.zeros(int(2.0 * SR), np.float32)
        for i in range(5):
            k = _fft_filter(rng.standard_normal(int(0.08 * SR)).astype(np.float32), lo=60, hi=600)
            k *= np.exp(-np.arange(len(k)) / 600)
            place(out, k, i * 0.38, 0.8 if i % 2 else 1.0)
        return _norm(out, 0.7)
    if name == "honk":  # elephant trunk toot
        t = np.arange(int(0.7 * SR)) / SR
        f = 330 + 90 * np.minimum(1, t / 0.08) + 12 * np.sin(2 * np.pi * 7 * t)
        ph = 2 * np.pi * np.cumsum(f) / SR
        w = np.sign(np.sin(ph)) * 0.5 + np.sin(2 * ph) * 0.3 + np.sin(3 * ph) * 0.2
        env = np.minimum(1, t / 0.03) * np.minimum(1, (0.7 - t) / 0.2)
        return _norm(_fft_filter((w * env).astype(np.float32), lo=200, hi=3500), 0.8)
    if name in ("slide_up", "slide_down"):  # slide whistle
        t = np.arange(int(0.8 * SR)) / SR
        a, b = (500, 1700) if name == "slide_up" else (1700, 450)
        f = a + (b - a) * (t / t[-1]) ** 0.8 + 18 * np.sin(2 * np.pi * 6 * t)
        env = np.minimum(1, t / 0.04) * np.minimum(1, (t[-1] - t) / 0.08)
        return _norm(np.sin(2 * np.pi * np.cumsum(f) / SR) * env, 0.7)
    if name == "ding":  # correct answer
        return _norm(_bell(_hz(88), 1.6, decay=2.2) + 0.6 * _bell(_hz(95), 1.6, decay=2.4), 0.8)
    if name == "tada":
        out = np.zeros(int(2.0 * SR), np.float32)
        for i, chord in enumerate([[72, 76, 79], [76, 79, 84, 88]]):
            for m in chord:
                place(out, _bell(_hz(m), 1.6, decay=2.0 if i else 6.0, bright=0.5), i * 0.16, 0.35)
        return _norm(out, 0.85)
    if name == "drumroll":
        n = int(1.6 * SR)
        out = np.zeros(n, np.float32)
        t = 0.0
        while t < 1.45:
            k = rng.standard_normal(int(0.03 * SR)).astype(np.float32) * np.exp(-np.arange(int(0.03 * SR)) / 250)
            place(out, _fft_filter(k, lo=150, hi=4000), t, 0.4 + 0.6 * t / 1.45)
            t += 0.045
        place(out, _fft_filter(rng.standard_normal(int(0.4 * SR)).astype(np.float32) * np.exp(-np.arange(int(0.4 * SR)) / 4000), lo=2000), 1.45, 0.6)
        return _norm(out, 0.8)
    if name == "bonk":
        t = np.arange(int(0.35 * SR)) / SR
        f = 260 * np.exp(-t * 4) + 120
        return _norm(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 12) + 0.3 * _fft_filter(rng.standard_normal(len(t)).astype(np.float32) * np.exp(-t * 60), hi=1500), 0.9)
    if name == "zip":
        t = np.arange(int(0.35 * SR)) / SR
        f = 400 + 2600 * (t / t[-1]) ** 2
        return _norm(_fft_filter((np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / t[-1]) +
                                  0.4 * rng.standard_normal(len(t))).astype(np.float32), lo=600, hi=6000), 0.6)
    if name == "jingle":  # channel intro sting
        out = np.zeros(int(3.2 * SR), np.float32)
        notes = [(72, 0.0), (76, 0.14), (79, 0.28), (84, 0.42), (81, 0.62), (84, 0.76), (88, 0.95)]
        for m, at in notes:
            place(out, _bell(_hz(m), 1.4, decay=3.0, bright=0.5), at, 0.45)
            place(out, _bell(_hz(m - 12), 1.0, decay=4.0, bright=0.2), at, 0.2)
        for m in (72, 76, 79, 84):
            place(out, _bell(_hz(m), 2.2, decay=1.6, bright=0.4), 0.95, 0.22)
        place(out, sfx("twinkle", seed) * 0.5, 1.15)
        return _norm(out, 0.85)
    raise ValueError(f"unknown sfx '{name}'")


SFX_NAMES = ["chime", "twinkle", "pop", "boing", "whoosh", "splash", "knock", "steps",
             "honk", "slide_up", "slide_down", "ding", "tada", "drumroll", "bonk", "zip", "jingle"]
AMBIENCE_NAMES = ["none", "wind", "birds", "night", "rain", "stream", "waves", "fire", "indoor", "city"]
