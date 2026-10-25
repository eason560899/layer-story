# Job manifest

```json
{
  "title": "Moonlit Cove",
  "brand": "Studio name",
  "language": "en",
  "order_confirmed": true,
  "alignment_confirmed": true,
  "layers": [
    {"id": "sky", "label": "Sky", "file": "01-sky.svg"},
    {"id": "ridge", "label": "Distant ridge", "file": "02-ridge.svg", "note": "Author-supplied instruction, if any."}
  ]
}
```

`layers` is an ordered array, back to front, with 2–24 layers. IDs must be unique short slugs. Relative file paths resolve against the manifest's directory. Keep labels short enough to recognize at a glance; longer labels belong in the PDF, not a tiny moving video badge.

The confirmation fields must reflect actual confirmation, not values filled just to make validation pass. For artwork produced within the current authorized task, the authoring process can establish both facts. For existing files, inspect trustworthy source metadata or ask the author. Unknown order should remain unknown.

All SVGs must have the same finite `viewBox`, with positive width and height. Supply self-contained vectors with internal `#id` references only. The renderer treats each full SVG as a separate document, so repeated definition IDs in different layers remain independent. It preserves white rectangles and opaque layers; these may intentionally hide earlier layers. SVG text should be converted to outlines by the author. Scripts, event handlers, external resources, embedded raster images, SVG filters and animated SVG are unsupported. Width and height, if present, must both use absolute units and have the same aspect ratio as the viewBox. Source files are limited to 5 MB each.

`note` is optional, author-supplied text. An omitted note means no assembly instruction is available for that layer. Presentation gaps are not foam thickness, and the build does not infer adhesives, cutting settings or manufacturing suitability.

Outputs include numbered original-layer and cumulative PNGs, `composite.png`, `overview.png`, `layer-guide.pdf`, `layer-story.mp4` (unless skipped), `video-poster.png`, and machine-readable build records with source hashes. Hashes establish which source was used, not who owns it or whether it is manufacturable. Export dimensions are presentation dimensions, not 1:1 cutting templates.

Dependency setup, if needed, from the skill directory:

```sh
python -m venv .venv
# Activate the environment for your shell, then:
python -m pip install -r requirements.txt
npm install --ignore-scripts
```

If `sharp` is already installed in a shared runtime, set Node's normal `NODE_PATH` to that runtime's `node_modules`. Do not hardcode a different user's paths into the skill. For a font outside the normal system locations, set `LAYER_STORY_FONT` to an embeddable TrueType font covering the requested text. MP4 encoding uses a local FFmpeg executable provided by imageio-ffmpeg or its `IMAGEIO_FFMPEG_EXE` override; it does not send artwork to a service.
