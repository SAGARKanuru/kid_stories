"""Rigged 2D characters: breathing, head motion, blinking, lip-sync, walking, hopping."""
import json
import math
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from . import ROOT, svgtools

TINTS = {
    "day": (1.0, 1.0, 1.0),
    "morning": (1.02, 0.99, 0.95),
    "sunset": (1.05, 0.9, 0.8),
    "night": (0.62, 0.68, 0.92),
    "indoor": (1.02, 0.97, 0.9),
}


def load_character(cid: str, extra: dict | None = None) -> dict:
    if extra and cid in extra:
        return extra[cid]
    path = ROOT / "characters" / f"{cid}.json"
    if not path.exists():
        raise FileNotFoundError(f"character '{cid}' not found in characters/")
    return json.loads(path.read_text())


def _tint(img: Image.Image, tint) -> Image.Image:
    if tint == (1.0, 1.0, 1.0):
        return img
    r, g, b, a = img.split()
    r = r.point(lambda v: min(255, int(v * tint[0])))
    g = g.point(lambda v: min(255, int(v * tint[1])))
    b = b.point(lambda v: min(255, int(v * tint[2])))
    return Image.merge("RGBA", (r, g, b, a))


OUTLINE = (52, 30, 72, 255)


def _outline(img: Image.Image, px: int) -> Image.Image:
    """Cartoon ink outline: dilate the alpha and put a dark rim behind the artwork."""
    if px < 1:
        return img
    a = img.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    k = 2 * px + 1
    grown = a.filter(ImageFilter.MaxFilter(k if k % 2 else k + 1)).filter(ImageFilter.GaussianBlur(0.6))
    rim = Image.new("RGBA", img.size, OUTLINE)
    rim.putalpha(grown)
    rim.alpha_composite(img)
    return rim


