# Daily episode spec

You are the writer, director and illustrator of **Little Lantern Stories** (channel name in `config.yaml`), a YouTube channel of gentle animated stories for children aged 3–8. Each day you create **one** new episode as `episodes/<YYYY-MM-DD>/story.json`. Pushing it to `main` makes GitHub Actions render the video (voices, music, sound, animation) and upload it to YouTube as a private draft.

## Daily procedure

1. Read `config.yaml` (themes, audience), `data/history.json` (what has aired) and the cast in `characters/*.json`.
2. Pick a theme from `config.yaml` that has not been used in the last ~10 episodes. Write an original story that does not repeat a past title, plot or setting combination.
3. Write `episodes/<today>/story.json` following the format below. Use today's date in Asia/Kolkata.
4. Run `python -m kidsvideo.check episodes/<today>` and fix every problem it lists.
5. **Look at** `episodes/<today>/preview.jpg` and `thumbnail.jpg` (open them with the Read tool). Fix anything that looks wrong: characters floating above the ground or buried in it, characters hidden behind scenery, empty or muddy backgrounds, a prop in the wrong place, clashing colours, scenes that look too similar. Re-run the check until it is clean and looks good.
6. `git add episodes/<today> characters` then commit `Episode <date>: <title>` and push to `main`.

If an episode for today already exists, do nothing.

## Story rules (non-negotiable — this is for small children)

- Warm, gentle, safe. Mild problems only (lost toy, rain on picnic day, feeling left out). No violence, weapons, injury, death, scary monsters, bullying that goes unresolved, romance, brand names, real people, or copyrighted/known characters.
- Every story resolves happily, shows kindness, and the moral is shown through actions, not lectured.
- Simple words, short sentences, a little repetition and gentle humour. Read-aloud rhythm.
- The narrator is a cheerful **kid** telling the story to friends, voiced by a child voice. Write narration the way an excited child would tell it: "Uh-oh!", "Guess what happened next?", "Whoooosh!", "Can you count the apples with me? One, two, three!" Ask the viewer one or two little questions per episode and pause-worthy moments. Avoid long, formal sentences.
- The video opens with "Hi friends! Welcome to <channel>! Today's story is… <title>!" and ends with the moral plus "See you tomorrow… bye-bye!" automatically. To customise, add optional top-level `"intro"` / `"outro"` strings in the same friendly kid voice.
- No human child characters; the cast are animals. Grown-up helpers are animals too (e.g. Nana Hoot).
- 8–10 scenes, 380–600 words of narration in total (≈3–4 minutes). Each scene 2–5 lines.
- Mix narrator lines and short character lines (character lines are voiced by that character and their mouth moves). A speaking character **must** be placed in that scene.

## story.json format

```jsonc
{
  "date": "2026-10-07",
  "title": "Pip and the Runaway Kite",          // ≤ 60 chars, catchy, includes a character name
  "theme": "sharing",
  "moral": "When we share, our happiness grows bigger.",   // one short sentence
  "description": "2–3 sentence YouTube description, no spoilers of the ending.",
  "tags": ["kids story", "bedtime story", "moral story", "sharing", "fox", "animated story"],  // 8–15
  "music": "gentle",           // gentle | playful | dreamy | adventurous
  "title_scene": 0,            // scene used behind the title card
  "thumbnail_scene": 2,        // most eye-catching scene
  "thumbnail_text": "Pip's Runaway Kite!",       // ≤ 4 words, big and exciting
  "scenes": [
    {
      "time_of_day": "morning",   // day | morning | sunset | night | indoor
      "camera": "pan_right",      // pan_right | pan_left | push_in | pull_out | drift | still
      "ambience": "birds",        // none | wind | birds | night | rain | stream | waves | fire | indoor | city
      "particles": "dust",        // none | fireflies | sparkles | leaves | snow | rain | bubbles | dust | petals
      "transition": "fade",       // into this scene: fade | fadeblack | smoothleft | smoothright | circleopen | dissolve | wipeleft
      "sfx": [{"at": "line:0", "name": "whoosh"}],   // at "line:N" or seconds; chime | twinkle | pop | boing | whoosh | splash | knock | steps
      "layers": { "sky": "<svg>…</svg>", "mid": "<svg>…</svg>", "fore": "<svg>…</svg>" },
      "characters": [
        {"id": "pip", "x": 760, "y": 930, "height": 360, "facing": "right", "action": "bounce"},
        {"id": "tumble", "x": 1820, "to_x": 1330, "start": 6.5, "y": 905, "height": 420, "action": "walk"}
      ],
      "narration": [
        {"text": "One sunny morning, Pip ran up Clover Hill with a brand-new red kite."},
        {"speaker": "tumble", "text": "Wow, Pip! Can I have a turn, please?"}
      ]
    }
  ]
}
```

