#!/usr/bin/env node
'use strict';

// Internal renderer. build_layer_story.py validates XML before sending a job.
// Install sharp normally, or set NODE_PATH to a directory containing sharp.
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  let sharp;
  try { sharp = require('sharp'); }
  catch (_) { throw new Error('Missing Node dependency: sharp. Run npm install in the skill folder, or configure NODE_PATH.'); }
  const job = JSON.parse(fs.readFileSync(0, 'utf8'));
  const {width, height} = job.canvas || {};
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || Math.max(width, height) !== 1200) {
    throw new Error('Invalid raster canvas; expected a positive canvas with a 1200 px long edge.');
  }
  if (!Array.isArray(job.layers) || job.layers.length < 2 || job.layers.length > 24) {
    throw new Error('Expected 2–24 validated layers.');
  }
  const started = performance.now();
  const results = [];
  for (const layer of job.layers) {
    if (typeof layer.svg !== 'string' || typeof layer.png !== 'string' || !path.isAbsolute(layer.png)) {
      throw new Error('Invalid internal rendering job.');
    }
    // Defense in depth. The Python admission checks are the full policy.
    if (/<!\s*(?:DOCTYPE|ENTITY)|<\s*(?:\w+:)?(?:script|foreignObject|image|text|animate\w*|set)\b/i.test(layer.svg)) {
      throw new Error('Unsupported active, external, raster, or text SVG content.');
    }
    // Sharp uses 72 dpi as its native SVG viewport scale (verified on librsvg).
    const png = await sharp(Buffer.from(layer.svg, 'utf8'), {density:72, limitInputPixels:16_000_000, failOn:'error'})
      .resize(width, height, {fit:'fill', kernel:'lanczos3'})
      .ensureAlpha()
      .png()
      .toBuffer();
    const meta = await sharp(png).metadata();
    if (meta.width !== width || meta.height !== height || !meta.hasAlpha) throw new Error('Unexpected rendered canvas.');
    fs.writeFileSync(layer.png, png, {flag:'wx'});
    results.push({id:layer.id, width:meta.width, height:meta.height});
  }
  process.stdout.write(JSON.stringify({renderer:'sharp/librsvg', sharp:sharp.versions.sharp, rsvg:sharp.versions.rsvg,
    elapsed_ms:Math.round(performance.now()-started), layers:results}));
}

main().catch(error => {
  process.stderr.write('SVG render failed: '+error.message+'\n');
  process.exitCode = 1;
});
