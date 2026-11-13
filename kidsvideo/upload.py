"""Upload a rendered episode to YouTube with the Data API v3 (OAuth refresh token)."""
import json
import os
import time
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]


def _client():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"].strip().strip('"'),
        client_id=os.environ["YT_CLIENT_ID"].strip().strip('"'),
        client_secret=os.environ["YT_CLIENT_SECRET"].strip().strip('"'),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except RefreshError as e:
        msg = str(e)
        hint = "Check the YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN secrets."
        if "deleted_client" in msg:
            hint = ("The OAuth client in YT_CLIENT_ID was deleted in Google Cloud. Create a new Desktop client, "
                    "get a NEW refresh token with it, and update all three YT_* secrets.")
        elif "invalid_client" in msg:
            hint = "YT_CLIENT_ID or YT_CLIENT_SECRET is wrong (typo, extra space, or from a different client)."
        elif "invalid_grant" in msg:
            hint = ("YT_REFRESH_TOKEN is not valid for this client. It must be made with the SAME client as "
                    "YT_CLIENT_ID (a new client needs a new token), start with '1//', and have no quotes or spaces. "
                    "It also stops working if access was revoked, or after 7 days if the consent screen is still "
                    "in 'Testing' (publish the app to avoid that).")
        raise SystemExit(f"YouTube login failed: {msg}\n  -> {hint}") from None
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def build_description(story: dict, cfg: dict) -> str:
    tags = " ".join("#" + t.replace(" ", "") for t in story.get("tags", [])[:5])
    return (
        f"{story['description']}\n\n"
        f"🌟 Moral of the story: {story['moral']}\n\n"
        f"A new animated story every day from {cfg['channel_name']} — gentle, original tales for "
        f"{cfg['story']['audience']}.\n\n"
        "This story, its artwork, music and voices were created with the help of AI tools and reviewed for children.\n\n"
        f"{tags}"
    )[:4900]


class UploadLimit(Exception):
    """YouTube refused more uploads today (daily quota / upload limit). Try again tomorrow."""


_RECENT = {}


def recent_uploads(yt, pages: int = 6) -> list[dict]:
    """Titles and ids of the channel's most recent uploads (newest first), cached per run."""
    if "items" in _RECENT:
        return _RECENT["items"]
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    pl = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items, token = [], None
    for _ in range(pages):
        r = yt.playlistItems().list(part="snippet", playlistId=pl, maxResults=50, pageToken=token).execute()
        for it in r.get("items", []):
            sn = it["snippet"]
            items.append({"id": sn["resourceId"]["videoId"], "title": sn["title"], "at": sn.get("publishedAt", "")})
        token = r.get("nextPageToken")
        if not token:
            break
    _RECENT["items"] = items
    return items


def already_uploaded(story: dict) -> dict | None:
    """If a video with this exact title is already on the channel, return its record instead of uploading again."""
    yt = _client()
    title = story["title"][:100]
    matches = [v for v in recent_uploads(yt) if v["title"] == title]
    if not matches:
        return None
    keep = sorted(matches, key=lambda v: v["at"])[0]  # the first copy
    extra = [v["id"] for v in matches if v["id"] != keep["id"]]
    if extra:
        print(f"::warning title=Duplicate uploads::'{title}' is on the channel {len(matches)} times. Keeping "
              f"https://youtu.be/{keep['id']}; delete these copies in YouTube Studio: "
              + ", ".join(f"https://youtu.be/{x}" for x in extra))
    return {"video_id": keep["id"], "url": f"https://youtu.be/{keep['id']}", "privacy": "unknown",
            "uploaded_at": keep["at"], "note": "found already on the channel; not uploaded again",
            "duplicates": [f"https://youtu.be/{x}" for x in extra]}


def remove_duplicates(protect: set) -> list:
    """Delete extra copies of videos uploaded more than once (same exact title).
    Keeps the copy an episode record points to (protect), otherwise the first one uploaded."""
    yt = _client()
    groups = {}
    for v in recent_uploads(yt):
        groups.setdefault(v["title"], []).append(v)
    deleted = []
    for title, vids in groups.items():
        if len(vids) < 2:
            continue
        keep = next((v for v in vids if v["id"] in protect), None) or sorted(vids, key=lambda v: v["at"])[0]
        for v in vids:
            if v["id"] == keep["id"] or v["id"] in protect:
                continue
            try:
                yt.videos().delete(id=v["id"]).execute()
                deleted.append(v["id"])
            except HttpError as e:
                print(f"::warning::could not delete duplicate https://youtu.be/{v['id']} of '{title}': {str(e)[:200]}")
        print(f"::notice title=Duplicates removed::'{title}': kept https://youtu.be/{keep['id']}, "
              f"deleted {len([v for v in vids if v['id'] in deleted])} extra copies")
    if deleted:
        _RECENT.pop("items", None)
    return deleted


def upload(ep_dir: Path, story: dict, cfg: dict) -> dict:
    yt_cfg = cfg["youtube"]
    yt = _client()
    tags, total = [], 0
    for t in story.get("tags", []):  # YouTube caps tags at ~500 characters total
        if total + len(t) + 2 > 450:
            break
        tags.append(t)
        total += len(t) + 2
    body = {
        "snippet": {
            "title": story["title"][:100],
            "description": build_description(story, cfg),
            "tags": tags,
            "categoryId": str(yt_cfg.get("category_id", "1")),
            "defaultLanguage": yt_cfg.get("default_language", "en"),
            "defaultAudioLanguage": yt_cfg.get("default_language", "en"),
        },
        "status": {
            "privacyStatus": yt_cfg.get("privacy", "private"),
            "selfDeclaredMadeForKids": bool(yt_cfg.get("made_for_kids", True)),
            "containsSyntheticMedia": bool(yt_cfg.get("contains_synthetic_media", True)),
            "embeddable": True,
        },
    }
    media = MediaFileUpload(str(ep_dir / "video.mp4"), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, retries = None, 0
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status:
                print(f"  uploaded {int(status.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retries < 6:
                retries += 1
                time.sleep(2 ** retries)
                continue
            if e.resp.status in (400, 403) and any(r in str(e) for r in ("uploadLimitExceeded", "quotaExceeded",
                                                                          "dailyLimitExceeded")):
                raise UploadLimit(str(e)[:300]) from None
            raise
    vid = resp["id"]
    got = resp["status"]["privacyStatus"]
    print(f"Uploaded: https://youtu.be/{vid}  (privacy: {got})")
    if got != body["status"]["privacyStatus"]:
        print(f"::warning::Asked for '{body['status']['privacyStatus']}' but YouTube set '{got}'. Until Google approves "
              "the YouTube API audit for this project, every API upload is locked to private. See README.")

    thumb = ep_dir / "thumbnail.jpg"
    if thumb.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
        except HttpError as e:  # custom thumbnails need a phone-verified channel
            print(f"  thumbnail not set ({e.resp.status}): verify your channel at youtube.com/verify to enable it")

    if yt_cfg.get("playlist_id"):
        try:
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": yt_cfg["playlist_id"], "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
        except HttpError as e:
            print(f"  could not add to playlist: {e}")

    info = {"video_id": vid, "url": f"https://youtu.be/{vid}", "privacy": resp["status"]["privacyStatus"],
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (ep_dir / "upload.json").write_text(json.dumps(info, indent=2))
    _RECENT.setdefault("items", []).insert(0, {"id": vid, "title": story["title"][:100], "at": info["uploaded_at"]})
    return info