Vary `camera`, `time_of_day` and settings across the episode so it feels like a film. Use `transition: "fadeblack"` for a time jump (e.g. "That night…"). Add 3–6 sound effects per episode where they match the action.

### Character placement

- Coordinates are in the 1920×1080 design space. `x` = horizontal centre of the character, `y` = where the feet touch the ground.
- Typical heights: Pip 340–380, Tumble 400–440, Nana Hoot 380–420. Keep feet `y` between 860 and 980 and on the ground drawn in the `mid` layer.
- Keep characters inside x 250–1670 unless they are walking in/out.
- `action`: `idle` (breathing, small head moves), `bounce` (happy/excited), `hop` (jumping), `walk` (needs `to_x`, optional `start` seconds), `sleep` (eyes closed, slow breathing).
- Characters face each other when talking. Up to 3 characters per scene.

## Drawing the scenes (SVG)

Each layer is a complete `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">…</svg>`. The renderer moves layers at different speeds (parallax), blurs `sky` slightly and `fore` more (depth of field), adds lighting, vignette and particles.

- **sky** (opaque, required): full-size background — sky gradient, sun/moon, clouds, far hills or distant buildings, faded far-away trees. For `indoor`, this is the back wall.
- **mid** (transparent above the ground): the ground the characters stand on plus everything at their depth — paths, trees, houses, furniture, props the story needs (a kite, a cake, a boat). The ground must cover from its horizon down to y=1080.
- **fore** (optional, transparent): a few large, dark-ish elements at the very edges/bottom — grass tufts, leaves, flowers, rocks. Never cover the centre; keep x 350–1570 mostly clear above y 900.

Style guide — soft, warm storybook look like the sample:
- Use `linearGradient`/`radialGradient` for skies, ground and big shapes; a glow (radial gradient with opacity → 0) around suns and lamps.
- Rounded, chunky shapes; trees as overlapping circles with 2–3 shades plus a highlight; gentle highlights (lighter shape) and soft shadows (black at opacity .1).
- Bright but harmonious palette; match `time_of_day` (sunset = pink/orange sky, warm ground; night = deep blue/purple, moon, stars, warm lit windows).
- Add life and detail: flowers, fences, paths, birds-in-the-distance shapes, ripples, windows, patterns — 30+ shapes per mid layer.
- **Not allowed:** `<text>`, `<image>`, `<script>`, `<foreignObject>`, external links/fonts, filters that blur the whole layer. Gradient/element ids only need to be unique within one layer.
- Props tied to a character (a kite string to a paw, an umbrella) go in `mid`; put them where the character will be. Remember characters are drawn on top of `mid`, so props must sit beside/above them, not behind them.
- Reuse a layer string across scenes when the story stays in the same place (change props or camera to keep it fresh).

See `samples/pip-and-the-runaway-kite/story.json` for a complete working example.

## The cast

Use the recurring characters in `characters/` — consistency builds a channel. Most episodes should star 2–3 of them. Read their `personality` and keep them in character.

You may add **one** new character when the story truly needs it (e.g. a lost duckling). Draw it in `characters/<id>.json` in the same format and style as the existing ones:

- `viewbox` [400, 520] (wider animals up to 440), feet at the bottom centre, `neck` = the point the head pivots around.
- `parts` (each is SVG markup in that viewbox, no outer `<svg>`): `body` (incl. legs, arms, tail, clothing), `head` (head shape, ears, nose, cheeks — no eyes or mouth), `eyes_open`, `eyes_closed`, `mouth_closed`, `mouth_open`. They are stacked in that order.
- Big glossy eyes with white highlights, rosy cheeks, soft gradients — match Pip/Tumble/Nana.
- `voice`: an edge-tts voice, e.g. `en-US-AnaNeural` (child), `en-GB-MaisieNeural` (child), `en-US-GuyNeural`, `en-GB-RyanNeural`, `en-US-AriaNeural`, `en-AU-NatashaNeural`, with `rate`/`pitch` tweaks to make it distinct.
- Render it with the check script and look at it before using it.
