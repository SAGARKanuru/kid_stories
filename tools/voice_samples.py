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
EXTRA = [  # other voices worth trying, with kid-like settings
    ("en-US-AnaNeural", "+0%", "+4Hz"), ("en-GB-MaisieNeural", "+0%", "+8Hz"),
    ("en-US-AnaNeural", "+8%", "+14Hz"), ("en-IN-NeerjaNeural", "-4%", "+10Hz"),
    ("en-US-JennyNeural", "+0%", "+16Hz"), ("en-AU-NatashaNeural", "+0%", "+12Hz"),
]


def save(name, text, voice, rate, pitch):
    a = sound.tts(text, voice, rate, pitch, OUT / ".cache")
    wav = OUT / f"{name}.wav"
    sound.write_wav(wav, a)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "128k", str(OUT / f"{name}.mp3")], check=True)
    wav.unlink()
    print("wrote", f"{name}.mp3", f"({voice} rate {rate} pitch {pitch})")


def main():
    OUT.mkdir(exist_ok=True)
    v = load_config()["voice"]
    save("01-narrator", LINE, v["narrator"], v["rate"], v["pitch"])
    for f in sorted((ROOT / "characters").glob("*.json")):
        c = json.loads(f.read_text())
        cv = c["voice"]
        save(f"02-{c['id']}", f"Hi! I'm {c['name']}! " + LINE.split("! ", 1)[1], cv["name"], cv.get("rate", "+0%"),
             cv.get("pitch", "+0Hz"))
    for i, (voice, rate, pitch) in enumerate(EXTRA):
        save(f"03-option-{i + 1}-{voice.split('-')[2]}-{pitch.replace('+', 'p')}", LINE, voice, rate, pitch)


if __name__ == "__main__":
    main()
