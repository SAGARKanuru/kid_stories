"""Make short MP3 samples of the narrator, each character and other kid-friendly voices.

    python tools/voice_samples.py            # writes voice-samples/*.mp3
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kidsvideo import ROOT, sound  # noqa: E402
from kidsvideo.render import load_config  # noqa: E402

OUT = ROOT / "voice-samples"
LINE = "Hi friends! Guess what? Today we're going on a super fun adventure. Are you ready? Let's go!"
EXTRA = [  # other narrator options to compare: (voice, rate, shift in semitones)
    ("en-US-AnaNeural", "-6%", 0), ("en-US-AnaNeural", "-6%", 2),
    ("en-GB-MaisieNeural", "-6%", 0), ("en-GB-MaisieNeural", "-6%", 1.5),
    ("en-IN-NeerjaNeural", "-6%", 3), ("en-US-JennyNeural", "-4%", 3.5),
]


def save(name, text, voice, rate, pitch, shift=0.0):
    a = sound.voice_fx(sound.tts(text, voice, rate, pitch, OUT / ".cache"), shift)
    wav = OUT / f"{name}.wav"
    sound.write_wav(wav, a)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "128k", str(OUT / f"{name}.mp3")], check=True)
    wav.unlink()
    print("wrote", f"{name}.mp3", f"({voice} rate {rate} shift {shift})")


def main():
    OUT.mkdir(exist_ok=True)
    v = load_config()["voice"]
    save("01-narrator", LINE, v["narrator"], v["rate"], v["pitch"], float(v.get("shift", 0)))
    for f in sorted((ROOT / "characters").glob("*.json")):
        c = json.loads(f.read_text())
        cv = c["voice"]
        save(f"02-{c['id']}", f"Hi! I'm {c['name']}! " + LINE.split("! ", 1)[1], cv["name"], cv.get("rate", "+0%"),
             cv.get("pitch", "+0Hz"), float(cv.get("shift", 0)))
    for i, (voice, rate, shift) in enumerate(EXTRA):
        save(f"03-narrator-option-{i + 1}-{voice.split('-')[2].replace('Neural', '')}-shift{shift}", LINE, voice, rate,
             "+0Hz", shift)


if __name__ == "__main__":
    main()
