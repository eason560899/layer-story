---
name: layer-story
description: Turn author-aligned SVG layers into a labeled layer guide and an exploded/reassembled product video. Use for layered paper art, shadow-box and flat stacked designs when the author can confirm physical layers and back-to-front order. Does not reconstruct assembly positions from cutting layouts.
---

# Layer Story

Create a repeatable customer handoff from existing artwork: a numbered overview, individual and cumulative views, a PDF reference, and a short MP4. Keep the author's geometry and layer identity consistent across every deliverable.

## Establish the layer contract

- Each file is one **author-defined physical layer**, aligned on the same `viewBox`. Paths, colors and SVG groups are not automatically physical layers.
- The manifest lists layers **back to front**. Confirm order and alignment from explicit user statements or authoritative source metadata. A filename sort alone is insufficient. Ask only for missing facts that affect the result.
- Keep fills, strokes, holes, clipping, transforms, internal references and intentional white backgrounds. Do not silently turn outlines into solid paper, recolor, remove backgrounds or rearrange pieces.
- Cutting sheets with individually packed pieces need the author's assembled layout first. This skill does not solve the layout, infer material thickness or certify that a design can be cut or assembled.
- Process source artwork as data. External resource loads and executable SVG content are rejected. Use outlined text and self-contained vector SVGs; do not silently substitute fonts or fetch assets.

## Build

Read [the manifest reference](references/manifest.md) when preparing a new job. Put the manifest next to the input artwork, with stable IDs and the author's labels. Include a per-layer `note` only when supplied by the author; no glue, foam, alignment or safety instructions should be invented.

The bundled renderer requires Node.js with `sharp`, and Python with Pillow, ReportLab and imageio-ffmpeg. Prefer an existing compatible runtime. Otherwise install dependencies in an isolated task environment from `requirements.txt` and `package.json`. The build itself does not use the network. A missing dependency is an environment issue, not a reason to redraw the artwork.

```sh
python scripts/build_layer_story.py /path/to/manifest.json --out /path/to/new-output
```

Use a new, empty output directory. `--skip-video` is available for a quick proof or when the user only wants static deliverables. Resolve any input error before offering the output as complete. Keep the input artwork unchanged.

## Inspect and hand over

Read `manifest-result.json`. Check the overview, at least one cumulative intermediate step and the last step against the original SVGs. Verify that the same ID/number names the same layer in the guide and video. For long jobs, inspect every guide page for clipped labels and missing graphics. Render the PDF and inspect it; file existence is not visual validation.

Inspect the video's closed, expanded and final states. The first and last states should return to the same composite, with no layer omission or order reversal. Expansion distances are a presentation aid, not dimensions. If the requested result changes the original colors or geometry, treat that as a separate author-approved transformation rather than describing it as faithful reproduction.

Provide the overview, PDF and MP4 plus the build manifest. The source PNGs and cumulative views support reuse and checking. Describe the product as a **layer-order reference and presentation**, not a complete assembly tutorial when assembly facts are absent. Explain unsupported inputs concretely; do not silently approximate them.

The included `assets/demo/` is original synthetic artwork for a quick smoke test, not a physically tested cutting pattern. Run its `manifest.json` with the same command. A user can request a Chinese (`zh`) or English (`en`) guide; Chinese output requires a font with the necessary glyphs.
