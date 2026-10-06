"""Turn an episode (story.json) into a finished, narrated, animated 1080p video."""
import hashlib
import json
import math
import os
import random
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import ROOT, rig, sound, svgtools

FONT = str(ROOT / "assets" / "fonts" / "Fredoka.ttf")
OVERSCAN = {"sky": 1.05, "mid": 1.12, "fore": 1.22}
PARALLAX = {"sky": 0.35, "mid": 1.0, "fore": 1.0}
BLUR = {"sky": 1.2, "mid": 0, "fore": 3.5}
XFADE = 0.6


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def font(size, weight="Bold"):
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def ease(p):  # smoothstep
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


# ====================================================================== text overlays
def text_block(text, max_w, size, fill=(255, 255, 255), stroke=(52, 30, 90), weight="Bold", align="center"):
    f = font(size, weight)
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if f.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    sw = max(3, size // 12)
    lh = int(size * 1.12)
    W = int(max(f.getlength(line) for line in lines) + sw * 2 + 30)
    H = lh * len(lines) + sw * 2 + 30
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(img), ImageDraw.Draw(shadow)
    for i, line in enumerate(lines):
        lw = f.getlength(line)
        x = (W - lw) / 2 if align == "center" else sw + 10
        y = 10 + i * lh
        ds.text((x + size * 0.05, y + size * 0.07), line, font=f, fill=(0, 0, 0, 120), stroke_width=sw,
                stroke_fill=(0, 0, 0, 120))
        d.text((x, y), line, font=f, fill=fill, stroke_width=sw, stroke_fill=stroke)
    shadow = shadow.filter(ImageFilter.GaussianBlur(size / 14))
    shadow.alpha_composite(img)
    return shadow


def caption_image(text, W, talk=False):
    s = W / 1920
    f = font(int(54 * s), "SemiBold")
    max_w = 1500 * s
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if f.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    lh = int(66 * s)
    tw = max(f.getlength(l) for l in lines)
    pad_x, pad_y = int(34 * s), int(14 * s)
    Wc, Hc = int(tw + 2 * pad_x), int(lh * len(lines) + 2 * pad_y)
    img = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, Wc - 1, Hc - 1), radius=int(26 * s), fill=(24, 14, 46, 120))
    col = (255, 232, 140) if talk else (255, 255, 255)
    for i, l in enumerate(lines):
        x = (Wc - f.getlength(l)) / 2
        d.text((x, pad_y + i * lh), l, font=f, fill=col, stroke_width=max(2, int(3 * s)), stroke_fill=(40, 22, 70))
    return img


