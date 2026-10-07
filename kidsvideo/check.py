"""Validate an episode and render a preview contact sheet (no audio, no network).

    python -m kidsvideo.check episodes/2026-10-07
"""
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from . import ROOT, rig, sound, svgtools
from .render import SceneRenderer, font, load_config, make_thumbnail

CAMERAS = {"pan_left", "pan_right", "push_in", "pull_out", "drift", "still"}
TODS = set(rig.TINTS)
PARTICLES = {"none", "fireflies", "sparkles", "leaves", "snow", "rain", "bubbles", "dust", "petals"}
TRANSITIONS = {"fade", "fadeblack", "smoothleft", "smoothright", "circleopen", "dissolve", "wipeleft"}
ACTIONS = {"idle", "bounce", "hop", "walk", "sleep", "shake", "wobble", "dance"}
SHAPES = {"none", "circle", "square", "rectangle", "triangle", "star", "heart", "diamond"}
PARTS = ["body", "head", "eyes_open", "eyes_closed", "mouth_closed", "mouth_open"]


def validate(story: dict) -> list[str]:
    errs = []
    for k in ("title", "moral", "description", "tags", "scenes"):
        if not story.get(k):
            errs.append(f"missing '{k}'")
    if len(story.get("title", "")) > 90:
        errs.append("title longer than 90 characters")
    extra = story.get("new_characters") or {}
    for cid, ch in extra.items():
        for p in PARTS:
            if p not in ch.get("parts", {}):
                errs.append(f"new character {cid} missing part {p}")
    known = {p.stem for p in (ROOT / "characters").glob("*.json")} | set(extra)
    words = 0
    for i, sc in enumerate(story.get("scenes", [])):
        tag = f"scene {i + 1}"
        if not sc.get("layers", {}).get("sky"):
            errs.append(f"{tag}: layers.sky is required")
        for name, svg in sc.get("layers", {}).items():
            if name not in ("sky", "mid", "fore"):
                errs.append(f"{tag}: unknown layer '{name}'")
            _, warns = svgtools.sanitize(svg)
            for w in warns:
                errs.append(f"{tag}.{name}: {w} (not allowed)")
            if re.search(r"<text\b", svg):
                errs.append(f"{tag}.{name}: <text> in artwork is not allowed (captions are added automatically)")
            try:
                svgtools.render(svg, 192, 108)
            except Exception as e:
                errs.append(f"{tag}.{name}: SVG does not render: {e}")
        if sc.get("camera", "pan_right") not in CAMERAS:
            errs.append(f"{tag}: camera must be one of {sorted(CAMERAS)}")
        if sc.get("time_of_day", "day") not in TODS:
            errs.append(f"{tag}: time_of_day must be one of {sorted(TODS)}")
        if sc.get("particles", "none") not in PARTICLES:
            errs.append(f"{tag}: particles must be one of {sorted(PARTICLES)}")
        if sc.get("ambience", "none") not in sound.AMBIENCE_NAMES:
            errs.append(f"{tag}: ambience must be one of {sound.AMBIENCE_NAMES}")
        if sc.get("transition", "fade") not in TRANSITIONS:
            errs.append(f"{tag}: transition must be one of {sorted(TRANSITIONS)}")
        for ev in sc.get("sfx", []):
            if ev.get("name") not in sound.SFX_NAMES:
                errs.append(f"{tag}: sfx '{ev.get('name')}' must be one of {sound.SFX_NAMES}")
        for pl in sc.get("characters", []):
            if pl.get("id") not in known:
                errs.append(f"{tag}: unknown character '{pl.get('id')}'")
            if pl.get("action", "idle") not in ACTIONS:
                errs.append(f"{tag}: action '{pl.get('action')}' must be one of {sorted(ACTIONS)}")
        for pp in sc.get("popups", []):
            if not (pp.get("text") or pp.get("count") or pp.get("shape", "none") != "none"):
                errs.append(f"{tag}: popup needs text, count or shape")
            if pp.get("shape", "none") not in SHAPES:
                errs.append(f"{tag}: popup shape must be one of {sorted(SHAPES)}")
            if len(str(pp.get("text", ""))) > 14:
                errs.append(f"{tag}: popup text '{pp.get('text')}' is too long (max 14 chars; put more in 'sub')")
            if len(str(pp.get("sub", ""))) > 34:
                errs.append(f"{tag}: popup sub '{pp.get('sub')}' is too long (max 34 chars)")
            if int(pp.get("count", 0) or 0) > 10:
                errs.append(f"{tag}: popup count max is 10")
            if pp.get("sound") and pp["sound"] not in sound.SFX_NAMES:
                errs.append(f"{tag}: popup sound must be one of {sound.SFX_NAMES}")
        if not sc.get("narration"):
            errs.append(f"{tag}: needs narration lines")
        for ln in sc.get("narration", []):
            words += len(ln.get("text", "").split())
            if ln.get("speaker") and ln["speaker"] not in known:
                errs.append(f"{tag}: unknown speaker '{ln['speaker']}'")
            if ln.get("speaker") and ln["speaker"] not in {p.get("id") for p in sc.get("characters", [])}:
                errs.append(f"{tag}: speaker '{ln['speaker']}' talks but is not placed in the scene")
    if not story.get("learning"):
        errs.append("missing 'learning' (what the episode teaches, e.g. 'counting to 5')")
    if not any(sc.get("popups") for sc in story.get("scenes", [])):
        errs.append("no learning popups: add 'popups' to at least 2 scenes")
    if words < 250:
        errs.append(f"story is short ({words} words); aim for 380-600 words (~3-4 minutes)")
    return errs


def contact_sheet(story: dict, out: Path):
    extra = story.get("new_characters") or {}
    ids = {pl["id"] for sc in story["scenes"] for pl in sc.get("characters", [])}
    chars = {c: rig.load_character(c, extra) for c in ids}
    W, H = 960, 540
    n = len(story["scenes"])
    cols = 2
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * W + (cols + 1) * 12, rows * (H + 50) + 12), (30, 30, 36))
    d = ImageDraw.Draw(sheet)
    f = font(28, "SemiBold")
    for i, sc in enumerate(story["scenes"]):
        pops = [dict(sc["popups"][0], _t0=0.0, _t1=99.0)] if sc.get("popups") else []
        r = SceneRenderer(sc, chars, W, H, 24, 12, {}, {}, i, camera_override="still", popups=pops)
        img = r.frame(36).convert("RGB")
        x, y = 12 + (i % cols) * (W + 12), 12 + (i // cols) * (H + 50)
        sheet.paste(img, (x, y))
        cast = ", ".join(pl["id"] for pl in sc.get("characters", []))
        d.text((x + 6, y + H + 8), f"Scene {i + 1} · {sc.get('time_of_day', 'day')} · {cast}", font=f, fill=(230, 230, 230))
    sheet.save(out, quality=88)


def main():
    ep = Path(sys.argv[1])
    story = json.loads((ep / "story.json").read_text())
    errs = validate(story)
    if errs:
        print("PROBLEMS:")
        for e in errs:
            print(" -", e)
    else:
        print("story.json is valid")
    contact_sheet(story, ep / "preview.jpg")
    make_thumbnail(story, {c: rig.load_character(c, story.get("new_characters") or {})
                           for c in {pl["id"] for sc in story["scenes"] for pl in sc.get("characters", [])}},
                   load_config(), ep / "thumbnail.jpg")
    print(f"preview: {ep / 'preview.jpg'}\nthumbnail: {ep / 'thumbnail.jpg'}")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
