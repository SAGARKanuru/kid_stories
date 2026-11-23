"""Render (and optionally upload) every episode that hasn't been uploaded yet.

    python -m kidsvideo.run                      # render + upload all pending episodes
    python -m kidsvideo.run --no-upload          # render only
    python -m kidsvideo.run --episode episodes/2026-10-07
"""
import argparse
import json
import os
import subprocess
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


def commit_record(ep: Path):
    """Save the upload record to the repo right away, so a later timeout can never cause a re-upload."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    run = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    run("config", "user.name", "kids-story-bot")
    run("config", "user.email", "kids-story-bot@users.noreply.github.com")
    run("add", "data/history.json", str(ep / "upload.json"))
    if run("diff", "--cached", "--quiet").returncode == 0:
        return
    run("commit", "-m", f"Record uploaded episode {ep.name} [skip ci]")
    err = ""
    for i in range(5):
        r = run("push", "origin", "HEAD:main")
        if r.returncode == 0:
            return
        err = (r.stderr or r.stdout)[-300:]
        p = run("pull", "--rebase", "--autostash", "-q", "origin", "main")
        if p.returncode != 0:
            err += " | " + (p.stderr or p.stdout)[-300:]
            run("rebase", "--abort")
        import time
        time.sleep(3 * (i + 1))
    print(f"::warning::could not push the upload record for {ep.name}: {err}")


def add_short(ep: Path, story: dict, cfg: dict, info: dict):
    """Upload the episode's Short and note it in upload.json. A failed Short never fails the episode."""
    from .upload import upload_short, UploadLimit
    try:
        sh = upload_short(ep, story, cfg, info["url"])
        info["short"] = sh
        (ep / "upload.json").write_text(json.dumps(info, indent=2))
        commit_record(ep)
    except UploadLimit:
        print(f"::warning title=YouTube daily limit::Short for {ep.name} will upload on the next run.")
    except Exception as e:
        print(f"::warning title={ep.name} Short failed::{str(e)[:300]}")


def pending_shorts(cfg) -> list:
    """Episodes already on YouTube (since shorts were switched on) that still have no Short."""
    since = str(cfg["youtube"].get("shorts_from", "9999"))
    out = []
    for f in sorted((ROOT / "episodes").glob("*/upload.json")):
        ep = f.parent
        try:
            info = json.loads(f.read_text())
        except Exception:
            continue
        if ep.name >= since and not info.get("short") and info.get("url"):
            out.append(ep)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", help="episode folder (default: all pending in episodes/)")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--max", type=int, default=int(os.environ.get("MAX_EPISODES", "3")),
                    help="most episodes to render+upload in one run (each = video + Short; YouTube allows ~6 uploads a day)")
    args = ap.parse_args()

    cfg = load_config()
    eps = [Path(args.episode)] if args.episode else pending_episodes()[::-1]  # newest first, then the backlog
    summary = []
    failed = False
    rendered = 0
    if not args.no_upload and cfg["youtube"].get("delete_duplicates"):
        from .upload import remove_duplicates
        protect = set()
        for f in (ROOT / "episodes").glob("*/upload.json"):
            try:
                protect.add(json.loads(f.read_text())["video_id"])
            except Exception:
                pass
        titles = set()
        for f in (ROOT / "episodes").glob("*/story.json"):
            try:
                titles.add(json.loads(f.read_text())["title"][:100])
            except Exception:
                pass
        hist = ROOT / "data" / "history.json"
        if hist.exists():
            titles |= {h["title"][:100] for h in json.loads(hist.read_text()) if h.get("title")}
        try:
            gone = remove_duplicates(protect, titles)
            if gone:
                print(f"Removed {len(gone)} duplicate video(s) from the channel")
        except Exception as e:
            print(f"::warning::duplicate clean-up skipped: {str(e)[:200]}")
    for ep in eps:
        if not args.no_upload and not args.episode:
            from .upload import already_uploaded
            story = json.loads((ep / "story.json").read_text())
            try:
                found = already_uploaded(story)
            except Exception as e:
                print(f"::warning::could not check the channel for '{story['title']}': {str(e)[:200]}")
                found = None
            if found:
                (ep / "upload.json").write_text(json.dumps(found, indent=2))
                record_history(ep, story, found)
                commit_record(ep)
                print(f"✓ {ep.name} is already on YouTube ({found['url']}); recorded, not uploaded again")
                summary.append(f"| {ep.name} | {story['title']} | - | {found['url']} (already there) |")
                continue
        if rendered >= args.max:
            print(f"… {ep.name} left for the next run (limit {args.max} per run)")
            continue
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
                commit_record(ep)
                if meta.get("short"):
                    add_short(ep, story, cfg, info)
            rendered += 1
        except BaseException as e:
            if type(e).__name__ == "UploadLimit":
                print(f"::warning title=YouTube daily limit::YouTube won't take more uploads today ({str(e)[:200]}). "
                      "The rest will upload on the next run.")
                break  # show the reason on the GitHub run page, then fail the run
            import traceback
            tb = traceback.format_exc().strip().splitlines()
            where = next((l.strip() for l in reversed(tb) if l.strip().startswith("File")), "")
            print(f"::error title={ep.name} {stage} failed::{type(e).__name__}: {str(e)[:500]} | {where}")
            raise
        summary.append(f"| {ep.name} | {story['title']} | {meta['duration']:.0f}s | {(info or {}).get('url', 'not uploaded')} |")
    if not args.no_upload and not args.episode and cfg["youtube"].get("shorts"):
        for ep in pending_shorts(cfg)[::-1]:
            if rendered >= args.max:
                break
            story = json.loads((ep / "story.json").read_text())
            info = json.loads((ep / "upload.json").read_text())
            print(f"▶ Making the Short for {ep.name}: {story['title']}")
            try:
                meta = render_episode(ep)
            except Exception as e:
                print(f"::warning title={ep.name} Short failed::{str(e)[:300]}")
                continue
            rendered += 1
            if meta.get("short"):
                add_short(ep, story, cfg, info)
    if os.environ.get("GITHUB_STEP_SUMMARY") and summary:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("| Episode | Title | Length | YouTube |\n|---|---|---|---|\n" + "\n".join(summary) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
