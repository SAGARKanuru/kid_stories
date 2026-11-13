import sys, random, math
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from PIL import Image, ImageFilter, ImageDraw
from kidsvideo import rig, svgtools
from kidsvideo.render import text_block, font
OUT = sys.path[0] + "/branding/"
R = random.Random(7)

def lantern(cx, cy, s, glow=True):
    g = ""
    if glow:
        g = f'<circle cx="{cx}" cy="{cy}" r="{260*s}" fill="url(#lg)"/>'
    return f'''{g}
<path d="M{cx} {cy-170*s} V{cy-120*s}" stroke="#5A3A2A" stroke-width="{8*s}"/>
<rect x="{cx-50*s}" y="{cy-125*s}" width="{100*s}" height="{26*s}" rx="{8*s}" fill="#C0392B"/>
<ellipse cx="{cx}" cy="{cy}" rx="{105*s}" ry="{105*s}" fill="url(#lb)"/>
<path d="M{cx-60*s} {cy-92*s} Q{cx-100*s} {cy} {cx-60*s} {cy+92*s} M{cx} {cy-104*s} V{cy+104*s} M{cx+60*s} {cy-92*s} Q{cx+100*s} {cy} {cx+60*s} {cy+92*s}" stroke="#E2572E" stroke-width="{6*s}" fill="none" opacity=".55"/>
<ellipse cx="{cx-35*s}" cy="{cy-40*s}" rx="{28*s}" ry="{40*s}" fill="#FFF8D8" opacity=".55"/>
<rect x="{cx-50*s}" y="{cy+98*s}" width="{100*s}" height="{24*s}" rx="{8*s}" fill="#C0392B"/>
<path d="M{cx} {cy+122*s} V{cy+150*s}" stroke="#E8A13A" stroke-width="{8*s}"/>
<path d="M{cx-16*s} {cy+150*s} h{32*s} l{-6*s} {50*s} h{-20*s}z" fill="#F2B544"/>'''

DEFS = '''<defs>
<radialGradient id="lg"><stop offset="0" stop-color="#FFE08A" stop-opacity=".95"/><stop offset=".35" stop-color="#FFB85A" stop-opacity=".45"/><stop offset="1" stop-color="#FF9A3C" stop-opacity="0"/></radialGradient>
<radialGradient id="lb" cx="45%" cy="40%" r="65%"><stop offset="0" stop-color="#FFF4B8"/><stop offset=".5" stop-color="#FFC24A"/><stop offset="1" stop-color="#F07A2A"/></radialGradient>
</defs>'''

def stars(w, h, n, ymax):
    out = []
    for _ in range(n):
        x, y, r = R.uniform(0, w), R.uniform(0, ymax), R.uniform(1.5, 4.5)
        op = R.uniform(.5, 1)
        if R.random() < .15:
            out.append(f'<path d="M{x} {y-r*3} L{x+r*.7} {y-r*.7} L{x+r*3} {y} L{x+r*.7} {y+r*.7} L{x} {y+r*3} L{x-r*.7} {y+r*.7} L{x-r*3} {y} L{x-r*.7} {y-r*.7}Z" fill="#FFF6C8" opacity="{op:.2f}"/>')
        else:
            out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.1f}" fill="#FFFFFF" opacity="{op:.2f}"/>')
    return "".join(out)

def fireflies(img, n, box, k=1.0):
    W, H = img.size
    layer = Image.new("RGBA", img.size, (0,0,0,0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y = R.uniform(box[0], box[2]), R.uniform(box[1], box[3]); r = R.uniform(4, 9)*k
        d.ellipse((x-r*3, y-r*3, x+r*3, y+r*3), fill=(255, 230, 120, 50))
        d.ellipse((x-r*.6, y-r*.6, x+r*.6, y+r*.6), fill=(255, 250, 200, 240))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(2*k)))

def place(img, cid, x, feet, h, facing="right", mouth=False):
    s = rig.Sprite(rig.load_character(cid), h, facing, "day", seed=3)
    s.blinks = [999]
    s.draw(img, 0.0, x, feet, "idle", 0, mouth)

