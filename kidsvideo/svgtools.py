"""Safe SVG -> PIL rendering."""
import io
import re

import cairosvg
from PIL import Image

SVG_NS = 'xmlns="http://www.w3.org/2000/svg"'

_FORBIDDEN = [
    (re.compile(r"<script\b.*?</script>", re.S | re.I), "script"),
    (re.compile(r"<foreignObject\b.*?</foreignObject>", re.S | re.I), "foreignObject"),
    (re.compile(r"<image\b[^>]*>", re.I), "image"),
]
_EXTERNAL = re.compile(r"""(?:xlink:)?href\s*=\s*["'](?!#)[^"']*["']""", re.I)
_URL_EXT = re.compile(r"url\(\s*['\"]?(?!#)[^)]*\)", re.I)


def sanitize(svg: str) -> tuple[str, list[str]]:
    """Strip anything that could load external content. Returns (svg, warnings)."""
    warnings = []
    for pat, name in _FORBIDDEN:
        if pat.search(svg):
            warnings.append(f"removed <{name}>")
            svg = pat.sub("", svg)
    if _EXTERNAL.search(svg):
        warnings.append("removed external href")
        svg = _EXTERNAL.sub("", svg)
    if _URL_EXT.search(svg):
        warnings.append("removed external url()")
        svg = _URL_EXT.sub("none", svg)
    return svg, warnings


def wrap(inner_or_full: str, view_w: float, view_h: float) -> str:
    """Accept either a full <svg> document or inner markup and return a full document."""
    s = inner_or_full.strip()
    if s.startswith("<svg"):
        if "xmlns=" not in s[:300]:
            s = s.replace("<svg", f"<svg {SVG_NS}", 1)
        return s
    return (f'<svg {SVG_NS} xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {view_w} {view_h}" width="{view_w}" height="{view_h}">{s}</svg>')


def render(svg: str, width: int, height: int, view_w: float = 1920, view_h: float = 1080) -> Image.Image:
    """Render SVG (full doc or inner markup) to an RGBA image of the given pixel size."""
    doc, _ = sanitize(wrap(svg, view_w, view_h))
    png = cairosvg.svg2png(bytestring=doc.encode("utf-8"), output_width=width,
                           output_height=height, unsafe=False)
    return Image.open(io.BytesIO(png)).convert("RGBA")
