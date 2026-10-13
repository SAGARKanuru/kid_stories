"""Quick health check of both voice engines; prints GitHub annotations so results show on the run page.

    python tools/tts_check.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kidsvideo import ROOT, sound  # noqa: E402
from kidsvideo.render import load_config  # noqa: E402

out = ROOT / "voice-samples"
out.mkdir(exist_ok=True)
v = load_config()["voice"]
narr = {"name": v["narrator"], "rate": v["rate"], "pitch": v["pitch"], "shift": v.get("shift", 0), "backup": v.get("backup")}
voices = [("narrator", narr)] + [(c.stem, json.loads(c.read_text())["voice"]) for c in sorted((ROOT / "characters").glob("*.json"))]
line = "Hi friends! Guess what? Today we're going on a super fun adventure. Are you ready? Let's go!"
ok_any = False
for mode in ("edge", "kokoro"):
    for name, spec in voices:
        t = time.time()
        try:
            a = sound.speak(line, spec, out / ".cache", mode)
            sound.write_wav(out / f"{mode}-{name}.wav", a)
            print(f"::notice::{mode} {name}: OK ({len(a) / sound.SR:.1f}s audio in {time.time() - t:.1f}s)")
            ok_any = True
        except Exception as e:
            print(f"::warning::{mode} {name}: FAILED {type(e).__name__}: {str(e)[:300]}")
sys.exit(0 if ok_any else 1)
