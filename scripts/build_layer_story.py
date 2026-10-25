#!/usr/bin/env python3
"""Build a digital SVG layer presentation from an author-confirmed manifest.

No network access, source edits, inferred alignment, or physical-assembly claims.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

SVG_NS = 'http://www.w3.org/2000/svg'
XLINK_NS = 'http://www.w3.org/1999/xlink'
MAX_SVG_BYTES = 5 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
ALLOWED_TAGS = {
    'svg', 'g', 'defs', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline',
    'polygon', 'clipPath', 'mask', 'linearGradient', 'radialGradient', 'stop',
    'pattern', 'marker', 'use', 'symbol', 'title', 'desc', 'metadata', 'style',
}
FORBIDDEN_TAGS = {'script', 'foreignObject', 'image', 'text', 'tspan', 'textPath',
                  'animate', 'animateMotion', 'animateTransform', 'set', 'mpath',
                  'font', 'font-face', 'filter', 'feImage', 'switch', 'a'}
ID_PATTERN = re.compile(r'[A-Za-z_][A-Za-z0-9_.:-]*\Z')
SLUG_PATTERN = re.compile(r'[a-z0-9][a-z0-9-]{0,47}\Z')
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
LENGTH_PATTERN = re.compile(r'(' + NUMBER + r')\s*(px|pt|pc|in|cm|mm|q)?\Z', re.I)
URL_PATTERN = re.compile(r'url\s*\((.*?)\)', re.I | re.S)
LENGTH_UNITS = {'px':1, 'pt':96/72, 'pc':16, 'in':96, 'cm':96/2.54, 'mm':96/25.4, 'q':96/101.6}


class BuildError(ValueError):
    pass


def local_name(value: str) -> str:
    return value.rsplit('}', 1)[-1]


def text_field(value, name, maximum, optional=False):
    if value is None and optional:
        return ''
    if not isinstance(value, str) or (not optional and not value.strip()):
        raise BuildError(f'{name} must be a nonempty string.')
    if len(value) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise BuildError(f'{name} contains unsupported control characters or exceeds {maximum} characters.')
    return value.strip()


def absolute_length(value, name):
    match = LENGTH_PATTERN.fullmatch(value.strip()) if isinstance(value, str) else None
    if not match:
        raise BuildError(f'{name} must be an absolute positive SVG length; percentages are unsupported.')
    result = float(match.group(1)) * LENGTH_UNITS[(match.group(2) or 'px').lower()]
    if not math.isfinite(result) or result <= 0 or result > 1_000_000:
        raise BuildError(f'{name} must be finite and positive, at most 1,000,000 CSS px.')
    return result


def inspect_css(value, location, references):
    # CSS escapes and at-rules are excluded to keep external resource checks explicit.
    cleaned = re.sub(r'/\*.*?\*/', '', value, flags=re.S)
    if '\\' in cleaned or '@' in cleaned or re.search(r'expression\s*\(|-moz-binding|behavior\s*:', cleaned, re.I):
        raise BuildError(f'{location}: CSS escapes, at-rules, and active CSS are unsupported.')
    for match in URL_PATTERN.finditer(cleaned):
        target = match.group(1).strip().strip('"\'').strip()
        if not target.startswith('#') or not ID_PATTERN.fullmatch(target[1:]):
            raise BuildError(f'{location}: only local fragment url(#id) references are allowed.')
        references.add(target[1:])
    remaining = URL_PATTERN.sub('', cleaned)
    if re.search(r'url\s*\(', remaining, re.I):
        raise BuildError(f'{location}: malformed CSS url().')
    if re.search(r'\b(?:https?|ftp|file|data|javascript)\s*:', cleaned, re.I):
        raise BuildError(f'{location}: external or embedded resources are unsupported.')


def inspect_svg(source: Path):
    if not source.is_file() or source.suffix.lower() != '.svg':
        raise BuildError(f'Expected an existing .svg file: {source.name}')
    if source.stat().st_size > MAX_SVG_BYTES:
        raise BuildError(f'{source.name}: exceeds the 5 MB SVG limit.')
    raw = source.read_bytes()
    if len(raw) > MAX_SVG_BYTES:
        raise BuildError(f'{source.name}: exceeds the 5 MB SVG limit.')
    try:
        xml = raw.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise BuildError(f'{source.name}: save the SVG as UTF-8.') from error
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)', xml, re.I):
        raise BuildError(f'{source.name}: DTDs and entities are unsupported.')
    if re.search(r'<\?(?!xml\s)[\s\S]*?\?>', xml, re.I):
        raise BuildError(f'{source.name}: XML processing instructions are unsupported.')
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise BuildError(f'{source.name}: invalid XML: {error}') from error
    if root.tag not in ('svg', '{'+SVG_NS+'}svg'):
        raise BuildError(f'{source.name}: root must be an SVG element.')
    values = re.split(r'[\s,]+', root.get('viewBox', '').strip())
    try:
        viewbox = [float(v) for v in values]
    except ValueError as error:
        raise BuildError(f'{source.name}: requires a numeric four-value viewBox.') from error
    if len(viewbox) != 4 or not all(math.isfinite(v) for v in viewbox) or viewbox[2] <= 0 or viewbox[3] <= 0:
        raise BuildError(f'{source.name}: requires a finite viewBox with positive width and height.')
    if any(abs(v) > 1_000_000 for v in viewbox):
        raise BuildError(f'{source.name}: viewBox coordinates exceed the supported limit.')
    ratio = viewbox[2] / viewbox[3]
    if not (1/1200 <= ratio <= 1200):
        raise BuildError(f'{source.name}: aspect ratio is too extreme for a 1200 px canvas.')
    width, height = root.get('width'), root.get('height')
    if (width is None) != (height is None):
        raise BuildError(f'{source.name}: provide both width and height, or omit both and use viewBox.')
    if width is not None:
        physical_ratio = absolute_length(width, source.name+' width') / absolute_length(height, source.name+' height')
        if not math.isclose(ratio, physical_ratio, rel_tol=1e-7, abs_tol=1e-9):
            raise BuildError(f'{source.name}: width/height aspect ratio must match viewBox.')
    ids, references = set(), set()
    stack = [(root, 0, False)]
    count = 0
    while stack:
        element, depth, metadata_parent = stack.pop()
        count += 1
        if count > 50_000 or depth > 128:
            raise BuildError(f'{source.name}: XML complexity exceeds the supported limit.')
        tag = local_name(element.tag)
        metadata = metadata_parent or tag == 'metadata'
        if tag in FORBIDDEN_TAGS or tag.lower().startswith('animate'):
            detail = ' Convert SVG text to paths before export.' if tag in {'text','tspan','textPath'} else ''
            raise BuildError(f'{source.name}: unsupported SVG element <{tag}>.{detail}')
        if not metadata:
            namespace = element.tag[1:].split('}')[0] if element.tag.startswith('{') else ''
            if tag not in ALLOWED_TAGS or namespace not in ('', SVG_NS):
                raise BuildError(f'{source.name}: unsupported SVG element <{tag}>.')
        if tag == 'style':
            inspect_css(''.join(element.itertext()), source.name+' style', references)
        for attribute, value in element.attrib.items():
            name = local_name(attribute)
            if name.lower().startswith('on') or name.lower() in {'base', 'src'}:
                raise BuildError(f'{source.name}: active or externally based attribute {name} is unsupported.')
            if name == 'id':
                if not ID_PATTERN.fullmatch(value) or value in ids:
                    raise BuildError(f'{source.name}: invalid or duplicate id {value!r}.')
                ids.add(value)
            if name == 'href':
                if not value.startswith('#') or not ID_PATTERN.fullmatch(value[1:]):
                    raise BuildError(f'{source.name}: href must refer to an internal #id.')
                references.add(value[1:])
            if name == 'style' or re.search(r'url\s*\(', value, re.I):
                inspect_css(value, source.name+' '+name, references)
            if name.lower() in {'fill','stroke','filter','clip-path','mask','marker','marker-start','marker-mid','marker-end'} and '\\' in value:
                raise BuildError(f'{source.name}: escaped paint or resource values are unsupported.')
        stack.extend((child, depth+1, metadata) for child in element)
    missing = references - ids
    if missing:
        raise BuildError(f'{source.name}: unresolved local references: {", ".join(sorted(missing)[:5])}.')
    return {'source':source, 'root':root, 'viewBox':viewbox, 'sha256':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw)}


def load_manifest(path):
    if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise BuildError('Manifest must be an existing JSON file no larger than 128 KB.')
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BuildError(f'Invalid manifest JSON: {error}') from error
    if not isinstance(data, dict):
        raise BuildError('Manifest must be a JSON object.')
    if data.get('order_confirmed') is not True or data.get('alignment_confirmed') is not True:
        raise BuildError('The author must set order_confirmed and alignment_confirmed to true after checking the layers.')
    title = text_field(data.get('title'), 'title', 180)
    brand = text_field(data.get('brand'), 'brand', 120, optional=True)
    language = data.get('language', 'en')
    if language not in ('en', 'zh'):
        raise BuildError('language must be en or zh.')
    layers = data.get('layers')
    if not isinstance(layers, list) or not 2 <= len(layers) <= 24:
        raise BuildError('Manifest requires 2–24 layers, ordered back to front.')
    inspected, seen = [], set()
    for index, layer in enumerate(layers, 1):
        if not isinstance(layer, dict):
            raise BuildError(f'Layer {index} must be an object.')
        identity = layer.get('id')
        if not isinstance(identity, str) or not SLUG_PATTERN.fullmatch(identity) or identity in seen:
            raise BuildError(f'Layer {index} requires a unique lowercase slug id (1–48 characters).')
        seen.add(identity)
        filename = layer.get('file')
        if not isinstance(filename, str) or not filename or '\x00' in filename:
            raise BuildError(f'Layer {identity}: file must be a local path.')
        if re.match(r'^(?:https?|ftp|data|file):', filename, re.I):
            raise BuildError(f'Layer {identity}: URLs are unsupported; provide a local SVG file.')
        if filename.startswith(('\\\\', '//')):
            raise BuildError(f'Layer {identity}: network share paths are unsupported; provide a local SVG file.')
        source = Path(filename).expanduser()
        if not source.is_absolute():
            source = path.parent / source
        resolved_source = source.resolve()
        if str(resolved_source).startswith(('\\\\', '//')):
            raise BuildError(f'Layer {identity}: the resolved source must be on a local filesystem.')
        info = inspect_svg(resolved_source)
        info.update(id=identity, label=text_field(layer.get('label'), f'{identity} label', 180),
                    note=text_field(layer.get('note'), f'{identity} note', 1000, optional=True))
        if inspected and not all(math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-9) for a,b in zip(info['viewBox'],inspected[0]['viewBox'])):
            raise BuildError(f'{identity}: every layer must have the same viewBox, including its origin; no automatic alignment is performed.')
        inspected.append(info)
    return {'title':title,'brand':brand,'language':language}, inspected


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def build(manifest, destination, skip_video=False):
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    manifest = Path(manifest).resolve()
    requested_out = Path(destination).expanduser().absolute()
    if requested_out.is_symlink():
        raise BuildError('Output directory may not be a symbolic link.')
    destination = requested_out.resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise BuildError('Output directory must be absent or empty; existing files are never overwritten.')
    fields, layers = load_manifest(manifest)
    try:
        from PIL import Image
        from presentation import create_deliverables
    except ImportError as error:
        raise BuildError(f'Missing Python dependency or presentation module: {error}. Install requirements.txt.') from error
    node = shutil.which('node')
    if node is None:
        raise BuildError('Node.js is required to render SVGs; install Node.js and sharp.')
    viewbox = layers[0]['viewBox']
    scale = 1200 / max(viewbox[2], viewbox[3])
    canvas = {'width':max(1, round(viewbox[2]*scale)), 'height':max(1, round(viewbox[3]*scale))}
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_prefix = '.'+destination.name+'.building-'
    # Inherit the output parent's readable ACL. Windows Python 3.13 mkdtemp
    # uses a private mode-0700 ACL that can prevent the app preview from reading.
    staging = destination.parent / (staging_prefix + uuid.uuid4().hex)
    staging.mkdir(mode=0o755)
    committed = False
    try:
        (staging/'layers').mkdir()
        (staging/'cumulative').mkdir()
        data = {**fields, 'schema_version':1, 'canvas':canvas, 'viewBox':viewbox,
                'layer_order':'back-to-front', 'layers':[]}
        jobs, warnings = [], []
        ET.register_namespace('', SVG_NS)
        ET.register_namespace('xlink', XLINK_NS)
        for index, layer in enumerate(layers, 1):
            png = f'layers/{index:02d}-{layer["id"]}.png'
            cumulative = f'cumulative/{index:02d}-{layer["id"]}.png'
            data['layers'].append({key:layer[key] for key in ('id','label','note','sha256')})
            data['layers'][-1].update(source_name=layer['source'].name, source_bytes=layer['bytes'], png=png, cumulative_png=cumulative)
            # Change only the raster viewport in memory; viewBox/geometry/style remain.
            layer['root'].set('width', str(canvas['width']))
            layer['root'].set('height', str(canvas['height']))
            jobs.append({'id':layer['id'], 'svg':ET.tostring(layer['root'], encoding='unicode'), 'png':str(staging/png)})
        try:
            process = subprocess.run([node, str(Path(__file__).with_name('render_svg.cjs'))],
                                     input=json.dumps({'canvas':canvas,'layers':jobs}), text=True,
                                     encoding='utf-8', capture_output=True, timeout=120, check=False)
        except subprocess.TimeoutExpired as error:
            raise BuildError('SVG rendering exceeded 120 seconds; reduce SVG complexity.') from error
        if process.returncode:
            raise BuildError(process.stderr.strip() or 'SVG rendering failed.')
        try:
            render_info = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise BuildError('SVG renderer returned an invalid receipt.') from error
        composite = Image.new('RGBA', (canvas['width'],canvas['height']), (0,0,0,0))
        for index, layer in enumerate(data['layers']):
            with Image.open(staging/layer['png']) as image:
                image.load()
                if image.size != composite.size:
                    raise BuildError('Rendered layer size does not match the canvas.')
                rgba = image.convert('RGBA')
                if index > 0 and rgba.getchannel('A').getextrema() == (255,255):
                    warnings.append(f'Layer {layer["id"]} is opaque across the full canvas and covers earlier layers; its background was preserved.')
                composite = Image.alpha_composite(composite, rgba)
                composite.save(staging/layer['cumulative_png'])
        composite.save(staging/'composite.png')
        data['renderer'] = render_info
        write_json(staging/'build-data.json', data)
        presentation_result = create_deliverables(data, staging, skip_video=skip_video)
        if isinstance(presentation_result, dict):
            warnings.extend(str(item) for item in presentation_result.get('warnings', []))
        required = ['overview.png','layer-guide.pdf','video-poster.png']
        if not skip_video:
            required.append('layer-story.mp4')
        for filename in required:
            item = staging/filename
            if not item.is_file() or item.stat().st_size == 0:
                raise BuildError(f'Presentation did not produce the required output: {filename}')
        outputs = []
        for item in sorted(staging.rglob('*')):
            if item.is_file():
                outputs.append({'path':item.relative_to(staging).as_posix(),'bytes':item.stat().st_size,
                                'sha256':hashlib.sha256(item.read_bytes()).hexdigest()})
        receipt = {'status':'complete','started_at':started.isoformat(), 'finished_at':datetime.now(timezone.utc).isoformat(),
                   'elapsed_seconds':round(time.perf_counter()-timer,3), 'title':fields['title'],
                   'layer_order':[layer['id'] for layer in layers], 'canvas':canvas, 'viewBox':viewbox,
                   'source_files_modified':False, 'source_files_copied':False, 'video_skipped':skip_video,
                   'outputs':outputs, 'warnings':warnings, 'renderer':render_info,
                   'scope':'Digital layer presentation only; author-confirmed order and alignment, no physical assembly verification.'}
        write_json(staging/'manifest-result.json', receipt)
        # Never replace an existing directory or files, including concurrent writes.
        if destination.exists():
            destination.rmdir()
        staging.rename(destination)
        committed = True
        return receipt
    finally:
        if not committed and staging.exists():
            # Check the concrete Windows target again immediately before recursion.
            if (not staging.is_symlink()
                    and staging.resolve().parent == destination.parent.resolve()
                    and staging.name.startswith(staging_prefix)):
                shutil.rmtree(staging)
            else:
                print('Temporary-output cleanup skipped because its verified location changed: '+str(staging), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', help='Author-confirmed local manifest.json')
    parser.add_argument('--out', required=True, help='New or empty output directory')
    parser.add_argument('--skip-video', action='store_true', help='Generate images and PDF without MP4')
    args = parser.parse_args()
    try:
        result = build(args.manifest, args.out, args.skip_video)
    except (BuildError, OSError, RuntimeError, ValueError) as error:
        print('Layer Story failed: '+str(error), file=sys.stderr)
        return 1
    print(json.dumps({'status':result['status'],'output_directory':str(Path(args.out).resolve()),
                      'elapsed_seconds':result['elapsed_seconds'],'warnings':result['warnings']}, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