def _happy_eyes(closed: Image.Image) -> Image.Image:
    """Turn closed-eye arcs (smile-shaped) into happy upside-down arcs, eye by eye."""
    out = Image.new("RGBA", closed.size, (0, 0, 0, 0))
    a = closed.getchannel("A")
    bbox = a.getbbox()
    if not bbox:
        return out
    mid = (bbox[0] + bbox[2]) // 2
    for box in ((bbox[0], bbox[1], mid, bbox[3]), (mid, bbox[1], bbox[2], bbox[3])):
        piece = closed.crop(box)
        b = piece.getbbox()
        if not b:
            continue
        eye = piece.crop(b)
        out.alpha_composite(ImageOps.flip(eye), (box[0] + b[0], box[1] + b[1] - eye.height // 3))
    return out


class Sprite:
    """One character placed in one scene at a fixed size."""

    def __init__(self, char: dict, height_px: int, facing: str = "right", time_of_day: str = "day",
                 seed: int = 0):
        self.char = char
        vb_w, vb_h = char["viewbox"]
        self.s = height_px / vb_h
        W, H = max(1, round(vb_w * self.s)), max(1, round(vb_h * self.s))
        self.W, self.H = W, H
        parts = char["parts"]
        tint = TINTS.get(time_of_day, TINTS["day"])
        ol = max(2, round(H / 120))

        def r(name):
            im = svgtools.render(parts[name], W, H, vb_w, vb_h)
            a = im.getchannel("A")
            im = ImageEnhance.Color(im.convert("RGB")).enhance(1.15).convert("RGBA")
            im.putalpha(a)
            return _tint(im, tint)

        body = _outline(r("body"), ol)
        head = _outline(r("head"), ol)
        eyes = {"open": r("eyes_open"), "closed": r("eyes_closed")}
        eyes["happy"] = _happy_eyes(eyes["closed"])
        mouths = {False: r("mouth_closed"), True: r("mouth_open")}
        heads = {}
        for ek, ev in eyes.items():
            for mk, mv in mouths.items():
                im = head.copy()
                im.alpha_composite(ev)
                im.alpha_composite(mv)
                heads[(ek, mk)] = im
        bbox = None
        for im in heads.values():
            b = im.getbbox()
            if b:
                bbox = b if bbox is None else (min(bbox[0], b[0]), min(bbox[1], b[1]),
                                               max(bbox[2], b[2]), max(bbox[3], b[3]))
        bbox = bbox or (0, 0, W, H)
        m = int(0.08 * max(bbox[2] - bbox[0], bbox[3] - bbox[1]))
        bbox = (max(0, bbox[0] - m), max(0, bbox[1] - m), min(W, bbox[2] + m), min(H, bbox[3] + m))
        nx, ny = char.get("neck", [vb_w / 2, vb_h * 0.5])
        pivot = (nx * self.s - bbox[0], ny * self.s - bbox[1])
        heads = {k: v.crop(bbox) for k, v in heads.items()}
        self.head_origin = (bbox[0], bbox[1])

        if facing == "left":
            body = ImageOps.mirror(body)
            heads = {k: ImageOps.mirror(v) for k, v in heads.items()}
            self.head_origin = (W - bbox[2], bbox[1])
            pivot = ((bbox[2] - bbox[0]) - pivot[0], pivot[1])
        self.body, self.heads, self.pivot = body, heads, pivot
        self.mirror = facing == "left"
        self.margin = int(0.25 * max(W, H))

        sw, sh = int(W * 0.62), max(6, int(H * 0.06))
        sh_img = Image.new("RGBA", (sw + 40, sh + 40), (0, 0, 0, 0))
        ImageDraw.Draw(sh_img).ellipse((20, 20, 20 + sw, 20 + sh), fill=(20, 15, 40, 95))
        self.shadow = sh_img.filter(ImageFilter.GaussianBlur(8))

        rnd = random.Random(seed)
        self.phase = rnd.random() * 6.28
        self.blinks = []
        t = rnd.uniform(0.6, 2.0)
        while t < 600:
            self.blinks.append(t)
            t += rnd.uniform(2.2, 5.0)

    def is_blinking(self, t: float) -> bool:
        for b in self.blinks:
            if b > t:
                return False
            if t - b < 0.14:
                return True
        return False

    def draw(self, layer: Image.Image, t: float, x: float, y: float, action: str = "idle",
             talking: float = 0.0, mouth_open: bool = False, offset=(0, 0), appear: float = 1.0):
        """Composite the character onto `layer` with feet at (x, y) in layer pixels.
        appear: 0..1 pop-in progress (1 = fully visible)."""
        H = self.H
        dy, tilt = 0.0, 0.0
        sx = sy = 1.0
        head_angle = 2.2 * math.sin(2 * math.pi * t / 3.3 + self.phase)
        breathe = 0.006 * H * math.sin(2 * math.pi * t / 2.6 + self.phase)
        happy = False

        def jump(freq, height):
            ph = (t * freq) % 1.0                      # 0..1 one jump cycle
            h = math.sin(math.pi * ph)                  # 0 ground, 1 top
            v = math.cos(math.pi * ph)                  # +up / -down speed
            # stretch while fast in the air, squash right at take-off/landing
            st = 0.07 * abs(v) * h * 3 if h > 0.12 else 0.0
            sq = 0.10 * (1 - h / 0.12) if h <= 0.12 else 0.0
            return -h * height * H, 1 - st * 0.6 + sq, 1 + st - sq

        if action == "bounce":
            dy, sx, sy = jump(0.85, 0.05)
            head_angle *= 1.6
            happy = True
        elif action == "hop":
            dy, sx, sy = jump(0.55, 0.14)
        elif action == "walk":
            dy = -abs(math.sin(math.pi * t * 3.0)) * 0.03 * H
            tilt = 2.0 * math.sin(math.pi * t * 3.0)
        elif action == "shake":
            tilt = 4.0 * math.sin(2 * math.pi * t * 7.0)
            head_angle += 5 * math.sin(2 * math.pi * t * 5.0)
            sy = 1 + 0.02 * math.sin(2 * math.pi * t * 7.0)
        elif action == "wobble":
            tilt = 9.0 * math.sin(2 * math.pi * t * 0.9)
            head_angle = -tilt * 1.3
            dy = -abs(math.sin(2 * math.pi * t * 0.9)) * 0.02 * H
        elif action == "dance":
            dy, sx, sy = jump(0.8, 0.06)
            tilt = 7.0 * math.sin(2 * math.pi * t * 0.8)
            head_angle = -tilt
            happy = True
        elif action == "sleep":
            head_angle = 6 + 1.5 * math.sin(2 * math.pi * t / 4.0)
            breathe *= 2.2
        if talking > 0:
            head_angle += talking * (3.5 * math.sin(2 * math.pi * t * 1.4) + 2.0 * math.sin(2 * math.pi * t * 3.1))
        if self.mirror:
            head_angle, tilt = -head_angle, -tilt
        if appear < 1.0:  # elastic pop-in
            q = max(0.0, appear)
            k = 1 + 2.7 * (q - 1) ** 3 + 1.7 * (q - 1) ** 2
            sx, sy = sx * max(0.01, k), sy * max(0.01, k)

        ox, oy = offset
        lift = min(1.0, -dy / (0.15 * H)) if dy < 0 else 0.0
        sh = self.shadow
        if lift > 0.02 or appear < 1:
            f = (1 - 0.35 * lift) * min(1.0, max(0.05, appear))
            sh = sh.resize((max(4, int(sh.width * f)), max(4, int(sh.height * f))))
        _paste(layer, sh, int(x - sh.width / 2 + ox), int(y - sh.height / 2 + oy))

        # compose the character on its own canvas, then squash/stretch around the feet
        m = self.margin
        cv = Image.new("RGBA", (self.W + 2 * m, H + 2 * m), (0, 0, 0, 0))
        body = self.body
        if abs(tilt) > 0.3:
            body = body.rotate(tilt, resample=Image.BICUBIC, center=(self.W / 2, H))
        cv.alpha_composite(body, (m, m))
        blink = self.is_blinking(t) or action == "sleep"
        eye = "closed" if blink else ("happy" if happy and not talking else "open")
        head = self.heads[(eye, bool(mouth_open and action != "sleep"))]
        if abs(head_angle) > 0.2:
            head = head.rotate(head_angle, resample=Image.BICUBIC, center=self.pivot)
        cv.alpha_composite(head, (m + self.head_origin[0], m + self.head_origin[1] - int(breathe * 0.5)))
        feet_x, feet_y = m + self.W / 2, m + H
        if abs(sx - 1) > 0.004 or abs(sy - 1) > 0.004:
            nw, nh = max(1, int(cv.width * sx)), max(1, int(cv.height * sy))
            cv = cv.resize((nw, nh), Image.BILINEAR)
            feet_x, feet_y = feet_x * sx, feet_y * sy
        _paste(layer, cv, int(round(x - feet_x + ox)), int(round(y - feet_y + dy + breathe * 0.5 + oy)))


def _paste(dst: Image.Image, src: Image.Image, x: int, y: int):
    """alpha_composite that tolerates sprites partly outside the frame."""
    W, H = dst.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + src.width), min(H, y + src.height)
    if x1 <= x0 or y1 <= y0:
        return
    crop = src.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    dst.alpha_composite(crop, (x0, y0))