# ====================================================================== particles
class Particles:
    def __init__(self, kind, W, H, seed):
        self.kind, self.W, self.H = kind, W, H
        rnd = random.Random(seed)
        count = {"fireflies": 28, "sparkles": 26, "leaves": 16, "snow": 90, "rain": 160, "bubbles": 22,
                 "dust": 45, "petals": 20}.get(kind, 0)
        self.p = [(rnd.random(), rnd.random(), rnd.random(), rnd.uniform(0.6, 1.4)) for _ in range(count)]
        self.k = W / 1920
        self.glows = []
        if kind == "fireflies":
            r = int(34 * self.k) + 2
            yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
            dist = np.sqrt(xx ** 2 + yy ** 2) / r
            for level in range(8):
                g = (level + 1) / 8
                a = np.clip(np.exp(-dist ** 2 * 7) * 210 * g + np.exp(-dist ** 2 * 120) * 255 * g, 0, 255)
                arr = np.zeros((2 * r + 1, 2 * r + 1, 4), np.uint8)
                arr[..., 0], arr[..., 1], arr[..., 2] = 255, 244, 150
                arr[..., 3] = a.astype(np.uint8)
                self.glows.append(Image.fromarray(arr, "RGBA"))

    def draw(self, img, t):
        if not self.p:
            return
        d = ImageDraw.Draw(img, "RGBA")
        W, H, k = self.W, self.H, self.kind
        for (a, b, c, s) in self.p:
            if k == "fireflies":
                x = (a * W + 60 * self.k * math.sin(t * 0.5 * s + c * 9)) % W
                y = H * (0.25 + 0.6 * b) + 40 * self.k * math.sin(t * 0.7 * s + a * 7)
                glow = 0.5 + 0.5 * math.sin(t * 2.2 * s + c * 20)
                g = self.glows[min(7, int(glow * 8))]
                img.alpha_composite(g, (int(x - g.width / 2), int(y - g.height / 2))) if 0 < x - g.width / 2 < W - g.width and 0 < y - g.height / 2 < H - g.height else None
                continue
            elif k == "sparkles":
                x, y = a * W, b * H * 0.85
                tw = max(0.0, math.sin(t * 2.5 * s + c * 30))
                r = 14 * s * tw * self.k
                if r > 1:
                    col = (255, 250, 210, int(220 * tw))
                    d.polygon([(x, y - r), (x + r * 0.25, y - r * 0.25), (x + r, y), (x + r * 0.25, y + r * 0.25),
                               (x, y + r), (x - r * 0.25, y + r * 0.25), (x - r, y), (x - r * 0.25, y - r * 0.25)], fill=col)
            elif k in ("leaves", "petals"):
                y = ((b + t * 0.06 * s) % 1.1 - 0.05) * H
                x = (a * W + 80 * math.sin(t * 0.9 * s + c * 6) + t * 25 * s) % W
                ang = t * 1.5 * s + c * 6
                L, Wd = 22 * s * self.k, 11 * s * self.k
                dx, dy = math.cos(ang) * L, math.sin(ang) * L * 0.6
                col = (226, 128, 54, 230) if k == "leaves" and c < 0.5 else (240, 180, 60, 230) if k == "leaves" else (255, 182, 203, 235)
                d.polygon([(x - dx, y - dy), (x - dy * 0.4 + Wd * 0.2, y + dx * 0.4), (x + dx, y + dy),
                           (x + dy * 0.4 - Wd * 0.2, y - dx * 0.4)], fill=col)
            elif k == "snow":
                y = ((b + t * 0.05 * s) % 1.05) * H
                x = (a * W + 30 * math.sin(t * 0.8 * s + c * 6)) % W
                r = 5 * s * self.k
                d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 210))
            elif k == "rain":
                y = ((b + t * 1.1 * s) % 1.1 - 0.05) * H
                x = (a * W + y * 0.18) % W
                d.line((x, y, x - 7, y + 38 * s), fill=(200, 220, 255, 110), width=2)
            elif k == "bubbles":
                y = H - ((b + t * 0.05 * s) % 1.1) * H
                x = a * W + 25 * math.sin(t * 1.2 * s + c * 5)
                r = 16 * s * self.k
                d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255, 170), width=3)
                d.ellipse((x - r * 0.5, y - r * 0.6, x - r * 0.15, y - r * 0.25), fill=(255, 255, 255, 170))
            elif k == "dust":
                x = (a * W + t * 8 * s + 20 * math.sin(t * 0.3 + c * 9)) % W
                y = (b * H * 0.8 + 15 * math.sin(t * 0.4 * s + a * 8))
                al = int(90 * (0.5 + 0.5 * math.sin(t * 1.3 * s + c * 11)))
                r = 2.5 * s * self.k
                d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 250, 225, al))


