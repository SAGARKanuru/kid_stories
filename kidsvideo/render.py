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
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

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


def vivid(img: Image.Image, sat: float = 1.22, con: float = 1.06) -> Image.Image:
    """Bright, saturated cartoon colours (applied once to static artwork)."""
    a = img.getchannel("A")
    rgb = ImageEnhance.Contrast(ImageEnhance.Color(img.convert("RGB")).enhance(sat)).enhance(con)
    rgb = rgb.convert("RGBA")
    rgb.putalpha(a)
    return rgb


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


def _hex(c, default=(232, 65, 78)):
    try:
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _shape(d, kind, cx, cy, r, col):
    dark = tuple(max(0, int(v * 0.7)) for v in col)
    if kind == "circle":
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col, outline=dark, width=max(2, r // 10))
    elif kind == "square":
        d.rounded_rectangle((cx - r, cy - r, cx + r, cy + r), radius=r // 5, fill=col, outline=dark, width=max(2, r // 10))
    elif kind == "rectangle":
        d.rounded_rectangle((cx - r * 1.4, cy - r * 0.8, cx + r * 1.4, cy + r * 0.8), radius=r // 6, fill=col, outline=dark, width=max(2, r // 10))
    elif kind == "triangle":
        d.polygon([(cx, cy - r), (cx + r * 1.05, cy + r * 0.8), (cx - r * 1.05, cy + r * 0.8)], fill=col, outline=dark, width=max(2, r // 10))
    elif kind == "star":
        pts = []
        for i in range(10):
            a = -math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.45
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.polygon(pts, fill=col, outline=dark, width=max(2, r // 12))
    elif kind == "heart":
        d.ellipse((cx - r, cy - r * 0.75, cx, cy + r * 0.2), fill=col)
        d.ellipse((cx, cy - r * 0.75, cx + r, cy + r * 0.2), fill=col)
        d.polygon([(cx - r * 0.97, cy - r * 0.15), (cx + r * 0.97, cy - r * 0.15), (cx, cy + r)], fill=col)
    elif kind == "diamond":
        d.polygon([(cx, cy - r), (cx + r * 0.75, cy), (cx, cy + r), (cx - r * 0.75, cy)], fill=col, outline=dark, width=max(2, r // 10))


def learn_card(spec, W):
    """A pop-up 'learning card': shapes/counting row, big word or number, small caption."""
    s = W / 1920
    col = _hex(spec.get("color", "#E8414E"))
    shape, count = spec.get("shape", "none"), int(spec.get("count", 0) or 0)
    text, sub = str(spec.get("text", "")), str(spec.get("sub", ""))
    big = font(int((150 if len(text) <= 3 else 100 if len(text) <= 8 else 74) * s), "Bold")
    small = font(int(46 * s), "SemiBold")
    pad = int(36 * s)
    icons_h = 0
    n_icons = min(count, 10) if count else (1 if shape != "none" and not text else 0)
    r = int((54 if n_icons <= 5 else 40) * s)
    if n_icons:
        icons_h = 2 * r + int(18 * s)
    tw = big.getlength(text) if text else 0
    sw = small.getlength(sub) if sub else 0
    iw = n_icons * (2 * r + int(16 * s))
    Wc = int(max(tw, sw, iw, 280 * s) + 2 * pad)
    th = int(big.size * 1.08) if text else 0
    sh_ = int(small.size * 1.3) if sub else 0
    Hc = int(pad * 1.6 + icons_h + th + sh_)
    img = Image.new("RGBA", (Wc + 40, Hc + 40), (0, 0, 0, 0))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((24, 30, Wc + 16, Hc + 22), radius=int(40 * s), fill=(30, 15, 50, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((20, 20, Wc + 20, Hc + 20), radius=int(40 * s), fill=(255, 252, 244, 248),
                        outline=col, width=max(4, int(8 * s)))
    y = 20 + int(pad * 0.8)
    if n_icons:
        x0 = 20 + (Wc - iw) / 2 + r + int(8 * s)
        for i in range(n_icons):
            _shape(d, shape if shape != "none" else "star", int(x0 + i * (2 * r + int(16 * s))), y + r, r, col)
        y += icons_h
    if text:
        d.text((20 + (Wc - tw) / 2, y - big.size * 0.08), text, font=big, fill=col,
               stroke_width=max(2, int(4 * s)), stroke_fill=(255, 255, 255))
        y += th
    if sub:
        d.text((20 + (Wc - sw) / 2, y), sub, font=small, fill=(60, 40, 80))
    return img


# ====================================================================== particles
class Particles:
    def __init__(self, kind, W, H, seed):
        self.kind, self.W, self.H = kind, W, H
        rnd = random.Random(seed)
        count = {"fireflies": 28, "sparkles": 26, "leaves": 16, "snow": 90, "rain": 160, "bubbles": 22,
                 "dust": 45, "petals": 20, "confetti": 110}.get(kind, 0)
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
            elif k == "confetti":
                y = ((b + t * 0.16 * s) % 1.15 - 0.08) * H
                x = (a * W + 60 * self.k * math.sin(t * 1.6 * s + c * 9)) % W
                ang = t * 4 * s + c * 12
                L, Wd = 16 * s * self.k, 8 * s * self.k * abs(math.cos(t * 5 * s + a * 7))
                cols = [(255, 92, 120), (255, 200, 60), (80, 190, 255), (120, 220, 110), (190, 120, 255), (255, 150, 60)]
                col = cols[int(c * 6) % 6] + (240,)
                dx, dy = math.cos(ang), math.sin(ang)
                d.polygon([(x - dx * L - dy * Wd, y - dy * L + dx * Wd), (x + dx * L - dy * Wd, y + dy * L + dx * Wd),
                           (x + dx * L + dy * Wd, y + dy * L - dx * Wd), (x - dx * L + dy * Wd, y - dy * L - dx * Wd)], fill=col)
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
                 camera_override: str | None = None, captions=None, popups=None, shakes=None):
        self.W, self.H, self.fps, self.dur = W, H, fps, dur
        self.captions = captions or []
        self.shakes = shakes or []
        self.popups = [(p["_t0"], p["_t1"], learn_card(p, W), p.get("position", "top")) for p in (popups or [])]
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
            img = vivid(img)
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
        for st in self.shakes:  # comedy camera shake on bonks/boings
            if 0 <= t - st < 0.5:
                dec = (1 - (t - st) / 0.5) ** 2
                u += 0.16 * dec * math.sin(2 * math.pi * 17 * (t - st))
                v += 0.22 * dec * math.cos(2 * math.pi * 13 * (t - st))

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
            appear = 1.0
            if pl.get("enter") == "pop":
                appear = (t - float(pl.get("start", 0.4))) / 0.45
                if appear <= 0:
                    continue
            spr.draw(fr, t, x * self.sx, y * self.sy, action, talking, mouth, offset=(-mo[0], -mo[1]),
                     appear=min(1.0, appear))
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
        for (p0, p1, card, pos) in self.popups:
            if p0 <= t < p1:
                q = (t - p0) / 0.45
                k = 1 + 2.4 * (q - 1) ** 3 + 1.4 * (q - 1) ** 2 if q < 1 else 1.0  # ease-out-back
                fade = min(1.0, (p1 - t) / 0.3)
                k *= 0.85 + 0.15 * fade
                c = card
                if abs(k - 1) > 0.01:
                    c = card.resize((max(1, int(card.width * k)), max(1, int(card.height * k))), Image.BILINEAR)
                if fade < 1:
                    a = c.getchannel("A").point(lambda v: int(v * fade))
                    c = c.copy()
                    c.putalpha(a)
                bob = int(6 * self.H / 1080 * math.sin(2 * math.pi * (t - p0) / 1.6))
                cy = int(self.H * 0.05) + (card.height - c.height) // 2 + bob
                if pos == "left":
                    cx = int(self.W * 0.04) + (card.width - c.width) // 2
                elif pos == "right":
                    cx = self.W - int(self.W * 0.04) - card.width + (card.width - c.width) // 2
                else:
                    cx = (self.W - c.width) // 2
                fr.alpha_composite(c, (max(0, cx), max(0, cy)))
                if t - p0 < 0.9:  # sparkle burst
                    q = (t - p0) / 0.9
                    dd = ImageDraw.Draw(fr, "RGBA")
                    ccx, ccy = cx + c.width / 2, cy + c.height / 2
                    for j in range(12):
                        ang = j * math.pi / 6 + 0.3
                        rad = (card.width * 0.45 + 160 * self.W / 1920 * q)
                        px_, py_ = ccx + math.cos(ang) * rad, ccy + math.sin(ang) * rad * 0.8
                        rr = 16 * self.W / 1920 * (1 - q)
                        colr = [(255, 220, 80), (255, 120, 160), (120, 210, 255)][j % 3] + (int(255 * (1 - q)),)
                        dd.polygon([(px_, py_ - rr), (px_ + rr * .3, py_ - rr * .3), (px_ + rr, py_), (px_ + rr * .3, py_ + rr * .3),
                                    (px_, py_ + rr), (px_ - rr * .3, py_ + rr * .3), (px_ - rr, py_), (px_ - rr * .3, py_ - rr * .3)], fill=colr)
        for k, (c0, c1, text, talk) in enumerate(self.captions):
            if c0 <= t < c1:
                if k not in self._cap_cache:
                    self._cap_cache[k] = caption_image(text, self.W, talk)
                ci = self._cap_cache[k]
                fr.alpha_composite(ci, ((self.W - ci.width) // 2, self.H - ci.height - int(46 * self.H / 1080)))
                break
        return fr


class IntroRenderer:
    """Branded animated opener: rotating sunburst, bouncing rainbow title, story ribbon, cast pops in, confetti."""
    RAINBOW = [(255, 92, 120), (255, 160, 50), (255, 210, 60), (110, 205, 100), (70, 180, 255), (170, 120, 255)]

    def __init__(self, spec, characters, W, H, fps, dur, mouths=None, talk=None):
        self.W, self.H, self.fps, self.dur = W, H, fps, dur
        s = W / 1920
        D = int(math.hypot(W, H)) + 40
        rays = Image.new("RGBA", (D, D), (255, 196, 70, 255))
        d = ImageDraw.Draw(rays)
        c = D / 2
        for k in range(24):
            if k % 2:
                continue
            a0, a1 = k * math.pi / 12, (k + 1) * math.pi / 12
            d.polygon([(c, c), (c + D * math.cos(a0), c + D * math.sin(a0)), (c + D * math.cos(a1), c + D * math.sin(a1))],
                      fill=(255, 222, 110, 255))
        yy, xx = np.mgrid[0:D, 0:D].astype(np.float32)
        r = np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / (D / 2)
        glow = np.zeros((D, D, 4), np.uint8)
        glow[..., 0:3] = (255, 250, 225)
        glow[..., 3] = (np.clip(1 - r * 1.6, 0, 1) ** 1.5 * 230).astype(np.uint8)
        rays.alpha_composite(Image.fromarray(glow, "RGBA"))
        edge = np.zeros((D, D, 4), np.uint8)
        edge[..., 0:3] = (235, 95, 60)
        edge[..., 3] = (np.clip((r - 0.45) / 0.55, 0, 1) ** 1.3 * 200).astype(np.uint8)
        rays.alpha_composite(Image.fromarray(edge, "RGBA"))
        self.rays = rays
        hill = svgtools.render(
            '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8EDB6E"/>'
            '<stop offset="1" stop-color="#4FA348"/></linearGradient></defs>'
            '<path d="M0 900 C400 840 700 870 960 865 C1250 860 1500 835 1920 880 V1080 H0Z" fill="url(#g)"/>'
            '<path d="M0 900 C400 840 700 870 960 865 C1250 860 1500 835 1920 880 L1920 896 C1500 851 1250 876 960 881 '
            'C700 886 400 856 0 916Z" fill="#C6F2A2" opacity=".7"/>', W, H)
        self.hill = vivid(hill)
        # rainbow letters of the channel name
        f = font(int(112 * s), "Bold")
        self.letters = []
        name = spec.get("channel", "")
        x = (W - f.getlength(name)) / 2
        for i, ch in enumerate(name):
            w = f.getlength(ch)
            if ch.strip():
                img = text_block(ch, 400 * s, int(112 * s), fill=self.RAINBOW[i % 6], stroke=(60, 30, 90))
                self.letters.append((img, x + w / 2, i))
            x += w
        # story title ribbon
        title = text_block(spec["title"], 1500 * s, int(78 * s), fill=(255, 255, 255), stroke=(80, 30, 110))
        rw, rh = title.width + int(110 * s), title.height + int(40 * s)
        rib = Image.new("RGBA", (rw + 20, rh + 30), (0, 0, 0, 0))
        dr = ImageDraw.Draw(rib)
        dr.rounded_rectangle((10, 18, rw + 10, rh + 18), radius=int(rh / 2), fill=(60, 20, 80, 90))
        dr.rounded_rectangle((10, 8, rw + 10, rh + 8), radius=int(rh / 2), fill=(138, 72, 200),
                             outline=(255, 214, 90), width=max(4, int(8 * s)))
        rib.alpha_composite(title, ((rib.width - title.width) // 2, 8 + (rh - title.height) // 2))
        self.ribbon = rib
        # cast
        cast = [c for c in spec.get("cast", []) if c in characters][:3]
        xs = {1: [960], 2: [760, 1160], 3: [600, 960, 1320]}.get(len(cast), [])
        self.cast = []
        for i, (cid, xx) in enumerate(zip(cast, xs)):
            h = int(400 * H / 1080 * float(characters[cid].get("size", 1.0)))
            spr = rig.Sprite(characters[cid], h, "right" if xx < 960 else "left", "day", seed=i * 7)
            self.cast.append((spr, xx * W / 1920, 2.0 + i * 0.22))
        self.confetti = Particles("confetti", W, H, 5)

    def frame(self, i):
        t = i / self.fps
        W, H = self.W, self.H
        ang = t * 9
        rot = self.rays.rotate(ang, resample=Image.BILINEAR)
        cx, cy = rot.width / 2, rot.height / 2 + H * 0.08
        fr = rot.crop((int(cx - W / 2), int(cy - H / 2), int(cx - W / 2) + W, int(cy - H / 2) + H))
        fr.alpha_composite(self.hill)
        for spr, x, t0 in self.cast:
            if t >= t0:
                spr.draw(fr, t, x, H * 0.955, "bounce", 0, False, appear=min(1.0, (t - t0) / 0.45))
        base_y = H * 0.07
        for img, x, k in self.letters:
            t0 = 0.25 + k * 0.05
            if t < t0:
                continue
            q = min(1.0, (t - t0) / 0.5)
            drop = (1 - (1 + 2.6 * (q - 1) ** 3 + 1.6 * (q - 1) ** 2)) * H * 0.25
            wob = math.sin(2 * math.pi * (t * 0.9 + k * 0.08)) * 8 * H / 1080 if q >= 1 else 0
            fr.alpha_composite(img, (int(x - img.width / 2), max(0, int(base_y - drop + wob))))
        if t >= 1.4:
            q = min(1.0, (t - 1.4) / 0.5)
            k = max(0.02, 1 + 2.7 * (q - 1) ** 3 + 1.7 * (q - 1) ** 2)
            rb = self.ribbon if abs(k - 1) < 0.01 else self.ribbon.resize(
                (max(1, int(self.ribbon.width * k)), max(1, int(self.ribbon.height * k))), Image.BILINEAR)
            fr.alpha_composite(rb, ((W - rb.width) // 2, int(H * 0.36 - rb.height / 2)))
        self.confetti.draw(fr, t)
        return fr


def _render_segment(job):
    """Worker: render one segment to an mp4 (video only)."""
    (scene, characters, W, H, fps, dur, mouths, talk, seed, out, overlay_spec, cam, caps, pops, shakes) = job
    overlay, pop = None, False
    if overlay_spec and overlay_spec.get("intro"):
        r = IntroRenderer(overlay_spec, characters, W, H, fps, dur)
    else:
        if overlay_spec:
            overlay, pop = _build_overlay(overlay_spec, W, H), overlay_spec.get("pop", False)
        r = None
    r = r or SceneRenderer(scene, characters, W, H, fps, dur, mouths, talk, seed, overlay, pop, cam, caps, pops, shakes)
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

    narrator = {"name": vcfg["narrator"], "rate": vcfg["rate"], "pitch": vcfg["pitch"],
                "shift": vcfg.get("shift", 0), "backup": vcfg.get("backup")}

    def voice_for(speaker):
        if speaker and speaker in characters and characters[speaker].get("voice"):
            return characters[speaker]["voice"]
        return narrator

    segs = []
    title_idx = story.get("title_scene", 0)
    intro_line = {"text": story.get("intro") or f"Hi friends! Welcome to {cfg['channel_name']}! Today's story is... {story['title']}!",
                  "speaker": None}
    segs.append({"kind": "intro", "scene": story["scenes"][title_idx], "lines": [intro_line], "lead": 2.2, "tail": 1.4,
                 "min": 6.5, "sfx": [{"at": 0.15, "name": "jingle"}, {"at": 1.4, "name": "pop"}]})
    for sc in story["scenes"]:
        segs.append({"kind": "scene", "scene": sc, "lines": sc["narration"], "lead": 0.8, "tail": 1.1, "min": 4.0,
                     "sfx": sc.get("sfx", [])})
    outro_text = story.get("outro") or (f"The End! Remember, friends: {story['moral']} "
                                         "Did you like this story? See you tomorrow for a brand-new one. Bye-bye!")
    end_sc = dict(story["scenes"][story.get("outro_scene", -1)])
    end_sc["particles"] = "confetti"
    end_sc["characters"] = [dict(c, action="dance") for c in end_sc.get("characters", [])
                            if c.get("action") != "walk"] or end_sc.get("characters", [])
    segs.append({"kind": "outro", "scene": end_sc,
                 "lines": [{"text": outro_text, "speaker": None}], "lead": 1.0, "tail": 2.5, "min": 8.0,
                 "sfx": [{"at": 0.3, "name": "tada"}]})

    t = 0.0
    for seg in segs:
        cur = seg["lead"]
        prev = "__start__"
        for ln in seg["lines"]:
            v = voice_for(ln.get("speaker"))
            try:
                a = sound.speak(ln["text"], v, cache, vcfg.get("engine", "auto"))
            except Exception as e:  # unavailable character voice -> narrator voice
                if v is narrator:
                    raise
                print(f"warning: {e}; using narrator voice for this line")
                a = sound.speak(ln["text"], narrator, cache, vcfg.get("engine", "auto"))
            if prev != "__start__":
                cur += 0.55 if ln.get("speaker") != prev else 0.3
            ln["_start"], ln["_audio"] = cur, a
            ln["_dur"] = len(a) / sound.SR
            cur += ln["_dur"]
            cur += min(5.0, max(0.0, float(ln.get("pause", 0) or 0)))  # time for kids to answer
            prev = ln.get("speaker")
        lines = seg["lines"]
        pops = []
        for p in (seg["scene"].get("popups", []) if seg["kind"] == "scene" else []):
            p = dict(p)
            at = p.get("at", 0)
            if isinstance(at, str) and at.startswith("line:") and lines:
                ln = lines[min(int(at.split(":")[1]), len(lines) - 1)]
                p["_t0"] = ln["_start"] + 0.2
                default_end = ln["_start"] + ln["_dur"] + float(ln.get("pause", 0) or 0) + 1.0
            else:
                p["_t0"] = float(at)
                default_end = p["_t0"] + 4.0
            p["_t1"] = p["_t0"] + float(p["dur"]) if p.get("dur") else max(p["_t0"] + 3.0, default_end)
            pops.append(p)
        seg["popups"] = pops
        seg["dur"] = max(seg["min"], cur + seg["tail"], *[p["_t1"] + 0.3 for p in pops])
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


SHAKE_SFX = {"bonk", "boing", "honk", "splash", "drumroll"}


def resolve_at(seg, at):
    if isinstance(at, str) and at.startswith("line:"):
        lines = seg["lines"]
        return lines[min(int(at.split(":")[1]), len(lines) - 1)]["_start"] - 0.15 if lines else 0.0
    return float(at or 0)


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
        for p in seg.get("popups", []):
            snd = p.get("sound", "pop")
            if snd:
                try:
                    sound.place(fx, sound.sfx(snd, seed + k), seg["start"] + p["_t0"], 0.8)
                except ValueError as e:
                    print("warning:", e)
        for ev in seg.get("sfx", []):
            at = resolve_at(seg, ev.get("at", 0))
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
# ====================================================================== YouTube Short (vertical, < 60 s)
SHORT_MAX = 52.0   # seconds of story; + end card stays well under 60 s
COMEDY = {"bonk", "boing", "honk", "slide_up", "slide_down", "zip", "tummy", "idea", "whistle", "bleat",
          "giggle", "hiccup", "snore", "splash", "pop"}


def pick_short_window(story, segs):
    """Choose the funniest stretch of the episode: explicit story['short_scene'] or the scene with the most
    comedy sound effects / learning cards, plus following scenes while it fits."""
    scene_segs = [k for k, sg in enumerate(segs) if sg["kind"] == "scene"]
    if not scene_segs:
        return 0.0, min(SHORT_MAX, segs[-1]["start"] + segs[-1]["dur"])
    if isinstance(story.get("short_scene"), int) and 0 <= story["short_scene"] < len(scene_segs):
        first = scene_segs[story["short_scene"]]
    else:
        def score(k):
            sc = segs[k]["scene"]
            return (sum(1 for e in sc.get("sfx", []) if e.get("name") in COMEDY) * 2 + len(sc.get("popups", []))
                    + sum(1 for pl in sc.get("characters", []) if pl.get("action") in ("wobble", "spin", "laugh", "hop")))
        first = max(scene_segs[:-1] or scene_segs, key=score)
    start = segs[first]["start"]
    end = start
    for k in range(first, len(segs)):
        sg = segs[k]
        if sg["kind"] != "scene":
            break
        seg_end = sg["start"] + sg["dur"]
        if seg_end - start <= SHORT_MAX:
            end = seg_end
            continue
        # cut inside this scene at the end of the last line that still fits
        for ln in sg["lines"]:
            le = sg["start"] + ln["_start"] + ln["_dur"] + float(ln.get("pause", 0) or 0) + 0.6
            if le - start <= SHORT_MAX:
                end = max(end, le)
        break
    if end - start < 15:  # very short scene: extend into the next one
        end = min(start + SHORT_MAX, segs[-1]["start"])
    return start, end


def _short_overlay(story, cfg, characters, cast, W=1080, H=1920):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    k = W / 1080
    top = text_block(cfg["channel_name"], 900 * k, int(46 * k), fill=(255, 236, 140), weight="SemiBold")
    img.alpha_composite(top, ((W - top.width) // 2, int(150 * k)))
    title = text_block(story.get("thumbnail_text") or story["title"], 980 * k, int(92 * k), fill=(255, 255, 255))
    img.alpha_composite(title, ((W - title.width) // 2, int(150 * k) + top.height))
    # bottom: two characters cheering + "full story" line
    xs = [W * 0.27, W * 0.73]
    for x, cid in zip(xs, cast[:2]):
        h = int(330 * k * float(characters[cid].get("size", 1.0)))
        rig.Sprite(characters[cid], h, "right" if x < W / 2 else "left", "day", seed=3).draw(
            img, 0.0, x, H - int(150 * k), "bounce", 0, True)
    cta = text_block("Watch the full story on our channel!", 960 * k, int(56 * k), fill=(255, 255, 255))
    img.alpha_composite(cta, ((W - cta.width) // 2, H - int(560 * k)))
    return img


def make_short(ep_dir, story, cfg, characters, segs):
    """Vertical 1080x1920 YouTube Short cut from the finished episode: blurred backdrop, the scene in the middle,
    the title on top and two cheering characters at the bottom."""
    start, end = pick_short_window(story, segs)
    dur = end - start
    cast = []
    for sc in story["scenes"]:
        for pl in sc.get("characters", []):
            if pl["id"] not in cast and pl["id"] in characters:
                cast.append(pl["id"])
    ov_path = ep_dir / "build" / "short_overlay.png"
    _short_overlay(story, cfg, characters, cast).save(ov_path)
    out = ep_dir / "short.mp4"
    fl = ("[0:v]split[a][b];"
          "[a]scale=-2:1920,crop=1080:1920,boxblur=28:2,eq=brightness=-0.10:saturation=1.2[bg];"
          "[b]scale=1080:-2[fg];"
          "[bg][fg]overlay=0:(H-h)/2-40[base];"
          f"[base][1:v]overlay=0:0,fade=t=in:st=0:d=0.4,fade=t=out:st={dur - 0.8:.2f}:d=0.8,format=yuv420p[v];"
          f"[0:a]afade=t=in:st=0:d=0.3,afade=t=out:st={dur - 1.0:.2f}:d=1.0[a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(ep_dir / "video.mp4"),
                    "-i", str(ov_path), "-filter_complex", fl, "-map", "[v]", "-map", "[a]", "-r", "30",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(out)], check=True)
    return {"short": str(out), "short_window": [round(start, 2), round(end, 2)]}


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
            cast = []
            for sc in story["scenes"]:
                for pl in sc.get("characters", []):
                    if pl["id"] not in cast:
                        cast.append(pl["id"])
            ov = {"intro": True, "channel": cfg["channel_name"], "title": story["title"], "cast": cast}
            cam = "push_in"
        elif seg["kind"] == "outro":
            ov = {"title": "The End", "sub": story["moral"]}
            cam = "pull_out"
        elif "camera" not in seg["scene"]:
            cam = cams[k % len(cams)]
        caps = segment_captions(seg) if vc.get("captions", True) else []
        jobs.append((seg["scene"], characters, W, H, fps, dur, seg["mouths"], seg["talk"], seed + k,
                     work / f"seg_{k:02d}.mp4", ov, cam, caps, seg.get("popups", []),
                     [resolve_at(seg, e.get("at", 0)) + 0.1 for e in seg.get("sfx", []) if e.get("name") in SHAKE_SFX]))
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
    if cfg["youtube"].get("shorts"):
        try:
            meta.update(make_short(ep_dir, story, cfg, characters, segs))
        except Exception as e:
            print(f"::warning::Short not made: {str(e)[:300]}")
    (ep_dir / "render.json").write_text(json.dumps(meta, indent=2))
    return meta
