"""Render (and optionally upload) every episode that hasn't been uploaded yet.

    python -m kidsvideo.run                      # render + upload all pending episodes
    python -m kidsvideo.run --no-upload          # render only
    python -m kidsvideo.run --episode episodes/2026-10-07
"""
import argparse
import json
import os
import sys
from pathlib import Path

from . import ROOT
from .check import validate
from .render import load_config, render_episode


def pending_episodes():
    eps = sorted(p.parent for p in (ROOT / "episodes").glob("*/story.json"))
    return [e for e in eps if not (e / "upload.json").exists()]


def record_history(ep: Path, story: dict, info: dict | None):
    path = ROOT / "data" / "history.json"
    hist = json.loads(path.read_text()) if path.exists() else []
    hist.append({"date": story.get("date", ep.name), "title": story["title"], "theme": story.get("theme", ""), "learning": story.get("learning", ""),
                 "moral": story["moral"], "cast": sorted({pl["id"] for sc in story["scenes"] for pl in sc.get("characters", [])}),
                 "summary": story["description"], "video": (info or {}).get("url")})
    path.write_text(json.dumps(hist, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", help="episode folder (default: all pending in episodes/)")
    ap.add_argument("--no-upload", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    eps = [Path(args.episode)] if args.episode else pending_episodes()
    if not eps:
        print("No pending episodes.")
        return
    summary = []
    failed = False
    for ep in eps:
        story = json.loads((ep / "story.json").read_text())
        errs = validate(story)
        soft = ("story is short", "missing 'learning'", "no learning popups")
        hard = [e for e in errs if not e.startswith(soft)]
        if hard:
            print(f"✗ {ep.name}: story.json has problems:\n  - " + "\n  - ".join(hard))
            failed = True
            continue
        print(f"▶ Rendering {ep.name}: {story['title']}")
        stage = "render"
        try:
            meta = render_episode(ep)
            print(f"  video ready: {meta['duration']:.0f}s")
            info = None
            if not args.no_upload:
                stage = "upload"
                from .upload import upload
                info = upload(ep, story, cfg)
                record_history(ep, story, info)
        except BaseException as e:  # show the reason on the GitHub run page, then fail the run
            import traceback
            tb = traceback.format_exc().strip().splitlines()
            where = next((l.strip() for l in reversed(tb) if l.strip().startswith("File")), "")
            print(f"::error title={ep.name} {stage} failed::{type(e).__name__}: {str(e)[:500]} | {where}")
            raise
        summary.append(f"| {ep.name} | {story['title']} | {meta['duration']:.0f}s | {(info or {}).get('url', 'not uploaded')} |")
    if os.environ.get("GITHUB_STEP_SUMMARY") and summary:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("| Episode | Title | Length | YouTube |\n|---|---|---|---|\n" + "\n".join(summary) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
