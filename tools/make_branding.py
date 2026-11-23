"""Channel art for the Masti Nagar gang: profile picture (800x800) and banner (2560x1440).

    python tools/make_branding.py        # writes branding/*.png and preview images
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from kidsvideo import rig, svgtools  # noqa: E402
from kidsvideo.render import font, text_block, vivid  # noqa: E402

OUT = os.path.join(sys.path[0], "branding") + "/"
R = random.Random(11)
RAINBOW = [(255, 84, 112), (255, 150, 40), (255, 205, 40), (90, 200, 90), (60, 170, 255), (160, 110, 255)]


# ---------------------------------------------------------------- drawing helpers (SVG)
def sunburst(cx, cy, rad, n, c1, c2, rot=0):
    out = [f'<circle cx="{cx}" cy="{cy}" r="{rad}" fill="{c1}"/>']
    for k in range(n):
        if k % 2:
            continue
        a0 = math.radians(rot + k * 360 / n)
        a1 = math.radians(rot + (k + 1) * 360 / n)
        out.append(f'<path d="M{cx} {cy} L{cx + rad * math.cos(a0):.0f} {cy + rad * math.sin(a0):.0f} '
                   f'L{cx + rad * math.cos(a1):.0f} {cy + rad * math.sin(a1):.0f}Z" fill="{c2}"/>')
    return "".join(out)


def kite(x, y, s, c1, c2, rot=0):
    return (f'<g transform="rotate({rot} {x} {y})">'
            f'<path d="M{x} {y + 70 * s} C{x - 30 * s} {y + 130 * s} {x + 30 * s} {y + 170 * s} {x - 10 * s} {y + 230 * s}" '
            f'stroke="#fff" stroke-width="{3 * s}" fill="none" opacity=".8"/>'
            f'<path d="M{x - 12 * s} {y + 120 * s} l{14 * s} {-8 * s} l0 {16 * s}z M{x + 4 * s} {y + 170 * s} l{14 * s} {-8 * s} l0 {16 * s}z" fill="{c2}"/>'
            f'<path d="M{x} {y - 70 * s} L{x + 50 * s} {y} L{x} {y + 70 * s} L{x - 50 * s} {y}Z" fill="{c1}"/>'
            f'<path d="M{x} {y - 70 * s} L{x + 50 * s} {y} L{x} {y}Z" fill="#fff" opacity=".25"/>'
            f'<path d="M{x} {y - 70 * s} V{y + 70 * s} M{x - 50 * s} {y} H{x + 50 * s}" stroke="#fff" stroke-width="{3 * s}" opacity=".7"/></g>')


def bunting(x0, y0, x1, y1, sag, n, size=34):
    out = [f'<path d="M{x0} {y0} Q{(x0 + x1) / 2} {max(y0, y1) + sag} {x1} {y1}" stroke="#7A4A2A" stroke-width="4" fill="none"/>']
    cols = ["#FF5470", "#FFC928", "#3CC8B4", "#7A6CFF", "#FF8A3C", "#5AC85A"]
    for i in range(n):
        t = (i + 0.5) / n
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * (x0 + x1) / 2 + t ** 2 * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * (max(y0, y1) + sag) + t ** 2 * y1
        out.append(f'<path d="M{x - size / 2:.0f} {y:.0f} L{x + size / 2:.0f} {y:.0f} L{x:.0f} {y + size * 1.2:.0f}Z" fill="{cols[i % 6]}"/>')
    return "".join(out)


def house(x, base, w, h, wall, roof, trim="#FFFFFF"):
    win = []
    rows = max(1, int(h / 110))
    for r in range(rows):
        for c in range(max(1, int(w / 90))):
            wx = x + 22 + c * 90
            wy = base - h + 30 + r * 110
            if wx + 44 < x + w - 10 and wy + 60 < base - 90:
                win.append(f'<rect x="{wx}" y="{wy}" width="44" height="56" rx="22" fill="#3A6FB0"/>'
                           f'<rect x="{wx}" y="{wy}" width="44" height="56" rx="22" fill="none" stroke="{trim}" stroke-width="5"/>'
                           f'<path d="M{wx} {wy + 56} h44" stroke="{trim}" stroke-width="8"/>')
    door = (f'<path d="M{x + w / 2 - 30} {base} V{base - 70} A30 30 0 0 1 {x + w / 2 + 30} {base - 70} V{base}Z" fill="#8A4A2A"/>'
            f'<circle cx="{x + w / 2 + 16}" cy="{base - 40}" r="4" fill="#FFD23F"/>')
    return (f'<rect x="{x}" y="{base - h}" width="{w}" height="{h}" fill="{wall}"/>'
            f'<rect x="{x - 8}" y="{base - h - 18}" width="{w + 16}" height="22" rx="4" fill="{roof}"/>'
            f'<path d="M{x} {base - h + 6} h{w}" stroke="#000" stroke-width="6" opacity=".08"/>'
            + "".join(win) + door)


def tree(x, base, s):
    return (f'<rect x="{x - 24 * s}" y="{base - 200 * s}" width="{48 * s}" height="{205 * s}" rx="{14 * s}" fill="#7A4E33"/>'
            f'<circle cx="{x}" cy="{base - 260 * s}" r="{125 * s}" fill="#2F9A4A"/><circle cx="{x - 95 * s}" cy="{base - 200 * s}" r="{90 * s}" fill="#2F9A4A"/>'
            f'<circle cx="{x + 95 * s}" cy="{base - 205 * s}" r="{95 * s}" fill="#2F9A4A"/><circle cx="{x - 20 * s}" cy="{base - 300 * s}" r="{80 * s}" fill="#48B85C"/>'
            f'<circle cx="{x - 50 * s}" cy="{base - 325 * s}" r="{40 * s}" fill="#6FD27A"/>'
            + "".join(f'<ellipse cx="{x + R.uniform(-130, 130) * s:.0f}" cy="{base - R.uniform(170, 330) * s:.0f}" rx="{11 * s}" ry="{15 * s}" fill="#FFB020"/>'
                      for _ in range(9)))


def flowers(x0, x1, y0, y1, n):
    out = []
    for _ in range(n):
        x, y = R.uniform(x0, x1), R.uniform(y0, y1)
        c = R.choice(["#FF8FB1", "#FFFFFF", "#FFD166", "#FF7A3C", "#C3A6FF"])
        s = R.uniform(6, 10)
        out.append(f'<g fill="{c}"><circle cx="{x:.0f}" cy="{y - s:.0f}" r="{s:.1f}"/><circle cx="{x - s:.0f}" cy="{y:.0f}" r="{s:.1f}"/>'
                   f'<circle cx="{x + s:.0f}" cy="{y:.0f}" r="{s:.1f}"/><circle cx="{x:.0f}" cy="{y + s:.0f}" r="{s:.1f}"/></g>'
                   f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{s * .7:.1f}" fill="#FFE066"/>')
    return "".join(out)


def cloud(cx, cy, s, op=0.95):
    return (f'<g fill="#fff" opacity="{op}"><ellipse cx="{cx}" cy="{cy}" rx="{140 * s}" ry="{48 * s}"/>'
            f'<ellipse cx="{cx - 90 * s}" cy="{cy + 10 * s}" rx="{90 * s}" ry="{38 * s}"/><ellipse cx="{cx + 95 * s}" cy="{cy + 8 * s}" rx="{100 * s}" ry="{38 * s}"/>'
            f'<circle cx="{cx - 10 * s}" cy="{cy - 34 * s}" r="{62 * s}"/><circle cx="{cx + 60 * s}" cy="{cy - 18 * s}" r="{44 * s}"/></g>')


# ---------------------------------------------------------------- text helpers
def rainbow_word(text, size, start=0):
    """Chunky rainbow letters, each with its own colour and a tiny bounce, like the video intro."""
    f = font(size, "Bold")
    letters, x, k = [], 0, start
    for ch in text:
        w = f.getlength(ch)
        if ch.strip():
            img = text_block(ch, size * 2, size, fill=RAINBOW[k % 6], stroke=(60, 30, 90))
            letters.append((img, x + w / 2, k))
            k += 1
        x += w
    hmax = max(i.height for i, _, _ in letters)
    out = Image.new("RGBA", (int(x + size), int(hmax + size * 0.3)), (0, 0, 0, 0))
    for img, cx, kk in letters:
        dy = int(size * 0.06 * math.sin(kk * 1.3))
        out.alpha_composite(img, (int(cx - img.width / 2 + size / 2), int(size * 0.12 + dy)))
    return out.crop(out.getbbox())


def ribbon(text, size, fill=(138, 72, 200), border=(255, 214, 90)):
    t = text_block(text, size * 30, size, fill=(255, 255, 255), stroke=(80, 30, 110), weight="SemiBold")
    rw, rh = t.width + size * 2, t.height + int(size * 0.5)
    img = Image.new("RGBA", (rw + 20, rh + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((10, 18, rw + 10, rh + 18), radius=rh // 2, fill=(60, 20, 80, 90))
    d.rounded_rectangle((10, 8, rw + 10, rh + 8), radius=rh // 2, fill=fill, outline=border, width=max(4, size // 9))
    img.alpha_composite(t, ((img.width - t.width) // 2, 8 + (rh - t.height) // 2))
    return img


def place(img, cid, x, feet, h, facing="right", mouth=True, action="idle", t=0.0):
    s = rig.Sprite(rig.load_character(cid), h, facing, "day", seed=3)
    s.blinks = [999]
    s.draw(img, t, x, feet, action, 0, mouth)


def sparkles(img, n, box, k=1.0):
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(n):
        x, y = R.uniform(box[0], box[2]), R.uniform(box[1], box[3])
        r = R.uniform(8, 18) * k
        d.polygon([(x, y - r), (x + r * .28, y - r * .28), (x + r, y), (x + r * .28, y + r * .28), (x, y + r),
                   (x - r * .28, y + r * .28), (x - r, y), (x - r * .28, y - r * .28)], fill=(255, 250, 210, 230))


# ================================================================ PROFILE PICTURE 800x800
P = 800
bg = f'''<defs><radialGradient id="g" cx="50%" cy="45%" r="60%"><stop offset="0" stop-color="#FFF3B0"/>
<stop offset=".55" stop-color="#FFC23A" stop-opacity="0"/></radialGradient>
<radialGradient id="v" cx="50%" cy="50%" r="55%"><stop offset=".7" stop-color="#E8541E" stop-opacity="0"/><stop offset="1" stop-color="#C2361A" stop-opacity=".6"/></radialGradient></defs>
{sunburst(400, 430, 760, 28, "#FFB627", "#FFCD4A", 4)}
<rect width="800" height="800" fill="url(#g)"/><rect width="800" height="800" fill="url(#v)"/>
{kite(150, 170, 0.75, "#FF4D6D", "#3CC8B4", -18)}{kite(660, 150, 0.6, "#3C8CFF", "#FFC928", 16)}'''
pp = vivid(svgtools.render(bg, P, P, P, P))
place(pp, "chintu", 560, 1070, 880, "left", mouth=True)
place(pp, "laddu", 315, 1090, 960, "right", mouth=True)
sparkles(pp, 10, (60, 60, 740, 360), 1.1)
pp.convert("RGB").save(OUT + "profile-picture-800.png")
prev = Image.new("RGBA", (P, P), (245, 245, 245, 255))
m = Image.new("L", (P, P), 0)
ImageDraw.Draw(m).ellipse((0, 0, P - 1, P - 1), fill=255)
prev.paste(pp, (0, 0), m)
prev.convert("RGB").save(OUT + "preview-profile-circle.png")
prev.resize((98, 98), Image.LANCZOS).convert("RGB").save(OUT + "preview-profile-small.png")

# ================================================================ BANNER 2560x1440 (safe area 1546x423)
BW, BH = 2560, 1440
houses = ""
x = -40
cols = [("#FF8FB1", "#D94E7A"), ("#FFD23F", "#E09A10"), ("#5FD3C6", "#2A9D8F"), ("#B79CFF", "#7A5CE0"),
        ("#FFA45B", "#E0601E"), ("#8ED081", "#4E9A44")]
i = 0
while x < BW:
    w = R.choice([200, 240, 280])
    h = R.choice([330, 380, 430, 480])
    wall, roof = cols[i % len(cols)]
    houses += house(x, 900, w, h, wall, roof)
    x += w + 6
    i += 1
banner = f'''<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3FA9F5"/>
<stop offset=".6" stop-color="#9ED8FF"/><stop offset="1" stop-color="#FFE9C2"/></linearGradient>
<radialGradient id="sun" cx="1280" cy="380" r="900" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#FFF6C8" stop-opacity=".95"/>
<stop offset=".25" stop-color="#FFE38A" stop-opacity=".45"/><stop offset="1" stop-color="#FFE38A" stop-opacity="0"/></radialGradient>
<linearGradient id="road" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F2D29B"/><stop offset="1" stop-color="#E0B46E"/></linearGradient>
<linearGradient id="grass" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7CD36A"/><stop offset="1" stop-color="#3F9A48"/></linearGradient></defs>
<rect width="{BW}" height="{BH}" fill="url(#sky)"/><rect width="{BW}" height="{BH}" fill="url(#sun)"/>
{cloud(260, 220, 1.2)}{cloud(980, 150, 0.8, .9)}{cloud(2240, 250, 1.1)}{cloud(1700, 120, 0.7, .85)}
{kite(420, 420, 1.0, "#FF4D6D", "#FFC928", -15)}{kite(2140, 470, 1.1, "#3C8CFF", "#FF5470", 12)}{kite(1820, 230, 0.7, "#FFC928", "#3CC8B4", -8)}{kite(720, 200, 0.6, "#7A6CFF", "#FF8A3C", 10)}
<path d="M420 490 C520 700 600 820 700 930" stroke="#fff" stroke-width="2" opacity=".6" fill="none"/>
{houses}
{bunting(-20, 560, 1300, 600, 70, 26, 40)}{bunting(1260, 600, 2600, 550, 70, 26, 40)}
<path d="M0 900 H{BW} V{BH} H0Z" fill="url(#road)"/>
<path d="M0 900 H{BW} v14 H0Z" fill="#000" opacity=".08"/>
<path d="M0 1080 C600 1030 1900 1050 {BW} 1060 V{BH} H0Z" fill="url(#grass)"/>
{tree(200, 1010, 1.1)}{tree(2380, 1010, 1.15)}
{flowers(0, BW, 1090, 1400, 140)}'''
bn = vivid(svgtools.render(banner, BW, BH, BW, BH))
sparkles(bn, 18, (200, 80, 2360, 480), 1.4)
# gang on the left of the safe area (x 507-2053, y 508-931)
place(bn, "pinky", 600, 950, 340, "right")
place(bn, "chintu", 738, 952, 352, "right")
place(bn, "laddu", 885, 958, 345, "left")
place(bn, "dadaji", 1040, 952, 415, "left")
place(bn, "golu", 1150, 958, 170, "left", mouth=False)
# logo on the right of the safe area, on a soft glow so it reads over the houses
l1 = rainbow_word("Little Lantern", 108)
l2 = rainbow_word("Stories", 108, start=13)
rb = ribbon("Funny stories  \u2022  New every day!", 36)
cx = 1640
glow = Image.new("RGBA", bn.size, (0, 0, 0, 0))
ImageDraw.Draw(glow).rounded_rectangle((cx - 450, 520, cx + 450, 915), radius=90, fill=(255, 255, 255, 150))
bn.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30)))
y = 545
for img in (l1, l2):
    bn.alpha_composite(img, (int(cx - img.width / 2), y))
    y += img.height - 6
bn.alpha_composite(rb, (int(cx - rb.width / 2), y + 10))
bn.convert("RGB").save(OUT + "channel-banner-2560x1440.png")
g = bn.copy()
d = ImageDraw.Draw(g)
d.rectangle((507, 508, 2053, 931), outline=(255, 0, 0, 255), width=5)
g.convert("RGB").resize((1280, 720)).save(OUT + "preview-banner-safe-area.jpg")
print("ok")
