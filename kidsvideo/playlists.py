"""Topic playlists on the channel: created when missing, filled automatically after each upload, and
back-filled for older videos a few at a time (YouTube allows ~10,000 API units a day; each add costs 50).

Progress lives in data/playlists.json, so nothing is ever added twice.
"""
import json
import re
import time

from googleapiclient.errors import HttpError

from . import ROOT

STATE = ROOT / "data" / "playlists.json"

PLAYLISTS = {
    "Learn Counting & Numbers": "Count along with Laddu, Chintu and friends! Funny cartoon stories that teach "
                                "counting and numbers for kids aged 3 to 8.",
    "Learn Colours & Shapes": "Rainbow colours, circles, squares, triangles, stars and patterns in funny, kind "
                              "cartoon stories for kids aged 3 to 8.",
    "Learn About Animals": "Animal sounds, baby animals, what animals eat, bugs and insects in funny cartoon "
                           "stories for kids aged 3 to 8.",
    "Learn Words & Letters": "Letters, rhyming words, opposites, big and small, and the days of the week in funny "
                             "cartoon stories for kids aged 3 to 8.",
    "Learn About Nature & Science": "Weather, seasons, day and night, how plants grow, and what sinks or floats in "
                                    "funny cartoon stories for kids aged 3 to 8.",
    "Healthy Habits & Feelings": "The five senses, our bodies, healthy food and habits, road safety and big "
                                 "feelings in gentle cartoon stories for kids aged 3 to 8.",
    "Laddu & Chintu Comedy": "Laddu, Chintu, Pinky, Dadaji and Golu the goat in funny, kind adventures in Masti "
                             "Nagar. A new episode every day!",
    "Pip & Tumble Stories": "Pip the fox, Tumble the elephant and Nana Hoot in gentle animated moral stories for "
                            "kids aged 3 to 8.",
    "Bedtime Stories": "Calm, gentle cartoon stories about patience, kindness and gratitude, perfect before bed "
                       "for kids aged 3 to 8.",
    "Moral Stories for Kids": "Every Little Lantern Stories episode: funny animated moral stories that teach "
                              "something new, for kids aged 3 to 8.",
    "Laddu & Chintu Shorts": "Quick laughs and learning with Laddu, Chintu and Golu the goat. Watch the full "
                             "stories on our channel!",
    "Pip & Tumble Shorts": "Quick, gentle moments with Pip the fox, Tumble the elephant and Nana Hoot. Watch the full "
                           "stories on our channel!",
}

LEARNING = [
    ("Learn Counting & Numbers", r"count|number"),
    ("Learn Colours & Shapes", r"colou?r|shape|pattern"),
    ("Learn About Animals", r"animal|insect|bug"),
    ("Learn Words & Letters", r"letter|rhym|opposite|big and small|days of the week"),
    ("Learn About Nature & Science", r"weather|season|day and night|plant|sink|float"),
    ("Healthy Habits & Feelings", r"sense|body|healthy|fruit|vegetable|road|feeling"),
]
GENTLE = {"patience", "kindness", "gratitude", "managing big feelings", "being yourself", "caring for nature",
          "sharing", "making a new friend", "saying sorry"}
OLD_CAST = {"pip", "tumble", "nana", "hazel"}
NEW_CAST = {"laddu", "chintu", "pinky", "dadaji", "golu"}


def classify(entry: dict) -> list:
    """Which playlists a full episode belongs in."""
    names = ["Moral Stories for Kids"]
    learning = (entry.get("learning") or "").lower()
    for name, pat in LEARNING:
        if re.search(pat, learning):
            names.append(name)
            break
    cast = set(entry.get("cast") or [])
    if cast & NEW_CAST:
        names.append("Laddu & Chintu Comedy")
    elif cast & OLD_CAST:
        names.append("Pip & Tumble Stories")
    if (entry.get("theme") or "").lower() in GENTLE:
        names.append("Bedtime Stories")
    return names


def _vid(url):
    return (url or "").rstrip("/").split("/")[-1].split("=")[-1]