# ================= PROFILE PICTURE 800x800 =================
P = 800
sky = f'''{DEFS}<defs><radialGradient id="bg" cx="50%" cy="38%" r="75%"><stop offset="0" stop-color="#4B3B8F"/><stop offset=".6" stop-color="#2C2466"/><stop offset="1" stop-color="#1A1540"/></radialGradient>
<linearGradient id="hill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5FB86A"/><stop offset="1" stop-color="#3C8C4E"/></linearGradient></defs>
<rect width="800" height="800" fill="url(#bg)"/>{stars(800,800,70,520)}
<defs><mask id="m1"><rect width="800" height="800" fill="#fff"/><circle cx="635" cy="152" r="52" fill="#000"/></mask></defs><circle cx="610" cy="170" r="70" fill="#FFF3C4" opacity=".18"/><circle cx="610" cy="170" r="58" fill="#FFF3C4" mask="url(#m1)"/>
{lantern(250, 250, 0.95)}
<path d="M0 640 C200 585 600 585 800 640 V800 H0Z" fill="url(#hill)"/>
<path d="M0 640 C200 585 600 585 800 640 L800 652 C600 600 200 600 0 652Z" fill="#8BD58A" opacity=".6"/>'''
pp = svgtools.render(sky, P, P, 800, 800)
# lantern string from Pip's paw
place(pp, "golu", 545, 728, 175, "left")
place(pp, "laddu", 370, 742, 460, "right", mouth=True)
fireflies(pp, 6, (60, 420, 300, 600)); fireflies(pp, 4, (600, 260, 760, 560))
# circular mask preview
pp.convert("RGB").save(OUT + "profile-picture-800.png")
prev = Image.new("RGBA", (P, P), (240, 240, 240, 255))
m = Image.new("L", (P, P), 0); ImageDraw.Draw(m).ellipse((0, 0, P-1, P-1), fill=255)
prev.paste(pp, (0, 0), m)
prev.convert("RGB").save(OUT + "preview-profile-circle.png")

# ================= BANNER 2560x1440 (safe area 1546x423 centred) =================
BW, BH = 2560, 1440
def tree(x, base, s, c=("#2F6E4A","#3C845A","#4E9A6A")):
    return (f'<rect x="{x-20*s}" y="{base-180*s}" width="{40*s}" height="{185*s}" rx="{12*s}" fill="#4A3426"/>'
            f'<circle cx="{x}" cy="{base-240*s}" r="{115*s}" fill="{c[0]}"/><circle cx="{x-80*s}" cy="{base-185*s}" r="{80*s}" fill="{c[0]}"/>'
            f'<circle cx="{x+85*s}" cy="{base-190*s}" r="{85*s}" fill="{c[0]}"/><circle cx="{x-20*s}" cy="{base-275*s}" r="{75*s}" fill="{c[1]}"/>'
            f'<circle cx="{x-45*s}" cy="{base-300*s}" r="{38*s}" fill="{c[2]}"/>')
def tufts(x0,x1,yb,n,h0,h1,cols):
    o=[]
    for _ in range(n):
        x=R.uniform(x0,x1);h=R.uniform(h0,h1);w=R.uniform(12,24);l=R.uniform(-30,30)
        o.append(f'<path d="M{x-w:.0f} {yb} Q{x+l*.3:.0f} {yb-h*.6:.0f} {x+l:.0f} {yb-h:.0f} Q{x+w*.3:.0f} {yb-h*.5:.0f} {x+w:.0f} {yb}Z" fill="{R.choice(cols)}"/>')
    return "".join(o)
def flowers(x0,x1,y0,y1,n):
    o=[]
    for _ in range(n):
        x,y=R.uniform(x0,x1),R.uniform(y0,y1);c=R.choice(["#FF8FB1","#FFFFFF","#FFD166","#C3A6FF"]);s=R.uniform(5,9)
        o.append(f'<g fill="{c}"><circle cx="{x:.0f}" cy="{y-s:.0f}" r="{s:.1f}"/><circle cx="{x-s:.0f}" cy="{y:.0f}" r="{s:.1f}"/><circle cx="{x+s:.0f}" cy="{y:.0f}" r="{s:.1f}"/><circle cx="{x:.0f}" cy="{y+s:.0f}" r="{s:.1f}"/></g><circle cx="{x:.0f}" cy="{y:.0f}" r="{s*.7:.1f}" fill="#FFE066"/>')
    return "".join(o)

