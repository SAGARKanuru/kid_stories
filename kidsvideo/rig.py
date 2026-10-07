"""Rigged 2D characters: breathing, head motion, blinking, lip-sync, walking, hopping."""
import json
import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps

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

        def r(name):
            return _tint(svgtools.render(parts[name], W, H, vb_w, vb_h), tint)

        body = r("body")
        head = r("head")
        heads = {}
        for eyes in ("eyes_open", "eyes_closed"):
            for mouth in ("mouth_closed", "mouth_open"):
                im = head.copy()
                im.alpha_composite(r(eyes))
                im.alpha_composite(r(mouth))
                heads[(eyes == "eyes_closed", mouth == "mouth_open")] = im
        # Crop head layers to their bounding box (+ margin) so rotation is cheap.
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

        # Soft contact shadow.
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
             talking: float = 0.0, mouth_open: bool = False, offset=(0, 0)):
        """Composite the character onto `layer` with feet at (x, y) in layer pixels."""
        H = self.H
        dy, tilt = 0.0, 0.0
        head_angle = 2.2 * math.sin(2 * math.pi * t / 3.3 + self.phase)
        breathe = 0.006 * H * math.sin(2 * math.pi * t / 2.6 + self.phase)
        if action == "bounce":
            dy = -abs(math.sin(math.pi * t * 1.7)) * 0.045 * H
            head_angle *= 1.6
        elif action == "hop":
            dy = -abs(math.sin(math.pi * t * 1.05)) * 0.13 * H
        elif action == "walk":
            dy = -abs(math.sin(math.pi * t * 3.0)) * 0.03 * H
            tilt = 2.0 * math.sin(math.pi * t * 3.0)
        elif action == "shake":  # surprised / giggling jitter
            tilt = 4.0 * math.sin(2 * math.pi * t * 7.0)
            head_angle += 5 * math.sin(2 * math.pi * t * 5.0)
        elif action == "wobble":  # dizzy / silly rocking
            tilt = 9.0 * math.sin(2 * math.pi * t * 0.9)
            head_angle = -tilt * 1.3
            dy = -abs(math.sin(2 * math.pi * t * 0.9)) * 0.02 * H
        elif action == "dance":
            tilt = 7.0 * math.sin(2 * math.pi * t * 1.6)
            dy = -abs(math.sin(2 * math.pi * t * 1.6)) * 0.06 * H
            head_angle = -tilt
        elif action == "sleep":
            head_angle = 6 + 1.5 * math.sin(2 * math.pi * t / 4.0)
            breathe *= 2.2
        if talking > 0:
            head_angle += talking * (3.5 * math.sin(2 * math.pi * t * 1.4) + 2.0 * math.sin(2 * math.pi * t * 3.1))
        if self.mirror:
            head_angle, tilt = -head_angle, -tilt

        ox, oy = offset
        bx = int(round(x - self.W / 2 + ox))
        by = int(round(y - H + dy + breathe * 0.5 + oy))

        # Shadow stays on the ground and shrinks while airborne.
        lift = min(1.0, -dy / (0.15 * H)) if dy < 0 else 0.0
        sh = self.shadow
        if lift > 0.02:
            sh = sh.resize((max(4, int(sh.width * (1 - 0.35 * lift))), max(4, int(sh.height * (1 - 0.35 * lift)))))
        _paste(layer, sh, int(x - sh.width / 2 + ox), int(y - sh.height / 2 + oy))

        body = self.body
        if abs(tilt) > 0.3:
            body = body.rotate(tilt, resample=Image.BICUBIC, center=(self.W / 2, H))
        _paste(layer, body, bx, by)

        blink = self.is_blinking(t) or action == "sleep"
        head = self.heads[(blink, mouth_open and action != "sleep")]
        if abs(head_angle) > 0.2:
            head = head.rotate(head_angle, resample=Image.BICUBIC, center=self.pivot)
        hx = bx + self.head_origin[0]
        hy = by + self.head_origin[1] - int(breathe * 0.5)
        _paste(layer, head, hx, hy)


def _paste(dst: Image.Image, src: Image.Image, x: int, y: int):
    """alpha_composite that tolerates sprites partly outside the frame."""
    W, H = dst.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + src.width), min(H, y + src.height)
    if x1 <= x0 or y1 <= y0:
        return
    crop = src.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    dst.alpha_composite(crop, (x0, y0))
