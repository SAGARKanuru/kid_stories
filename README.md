# Little Lantern Stories — daily animated kids' story pipeline

Every morning a Claude scheduled task writes and illustrates a new children's story, checks the artwork, and pushes `episodes/<date>/story.json` to this repo. GitHub Actions then renders a ~3–4 minute 1080p animated video and uploads it to YouTube as **private**, marked *Made for Kids*.

```
Claude scheduled task (daily, 04:52 IST)          GitHub Actions (on push)
  story + scene art + direction  ──push──▶  voices (edge-tts) · music · ambience · SFX
  validates + previews its own art           parallax camera · rigged characters · captions
                                             thumbnail ─▶ YouTube upload (private, made for kids)
```

No paid AI video or voice services are used: voices are free Microsoft neural voices (edge-tts), music and sound effects are generated from scratch, and rendering runs on free GitHub Actions minutes.

## What makes it feel like a real cartoon

- Three depth layers per scene with parallax camera moves (pan, push-in, pull-out, drift) and depth-of-field blur
- Rigged characters that breathe, blink, turn their heads, walk, hop and **lip-sync** their own lines
- A separate voice for each character plus a narrator; original music that ducks under speech
- Scene ambience (birds, wind, stream, rain, crickets, fire…) and sound effects on cue
- Fireflies, sparkles, falling leaves, snow and rain; time-of-day lighting and vignette
- Title card, "The End" card with the moral, captions, crossfades and an auto-made thumbnail

## Setup (one time, ~20 minutes)

### 1. Put this project on GitHub
Create a repository (private is fine), push this folder to its `main` branch.

### 2. Google Cloud: allow uploads to your channel
1. Go to [console.cloud.google.com](https://console.cloud.google.com), create a project.
2. **APIs & Services → Library →** enable **YouTube Data API v3**.
3. **OAuth consent screen**: User type *External*, fill in the app name and your email, add the scopes `youtube.upload` and `youtube`.
   Then click **Publish app** (move it to *In production*). If you leave it in *Testing*, Google expires the login every 7 days and uploads will stop. You will see an "unverified app" warning when you sign in; that's expected for your own app — click *Advanced → continue*.
4. **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON file.

### 3. Get the token and add GitHub secrets
On your computer:
```bash
pip install google-auth-oauthlib
python tools/get_youtube_token.py ~/Downloads/client_secret_XXXX.json
```
Sign in with the account that owns the channel. Add the three printed values in GitHub → **Settings → Secrets and variables → Actions → New repository secret**:
`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.

### 4. YouTube channel settings
- Verify your channel at [youtube.com/verify](https://www.youtube.com/verify) so custom thumbnails can be set.
- In YouTube Studio → Settings → Channel → Advanced, set the audience to *Yes, it's made for kids*.

### 5. Test it
GitHub → **Actions → Render & upload episode → Run workflow** with episode `samples/pip-and-the-runaway-kite` and *Upload* unchecked. Download the video from the run page (Artifacts).

## Important YouTube rules

- **Private until Google audits your API project.** YouTube locks every video uploaded through the API by an unaudited project to *private*. To be able to publish, submit the free *YouTube API Services audit* (Google Cloud console → YouTube Data API → Quotas → "apply for an audit"; describe it as "uploads my own channel's original animated videos"). Until then, the daily videos collect privately in YouTube Studio.
- **AI disclosure**: uploads are flagged as containing synthetic media and the description says AI tools were used.
- **Monetisation**: YouTube doesn't monetise mass-produced, repetitive content. Keep stories genuinely varied, review them, and consider adding your own touches (intro voice, channel art) if you plan to join the Partner Programme.
- Made-for-kids videos have comments, notifications bell and personalised ads turned off by YouTube — that's normal.

## Daily operation

| What | Where |
|---|---|
| Today's story, preview sheet and thumbnail | `episodes/<date>/` (`preview.jpg`, `thumbnail.jpg`) |
| Render/upload logs, video download | GitHub → Actions |
| Uploaded list | `data/history.json` |
| Change voices, music level, privacy, themes | `config.yaml` |
| Writing and art rules Claude follows | `STORY_SPEC.md` |
| Recurring characters | `characters/*.json` |

Re-render an episode: Actions → Run workflow → episode `episodes/2026-10-07`. To redo an upload, delete that episode's `upload.json` first.

## Local use

```bash
pip install -r requirements.txt            # plus ffmpeg
python -m kidsvideo.check samples/pip-and-the-runaway-kite     # validate + preview.jpg
python -m kidsvideo.run --episode samples/pip-and-the-runaway-kite --no-upload
```