banner_svg = f'''{DEFS}<defs><linearGradient id="bs" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2A2163"/><stop offset=".45" stop-color="#6A4FA8"/><stop offset=".75" stop-color="#E88AA6"/><stop offset="1" stop-color="#FFC98A"/></linearGradient>
<linearGradient id="h1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7C6BB0"/><stop offset="1" stop-color="#5C4F92"/></linearGradient>
<linearGradient id="h2" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5DAE6A"/><stop offset="1" stop-color="#3B8650"/></linearGradient>
<linearGradient id="h3" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#78C46E"/><stop offset="1" stop-color="#4E9A4E"/></linearGradient></defs>
<rect width="{BW}" height="{BH}" fill="url(#bs)"/>{stars(BW,BH,180,700)}
<defs><mask id="m2"><rect width="2560" height="1440" fill="#fff"/><circle cx="2185" cy="305" r="72" fill="#000"/></mask></defs><circle cx="2150" cy="330" r="98" fill="#FFF3C4" opacity=".15"/><circle cx="2150" cy="330" r="80" fill="#FFF3C4" mask="url(#m2)"/>
<path d="M0 900 C300 820 600 870 900 850 C1250 825 1500 880 1800 850 C2100 820 2350 860 2560 840 V1440 H0Z" fill="url(#h1)"/>
{tree(330, 960, .55)}{tree(2260, 950, .6)}
<path d="M0 960 C400 905 800 940 1280 930 C1760 920 2150 950 2560 915 V1440 H0Z" fill="url(#h2)"/>
<path d="M0 960 C400 905 800 940 1280 930 C1760 920 2150 950 2560 915 L2560 930 C2150 965 1760 935 1280 945 C800 955 400 920 0 975Z" fill="#9FDB8E" opacity=".5"/>
{lantern(470, 560, .75)}{lantern(2090, 600, .6)}{lantern(1280, 300, .5)}
{flowers(0, 2560, 990, 1200, 90)}
{tufts(0, 2560, 1440, 80, 40, 110, ["#3B8650","#4A9A5A","#2F7444"])}'''
bn = svgtools.render(banner_svg, BW, BH, BW, BH)
fireflies(bn, 40, (100, 420, 2460, 1000), 1.3)
# characters on the left of the safe area (x 507-2053, y 508-931)
place(bn, "dadaji", 1000, 928, 400, "left")
place(bn, "pinky", 580, 932, 330, "right", mouth=True)
place(bn, "chintu", 715, 936, 345, "right")
place(bn, "laddu", 860, 940, 335, "left", mouth=True)
place(bn, "golu", 1100, 936, 175, "left")
# title on the right of the safe area
t1 = text_block("Little Lantern Stories", 900, 118, fill=(255, 236, 140), stroke=(52, 30, 90))
t2 = text_block("A new funny story every day!", 900, 58, fill=(255, 255, 255), stroke=(52, 30, 90), weight="SemiBold")
tx = 1130 + (2050 - 1130 - t1.width) // 2
ty = 530
bn.alpha_composite(t1, (max(1120, tx), ty))
bn.alpha_composite(t2, (1130 + (2050 - 1130 - t2.width) // 2, ty + t1.height - 28))
bn.convert("RGB").save(OUT + "channel-banner-2560x1440.png")
# safe-area guide preview
g = bn.copy(); d = ImageDraw.Draw(g)
d.rectangle((507, 508, 2053, 931), outline=(255, 0, 0, 255), width=4)
d.rectangle((0, 0, BW, BH), outline=(0, 255, 255, 255), width=1)
g.convert("RGB").resize((1280, 720)).save(OUT + "preview-banner-safe-area.jpg")
print("ok")
