# Layer Story v0.1.0

The first public release of Layer Story turns author-aligned SVG layers into a numbered overview, a layer-reference PDF, and a 12-second unfold-and-return video. It is intended for layered paper art, shadow boxes, and flat stacked designs with confirmed back-to-front order.

![Layer Story animation preview](https://raw.githubusercontent.com/eason560899/layer-story/v0.1.0/docs/demo/layer-story.gif)

[Sample overview](https://github.com/eason560899/layer-story/blob/v0.1.0/docs/demo/overview.png) · [Sample PDF](https://github.com/eason560899/layer-story/blob/v0.1.0/docs/demo/layer-guide.pdf) · [Full MP4](https://github.com/eason560899/layer-story/blob/v0.1.0/docs/demo/layer-story.mp4)

## Included

- Agent skill instructions and a local Python/Node CLI.
- Manifests for 2–24 author-defined layers, with English or Chinese guides.
- Individual and cumulative PNGs, a complete composition, a numbered overview, PDF, MP4, and poster.
- One numbered card per layer in the expanded video, including separate layers that share a color.
- Input validation, source SHA-256 hashes, output records, and preservation of the original SVG files.
- Original six-layer demo artwork with English and Chinese manifests.

## Try it

After installing the dependencies described in the [README](https://github.com/eason560899/layer-story/blob/v0.1.0/README.md#start-with-the-cli):

```sh
python scripts/build_layer_story.py assets/demo/manifest.en.json --out demo-output
```

The output directory must be new or empty. Add `--skip-video` for images and PDF only. The Chinese demo uses `assets/demo/manifest.json` and requires a font covering the requested Chinese text.

## Checked for this release

The original six-layer demo and a separate four-layer fixture produced inspected PDFs and decoded 1080 × 1080, 24 fps H.264 videos. Checks included holes, local transforms, intentional white areas, repeated definition IDs across source files, and independent layers with the same color. The four-layer cumulative images matched independent compositing, and source hashes stayed unchanged.

A 24-layer stress case passed static output and long-label checks, plus visual inspection of video-renderer frames. A full independent decode of a 24-layer MP4 has not been performed. Invalid manifests and unsupported SVG inputs were exercised as rejection cases.

## Current boundaries

Provide one aligned SVG per physical layer and confirm the order. Layer Story does not recover assembled positions from cutting layouts, infer physical layers from colors, or invent assembly methods. External resources, embedded raster images, SVG text, filters, scripts, and animation are unsupported. Convert text to outlines before export.

Video spacing is schematic, and the outputs are presentation assets rather than cutting templates or manufacturing validation. The bundled synthetic artwork has not been physically cut or assembled. Cross-platform installation and all SVG features have not been exhaustively tested.

**中文：** 首个公开版本提供本地 Skill 与命令行，把已对齐且已确认前后顺序的 SVG 图层制作成层序图册和展示视频。英文示例可直接按 README 运行；中文输出需先配置覆盖所用汉字的字体。示例为原创合成素材，未经实体试切。