def _load():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"ids": {}, "done": {}}


def _save(state):
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True))


def wanted() -> list:
    """(video_id, [playlist names], label) for every video the channel should have in playlists, newest first."""
    out = []
    hist_path = ROOT / "data" / "history.json"
    hist = json.loads(hist_path.read_text()) if hist_path.exists() else []
    for h in reversed(hist):
        if h.get("video"):
            out.append((_vid(h["video"]), classify(h), h.get("title", "")))
    cast_by_date = {h.get("date"): set(h.get("cast") or []) for h in hist}
    seen = set()

    def short_list(date):
        return ["Pip & Tumble Shorts"] if cast_by_date.get(date, set()) & OLD_CAST else ["Laddu & Chintu Shorts"]

    for f in sorted((ROOT / "episodes").glob("*/upload.json"), reverse=True):
        try:
            info = json.loads(f.read_text())
        except Exception:
            continue
        if info.get("short", {}).get("url"):
            v = _vid(info["short"]["url"])
            seen.add(v)
            out.append((v, short_list(f.parent.name), f.parent.name + " Short"))
    sp = ROOT / "data" / "shorts.json"
    if sp.exists():
        for date, sh in sorted(json.loads(sp.read_text()).items(), reverse=True):
            if sh.get("url") and _vid(sh["url"]) not in seen:
                out.append((_vid(sh["url"]), short_list(date), date + " Short"))
    return out


def ensure(yt, state, names) -> dict:
    """Find or create the playlists we need; ids are cached in data/playlists.json."""
    ids = state.setdefault("ids", {})
    missing = [n for n in names if n not in ids]
    if not missing:
        return ids
    token, existing = None, {}
    while True:
        r = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=token).execute()
        for p in r.get("items", []):
            existing[p["snippet"]["title"]] = p["id"]
        token = r.get("nextPageToken")
        if not token:
            break
    for n in missing:
        if n in existing:
            ids[n] = existing[n]
            continue
        p = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": n, "description": PLAYLISTS[n], "defaultLanguage": "en"},
            "status": {"privacyStatus": "public"}}).execute()
        ids[n] = p["id"]
        print(f"  created playlist '{n}'")
    return ids


def sync(max_adds: int = 60) -> int:
    """Add videos to their playlists until max_adds is reached. Returns how many were added."""
    from .upload import UploadLimit, _client
    state = _load()
    done = state.setdefault("done", {})
    todo = []
    for vid, names, label in wanted():
        rest = [n for n in names if n not in done.get(vid, [])]
        if rest:
            todo.append((vid, rest, label))
    if not todo:
        return 0
    yt = _client()
    ids = ensure(yt, state, sorted({n for _, names, _ in todo for n in names}))
    _save(state)
    added = 0
    try:
        for vid, names, label in todo:
            for n in names:
                if added >= max_adds:
                    raise StopIteration
                try:
                    yt.playlistItems().insert(part="snippet", body={"snippet": {
                        "playlistId": ids[n], "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
                    added += 1
                except HttpError as e:
                    if e.resp.status == 403 and "quotaExceeded" in str(e):
                        raise UploadLimit(str(e)[:200]) from None
                    if e.resp.status == 404 and "playlistNotFound" in str(e):
                        ids.pop(n, None)  # playlist was deleted in Studio: recreate next run
                        continue
                    if e.resp.status in (400, 404):  # video removed/unavailable: don't keep retrying it
                        print(f"  skipped {label} -> {n}: {str(e)[:120]}")
                    else:
                        raise
                done.setdefault(vid, []).append(n)
                time.sleep(0.3)
    except (StopIteration, UploadLimit) as e:
        if isinstance(e, UploadLimit):
            print("::notice::YouTube's daily limit reached while filling playlists; the rest continue next run.")
    finally:
        _save(state)
    left = sum(len([n for n in names if n not in done.get(vid, [])]) for vid, names, _ in todo)
    print(f"Playlists: added {added} video(s); {left} still to add on later runs")
    return added