# ====================================================================== scene renderer
def grade_overlay(W, H, tod):
    """Vignette + time-of-day light."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    vig = np.clip((r - 0.75) / 0.75, 0, 1) ** 1.6
    a = np.zeros((H, W, 4), np.float32)
    a[..., 0:3] = (20, 10, 35)
    a[..., 3] = vig * (150 if tod == "night" else 105)
    over = Image.fromarray(a.astype(np.uint8), "RGBA")
    if tod in ("sunset", "morning", "day", "indoor"):
        col = {"sunset": (255, 140, 60, 45), "morning": (255, 225, 170, 26), "day": (255, 240, 200, 14),
               "indoor": (255, 200, 140, 22)}[tod]
        g = np.zeros((H, W, 4), np.float32)
        g[..., 0:3] = col[:3]
        g[..., 3] = col[3] * np.clip(1.1 - yy / H, 0, 1)
        over.alpha_composite(Image.fromarray(g.astype(np.uint8), "RGBA"))
    elif tod == "night":
        g = np.zeros((H, W, 4), np.uint8)
        g[..., 0:3] = (25, 35, 90)
        g[..., 3] = 38
        over.alpha_composite(Image.fromarray(g, "RGBA"))
    return over


class SceneRenderer:
    def __init__(self, scene: dict, characters: dict, W: int, H: int, fps: int, dur: float,
                 mouths: dict, talk: dict, seed: int, overlay: Image.Image | None = None, overlay_pop=False,
                 camera_override: str | None = None, captions=None):
        self.W, self.H, self.fps, self.dur = W, H, fps, dur
        self.captions = captions or []
        self._cap_cache = {}
        self.scene = scene
        self.tod = scene.get("time_of_day", "day")
        sx, sy = W / 1920, H / 1080
        self.layers = {}
        for name in ("sky", "mid", "fore"):
            svg = scene.get("layers", {}).get(name)
            if not svg:
                continue
            os_ = OVERSCAN[name]
            lw, lh = int(W * os_), int(H * os_)
            img = svgtools.render(svg, lw, lh, 1920, 1080)
            if BLUR[name]:
                img = img.filter(ImageFilter.GaussianBlur(BLUR[name] * W / 1920))
            if name == "sky":
                bg = Image.new("RGBA", img.size, (135, 190, 235, 255))
                bg.alpha_composite(img)
                img = bg
            self.layers[name] = img
        if "sky" not in self.layers:
            self.layers["sky"] = Image.new("RGBA", (int(W * 1.05), int(H * 1.05)), (135, 190, 235, 255))

        self.camera = camera_override or scene.get("camera", "pan_right")
        mid_os = OVERSCAN["mid"]
        self.sprites = []
        for i, pl in enumerate(scene.get("characters", [])):
            ch = characters[pl["id"]]
            facing = pl.get("facing", "right")
            if pl.get("action") == "walk" and "to_x" in pl:
                facing = "right" if pl["to_x"] > pl["x"] else "left"
            h = int(pl.get("height", 420) * sy * mid_os)
            spr = rig.Sprite(ch, h, facing, self.tod, seed=seed + i * 101)
            self.sprites.append((pl, spr))
        # draw back-to-front by feet y
        self.sprites.sort(key=lambda s: s[0].get("y", 900))
        self.mouths, self.talk = mouths, talk
        self.particles = Particles(scene.get("particles", "none"), W, H, seed)
        self.grade = grade_overlay(W, H, self.tod)
        self.overlay, self.overlay_pop = overlay, overlay_pop
        self.sx, self.sy = sx * mid_os, sy * mid_os

    def _offset(self, name, u, v):
        img = self.layers[name]
        slack_x, slack_y = (img.width - self.W) / 2, (img.height - self.H) / 2
        a = PARALLAX[name]
        return int(round(slack_x - u * a * slack_x)), int(round(slack_y - v * a * slack_y))

    def frame(self, i: int) -> Image.Image:
        t = i / self.fps
        p = ease(t / max(0.01, self.dur))
        cam = self.camera
        u = v = 0.0
        zoom = 1.0
        if cam == "pan_right":
            u = -0.85 + 1.7 * p
        elif cam == "pan_left":
            u = 0.85 - 1.7 * p
        elif cam == "push_in":
            zoom = 1.0 + 0.07 * p
        elif cam == "pull_out":
            zoom = 1.07 - 0.07 * p
        elif cam == "drift":
            u = 0.5 * math.sin(2 * math.pi * t / max(8.0, self.dur * 1.4))
            v = 0.3 * math.sin(2 * math.pi * t / 11.0)
        # gentle handheld breathing on every shot
        v += 0.12 * math.sin(2 * math.pi * t / 6.7)

        ox, oy = self._offset("sky", u, v)
        fr = self.layers["sky"].crop((ox, oy, ox + self.W, oy + self.H))
        mo = (0, 0)
        if "mid" in self.layers:
            mo = self._offset("mid", u, v)
            fr.alpha_composite(self.layers["mid"], (0, 0), (mo[0], mo[1], mo[0] + self.W, mo[1] + self.H))
        else:
            mid = Image.new("RGBA", (1, 1))
            mo = (int(self.W * (OVERSCAN["mid"] - 1) / 2), int(self.H * (OVERSCAN["mid"] - 1) / 2))
        for pl, spr in self.sprites:
            x, y = pl["x"], pl.get("y", 900)
            action = pl.get("action", "idle")
            if action == "walk" and "to_x" in pl:
                speed = 0.55 * pl.get("height", 420)
                t0 = pl.get("start", 0.6)
                t1 = t0 + abs(pl["to_x"] - pl["x"]) / speed
                q = min(1.0, max(0.0, (t - t0) / (t1 - t0)))
                x = pl["x"] + (pl["to_x"] - pl["x"]) * q
                if q <= 0 or q >= 1:
                    action = "idle"
            cid = pl["id"]
            mouth = bool(self.mouths.get(cid) is not None and i < len(self.mouths[cid]) and self.mouths[cid][i])
            talking = float(self.talk[cid][i]) if cid in self.talk and i < len(self.talk[cid]) else 0.0
            spr.draw(fr, t, x * self.sx, y * self.sy, action, talking, mouth, offset=(-mo[0], -mo[1]))
        if "fore" in self.layers:
            fo = self._offset("fore", u * 1.6, v)
            fo = (max(0, min(fo[0], self.layers["fore"].width - self.W)), max(0, min(fo[1], self.layers["fore"].height - self.H)))
            fr.alpha_composite(self.layers["fore"], (0, 0), (fo[0], fo[1], fo[0] + self.W, fo[1] + self.H))
        self.particles.draw(fr, t)
        if zoom != 1.0:
            cw, chh = self.W / zoom, self.H / zoom
            x0, y0 = (self.W - cw) / 2, (self.H - chh) * 0.45
            fr = fr.transform((self.W, self.H), Image.EXTENT, (x0, y0, x0 + cw, y0 + chh), Image.BILINEAR)
        fr.alpha_composite(self.grade)
        if self.overlay is not None:
            ov = self.overlay
            k = 1.0
            if self.overlay_pop:
                q = min(1.0, t / 0.7)
                k = 1 + 2.2 * (q - 1) ** 3 + 1.2 * (q - 1) ** 2 if q < 1 else 1.0  # ease-out-back
                k = max(0.05, k)
                if k != 1.0:
                    ov = ov.resize((max(1, int(ov.width * k)), max(1, int(ov.height * k))), Image.BILINEAR)
            fr.alpha_composite(ov, ((self.W - ov.width) // 2, (self.H - ov.height) // 2))
        for k, (c0, c1, text, talk) in enumerate(self.captions):
            if c0 <= t < c1:
                if k not in self._cap_cache:
                    self._cap_cache[k] = caption_image(text, self.W, talk)
                ci = self._cap_cache[k]
                fr.alpha_composite(ci, ((self.W - ci.width) // 2, self.H - ci.height - int(46 * self.H / 1080)))
                break
        return fr


def _render_segment(job):
    """Worker: render one segment to an mp4 (video only)."""
    (scene, characters, W, H, fps, dur, mouths, talk, seed, out, overlay_spec, cam, caps) = job
    overlay, pop = None, False
    if overlay_spec:
        overlay, pop = _build_overlay(overlay_spec, W, H), overlay_spec.get("pop", False)
    r = SceneRenderer(scene, characters, W, H, fps, dur, mouths, talk, seed, overlay, pop, cam, caps)
    n = int(round(dur * fps))
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                             "-crf", "16", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    for i in range(n):
        proc.stdin.write(r.frame(i).convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {out}")
    return str(out)


def _build_overlay(spec, W, H):
    s = W / 1920
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # soft dark band behind the text
    band = np.zeros((H, W, 4), np.uint8)
    yy = np.arange(H)[:, None]
    band[..., 3] = (np.clip(1 - np.abs(yy - H * 0.47) / (H * 0.36), 0, 1) ** 1.5 * 120).astype(np.uint8)
    canvas.alpha_composite(Image.fromarray(band, "RGBA"))
    y = int(H * 0.47)
    blocks = []
    if spec.get("kicker"):
        blocks.append(text_block(spec["kicker"], 1400 * s, int(54 * s), fill=(255, 226, 140), weight="SemiBold"))
    blocks.append(text_block(spec["title"], 1500 * s, int(124 * s)))
    if spec.get("sub"):
        blocks.append(text_block(spec["sub"], 1400 * s, int(56 * s), weight="Medium"))
    total = sum(b.height for b in blocks)
    y -= total // 2
    for b in blocks:
        canvas.alpha_composite(b, ((W - b.width) // 2, y))
        y += b.height
    return canvas


# ====================================================================== timeline / audio
def build_timeline(story, cfg, characters, cache):
    vcfg = cfg["voice"]
    fps = cfg["video"]["fps"]

    def voice_for(speaker):
        if speaker and speaker in characters and characters[speaker].get("voice"):
            v = characters[speaker]["voice"]
            return v["name"], v.get("rate", vcfg["rate"]), v.get("pitch", "+0Hz")
        return vcfg["narrator"], vcfg["rate"], vcfg["pitch"]

    segs = []
    title_idx = story.get("title_scene", 0)
    intro_line = {"text": f"{cfg['channel_name']} presents... {story['title']}.", "speaker": None}
    segs.append({"kind": "intro", "scene": story["scenes"][title_idx], "lines": [intro_line], "lead": 1.4, "tail": 1.6,
                 "min": 5.5, "sfx": [{"at": 0.25, "name": "twinkle"}]})
    for sc in story["scenes"]:
        segs.append({"kind": "scene", "scene": sc, "lines": sc["narration"], "lead": 0.8, "tail": 1.1, "min": 4.0,
                     "sfx": sc.get("sfx", [])})
    outro_text = f"The End. And remember: {story['moral']}"
    segs.append({"kind": "outro", "scene": story["scenes"][story.get("outro_scene", -1)],
                 "lines": [{"text": outro_text, "speaker": None}], "lead": 1.2, "tail": 3.5, "min": 8.0,
                 "sfx": [{"at": 0.3, "name": "chime"}]})

    t = 0.0
    for seg in segs:
        cur = seg["lead"]
        prev = "__start__"
        for ln in seg["lines"]:
            name, rate, pitch = voice_for(ln.get("speaker"))
            try:
                a = sound.tts(ln["text"], name, rate, pitch, cache)
            except RuntimeError as e:  # unknown/unavailable character voice -> narrator voice
                if name == vcfg["narrator"]:
                    raise
                print(f"warning: {e}; using narrator voice for this line")
                a = sound.tts(ln["text"], vcfg["narrator"], vcfg["rate"], pitch, cache)
            if prev != "__start__":
                cur += 0.55 if ln.get("speaker") != prev else 0.3
            ln["_start"], ln["_audio"] = cur, a
            ln["_dur"] = len(a) / sound.SR
            cur += ln["_dur"]
            prev = ln.get("speaker")
        seg["dur"] = max(seg["min"], cur + seg["tail"])
        seg["start"] = t
        t += seg["dur"]
    total = t
    # per-frame mouth/talk arrays per character for each segment
    for seg in segs:
        n = int(round(seg["dur"] * fps)) + 2
        mouths, talk = {}, {}
        for ln in seg["lines"]:
            sp = ln.get("speaker")
            if not sp:
                continue
            env = sound.envelope(ln["_audio"], fps)
            f0 = int(ln["_start"] * fps)
            m = mouths.setdefault(sp, np.zeros(n, bool))
            k = talk.setdefault(sp, np.zeros(n, np.float32))
            for j, e in enumerate(env):
                if f0 + j < n:
                    m[f0 + j] = e > 0.28
                    k[f0 + j] = 1.0
        # smooth "talk" so heads ease in/out of animated speech
        for sp in talk:
            k = talk[sp]
            ker = np.ones(9) / 9
            talk[sp] = np.convolve(k, ker, mode="same")
        seg["mouths"] = {k: v.tolist() for k, v in mouths.items()}
        seg["talk"] = {k: v.tolist() for k, v in talk.items()}
    return segs, total


def mix_audio(segs, total, cfg, seed, mood):
    vc = cfg["video"]
    n = int((total + 0.5) * sound.SR)
    voice = np.zeros(n, np.float32)
    amb = np.zeros(n, np.float32)
    fx = np.zeros(n, np.float32)
    for k, seg in enumerate(segs):
        for ln in seg["lines"]:
            sound.place(voice, ln["_audio"], seg["start"] + ln["_start"])
        kind = seg["scene"].get("ambience", "none") if seg["kind"] == "scene" else "none"
        if kind != "none":
            a = sound.ambience(kind, seg["dur"] + 1.6, seed + k)
            sound.place(amb, a, max(0, seg["start"] - 0.8))
        for ev in seg.get("sfx", []):
            at = ev.get("at", 0)
            if isinstance(at, str) and at.startswith("line:"):
                li = int(at.split(":")[1])
                lines = seg["lines"]
                at = lines[min(li, len(lines) - 1)]["_start"] - 0.15 if lines else 0
            try:
                sound.place(fx, sound.sfx(ev["name"], seed + k), seg["start"] + float(at))
            except ValueError as e:
                print("warning:", e)
    mus = sound.music(total + 0.5, seed, mood)[:n]
    # duck music under speech
    fps = 50
    env = sound.envelope(voice, fps)
    env = np.convolve(np.clip(env, 0, 1), np.ones(25) / 25, mode="same")
    duck = 1 - 0.55 * np.clip(env * 1.5, 0, 1)
    duck = np.interp(np.arange(n) / sound.SR, np.arange(len(duck)) / fps, duck).astype(np.float32)
    L = voice + amb * vc["ambience_volume"] + fx * vc["sfx_volume"] + mus[:, 0] * vc["music_volume"] * duck
    R = voice + amb * vc["ambience_volume"] + fx * vc["sfx_volume"] + mus[:, 1] * vc["music_volume"] * duck
    st = np.stack([L, R], axis=1)
    st /= max(1.0, np.max(np.abs(st)) / 0.95)
    return st


# ====================================================================== captions
def _chunks(text, max_chars=80):
    import re
    parts = re.split(r"(?<=[.!?,;:])\s+", text.strip())
    out, cur = [], ""
    for p in parts:
        if len(cur) + len(p) + 1 <= max_chars or not cur:
            cur = (cur + " " + p).strip()
        else:
            out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out


def segment_captions(seg):
    """[(start, end, text, is_character_line)] relative to the segment."""
    if seg["kind"] != "scene":
        return []
    caps = []
    for ln in seg["lines"]:
        chunks = _chunks(ln["text"])
        total = sum(len(c) for c in chunks) or 1
        t = ln["_start"]
        for c in chunks:
            d = ln["_dur"] * len(c) / total
            caps.append((t, t + d + 0.2, c, bool(ln.get("speaker"))))
            t += d
    return caps


# ====================================================================== thumbnail
def make_thumbnail(story, characters, cfg, out):
    W, H = 1280, 720
    sc = story["scenes"][story.get("thumbnail_scene", story.get("title_scene", 0))]
    r = SceneRenderer(sc, characters, W, H, 24, 10, {}, {}, 7, camera_override="still")
    img = r.frame(30).convert("RGBA")
    # left gradient for legibility
    g = np.zeros((H, W, 4), np.uint8)
    g[..., 3] = (np.clip(1 - np.arange(W)[None, :] / (W * 0.62), 0, 1) ** 1.3 * 170).astype(np.uint8)
    g[..., 0:3] = (30, 15, 60)
    img.alpha_composite(Image.fromarray(g, "RGBA"))
    tb = text_block(story.get("thumbnail_text", story["title"]).upper(), 640, 92, fill=(255, 236, 120),
                    stroke=(40, 20, 80), align="left")
    img.alpha_composite(tb, (40, max(20, (H - tb.height) // 2 - 20)))
    badge = text_block(cfg["channel_name"], 600, 34, fill=(255, 255, 255), weight="SemiBold", align="left")
    img.alpha_composite(badge, (44, H - badge.height - 24))
    img.convert("RGB").save(out, quality=92)


# ====================================================================== main entry
def render_episode(ep_dir: Path, workers: int | None = None, preview_only=False) -> dict:
    ep_dir = Path(ep_dir)
    story = json.loads((ep_dir / "story.json").read_text())
    cfg = load_config()
    vc = cfg["video"]
    W, H, fps = vc["width"], vc["height"], vc["fps"]
    seed = int(hashlib.sha1(story.get("date", story["title"]).encode()).hexdigest()[:8], 16)
    extra = story.get("new_characters") or {}
    cast = set()
    for sc in story["scenes"]:
        for pl in sc.get("characters", []):
            cast.add(pl["id"])
        for ln in sc["narration"]:
            if ln.get("speaker"):
                cast.add(ln["speaker"])
    characters = {c: rig.load_character(c, extra) for c in cast}
    work = ep_dir / "build"
    work.mkdir(exist_ok=True)

    make_thumbnail(story, characters, cfg, ep_dir / "thumbnail.jpg")
    if preview_only:
        return {"thumbnail": str(ep_dir / "thumbnail.jpg")}

    segs, total = build_timeline(story, cfg, characters, work / "tts")
    audio = mix_audio(segs, total, cfg, seed, story.get("music", "gentle"))
    sound.write_wav(work / "mix.wav", audio)

    jobs = []
    cams = ["pan_right", "push_in", "pan_left", "drift"]
    for k, seg in enumerate(segs):
        dur = seg["dur"] + (XFADE if k < len(segs) - 1 else 0)
        ov = None
        cam = None
        if seg["kind"] == "intro":
            ov = {"kicker": cfg["channel_name"] + " presents", "title": story["title"], "pop": True}
            cam = "push_in"
        elif seg["kind"] == "outro":
            ov = {"title": "The End", "sub": story["moral"]}
            cam = "pull_out"
        elif "camera" not in seg["scene"]:
            cam = cams[k % len(cams)]
        caps = segment_captions(seg) if vc.get("captions", True) else []
        jobs.append((seg["scene"], characters, W, H, fps, dur, seg["mouths"], seg["talk"], seed + k,
                     work / f"seg_{k:02d}.mp4", ov, cam, caps))
    workers = workers or max(1, min(len(jobs), os.cpu_count() or 2))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        outs = list(ex.map(_render_segment, jobs))

    out = ep_dir / "video.mp4"
    inputs = []
    for o in outs:
        inputs += ["-i", o]
    inputs += ["-i", str(work / "mix.wav")]
    fl, last = [], "[0:v]"
    for k in range(1, len(outs)):
        tr = segs[k]["scene"].get("transition", "fade") if segs[k]["kind"] == "scene" else "fade"
        if tr not in ("fade", "fadeblack", "smoothleft", "smoothright", "circleopen", "dissolve", "wipeleft"):
            tr = "fade"
        fl.append(f"{last}[{k}:v]xfade=transition={tr}:duration={XFADE}:offset={segs[k]['start']:.3f}[v{k}]")
        last = f"[v{k}]"
    post = f"fade=t=in:st=0:d=0.8,fade=t=out:st={total - 1.5:.3f}:d=1.5"
    fl.append(f"{last}{post},format=yuv420p[vout]")
    fl.append(f"[{len(outs)}:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fl), "-map", "[vout]", "-map", "[aout]",
           "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    meta = {"video": str(out), "thumbnail": str(ep_dir / "thumbnail.jpg"), "duration": round(total, 2)}
    (ep_dir / "render.json").write_text(json.dumps(meta, indent=2))
    return meta
