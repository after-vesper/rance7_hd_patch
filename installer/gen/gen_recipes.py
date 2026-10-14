# -*- coding: utf-8 -*-
"""Postprocess recipe implementations for the generation pipeline.

Each recipe takes the decoded source image and produces the 2x output.
Inputs available to every recipe:
  si    : source PIL image (RGBA or RGB)
  ai    : AI 2x RGB (base_up; clean model_up by default, forge_up for
          shipped-faithful auditing via BASE_MODE)
  lan   : Lanczos 2x of source (same mode as output)
  near  : NEAREST 2x of source

Recipes mirror docs/cg_map.md descriptions. Quality-equivalent mode: the AI
base may come from ONNX (slightly different from archived Forge output) —
recipes still apply the same intent.
"""

import numpy as np
from PIL import Image
from scipy.ndimage import (
    binary_dilation,
    generate_binary_structure,
    label,
)

import gen_audit as ga


def base_up(si, rgb=None):
    """AI 2x RGB for recipe input.

    'clean' uses model_up directly (exact 2x, no Forge quirks).
    'forge' uses forge_up (round8 resize + center crop-paste) which
    reproduces the shipped assets' black borders — useful only for
    auditing against the shipped payloads.
    rgb: precomputed 2x AI RGB (pipelined generation); skips inference.
    """
    if rgb is not None:
        return rgb
    mode = BASE_MODE
    if mode == 'forge':
        return ga.forge_up(si)
    return ga.model_up(si.convert('RGB'), batch=BATCH)


# 'clean' = production output; 'forge' = shipped-faithful audit output
BASE_MODE = 'clean'
# ONNX batch size for tile inference (all tiles are 256x256)
BATCH = 16


def _lan2x(si):
    return si.resize((si.width * 2, si.height * 2), Image.LANCZOS)


def _near2x(si):
    return si.resize((si.width * 2, si.height * 2), Image.NEAREST)


def _footprint(si, dilate=0):
    """2x alpha footprint mask of the original sprite."""
    a = np.asarray(si.convert('RGBA').getchannel('A')) > 0
    a2 = np.kron(a, np.ones((2, 2), dtype=bool))
    if dilate:
        a2 = binary_dilation(a2, iterations=dilate)
    return a2


def _clamp_alpha(out, si, dilate=0):
    """Alpha-clamp: zero out alpha outside original footprint (+dilation)."""
    fp = _footprint(si, dilate)
    a = np.asarray(out.getchannel('A')).copy()
    a[~fp] = 0
    out.putalpha(Image.fromarray(a))
    return out


def recipe_nearest(si):
    return _near2x(si.convert('RGBA'))


def recipe_lanczos(si):
    return _lan2x(si.convert('RGBA'))


def recipe_ai(si, rgb=None):
    """AI RGB + Lanczos alpha (default)."""
    rgb = base_up(si, rgb)
    if si.mode != 'RGBA':
        return rgb
    a = si.getchannel('A').resize(rgb.size, Image.LANCZOS)
    out = rgb.convert('RGBA')
    out.putalpha(a)
    return out


def recipe_ai_nearest_alpha(si, rgb=None):
    """AI RGB + NEAREST source alpha (HYB)."""
    rgb = base_up(si, rgb)
    a = si.getchannel('A').resize(rgb.size, Image.NEAREST)
    out = rgb.convert('RGBA')
    out.putalpha(a)
    return out


def recipe_ai_alpha_clamp(si, rgb=None):
    """AI RGB, alpha clamped to original footprint (halo fill fix)."""
    out = recipe_ai(si, rgb)
    return _clamp_alpha(out, si, dilate=0)


def recipe_padded_ai(si, canvas=None, rgb=None):
    """Tiny sprite rescue: pad onto transparent canvas, AI 2x, crop center,
    clamp alpha to orig footprint dilated 1px.

    Canvas rule from docs: 96x96 if sprite fits, else fitted w+16 x h+32
    (min 128px each side). rgb: precomputed AI 2x of the padded canvas.
    """
    w, h = si.size
    if canvas is None:
        cw, ch = (96, 96) if (w <= 96 and h <= 96) else (max(w + 16, 128),
                                                        max(h + 32, 128))
    else:
        cw, ch = canvas
    cw = max(cw, w)
    ch = max(ch, h)
    if rgb is not None:
        up = rgb
    else:
        cv = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
        cv.paste(si.convert('RGBA'), ((cw - w) // 2, (ch - h) // 2))
        up = base_up(cv)
    x0 = up.width // 2 - w
    y0 = up.height // 2 - h
    out = up.crop((x0, y0, x0 + w * 2, y0 + h * 2)).convert('RGBA')
    # Model output is RGB-only; synthesize alpha from the SOURCE alpha
    # (Lanczos 2x keeps soft edges), then clamp outside the footprint.
    a = si.convert('RGBA').getchannel('A').resize(out.size, Image.LANCZOS)
    out.putalpha(a)
    return _clamp_alpha(out, si, dilate=1)


def _ai_darkened_mask(ai_rgb, lan_rgb):
    """Mask where AI output is darker than Lanczos ref (dark-border fill)."""
    a = np.asarray(ai_rgb.convert('RGB'), np.float32).mean(2)
    r = np.asarray(lan_rgb.convert('RGB'), np.float32).mean(2)
    return (r - a) > 30, r, a


def _revert_components(ai_rgb, ref_rgb, mask, border_touch=True,
                       min_size=120, dilate=2, extra_mask=None):
    """Revert whole connected components of `mask` to ref pixels.

    Components reverted if they touch the outer border (when border_touch)
    or are >= min_size. Dilated by `dilate` px before blending.
    extra_mask: additional boolean mask always reverted (e.g. stroke
    thinning recipe).
    """
    lab, nc = label(mask)
    if nc == 0:
        comps = np.zeros_like(mask)
    else:
        sizes = np.bincount(lab.ravel())
        h, w = mask.shape
        sel = np.zeros(nc + 1, bool)
        for i in range(1, nc + 1):
            if sizes[i] < min_size:
                continue
            ys, xs = np.where(lab == i)
            if border_touch and (ys.min() == 0 or xs.min() == 0 or
                                 ys.max() == h - 1 or xs.max() == w - 1):
                sel[i] = True
            elif sizes[i] >= min_size:
                sel[i] = True
        comps = np.isin(lab, np.where(sel)[0])
    if extra_mask is not None:
        comps |= extra_mask
    if dilate:
        comps = binary_dilation(comps, iterations=dilate)
    out = np.asarray(ai_rgb.convert('RGB'), np.uint8).copy()
    ref = np.asarray(ref_rgb.convert('RGB'), np.uint8)
    out[comps] = ref[comps]
    return Image.fromarray(out, 'RGB')


def recipe_component_revert(si, rgb=None):
    """Dark-border fill fix: revert AI-darkened components touching the
    border or >=120px back to Lanczos (docs recipe)."""
    ai = base_up(si, rgb)
    lan = _lan2x(si.convert('RGB'))
    mask, _, _ = _ai_darkened_mask(ai, lan)
    out = _revert_components(ai, lan, mask)
    if si.mode == 'RGBA':
        a = si.getchannel('A').resize(out.size, Image.LANCZOS)
        out = out.convert('RGBA')
        out.putalpha(a)
        return _clamp_alpha(out, si, dilate=0)
    return out


def recipe_component_revert_aex(si, rgb=None):
    """component_revert + alpha-extras removal (alpha outside orig
    footprint removed)."""
    out = recipe_component_revert(si, rgb)
    return _clamp_alpha(out.convert('RGBA'), si, dilate=0)


def recipe_hybrid_clamp(si, rgb=None):
    """AI RGB + alpha clamp (cg10126)."""
    return recipe_ai_alpha_clamp(si, rgb)


def recipe_baked_text(si, rgb=None):
    """Baked-text panels: revert text regions (dark glyph cores + long
    dark/bright runs near them) to Lanczos; alpha clamped to footprint."""
    ai = base_up(si, rgb)
    lan = _lan2x(si.convert('RGB'))
    s = np.asarray(si.convert('RGB'), np.float32).mean(2)
    # glyph cores in SOURCE space: lum<150, components 4..400px
    core = s < 150
    lab, nc = label(core)
    sizes = np.bincount(lab.ravel())
    keep = np.isin(lab, np.where((sizes >= 4) & (sizes <= 400))[0])
    # to 2x space, dilate 6px, feather
    mask2 = np.kron(keep, np.ones((2, 2), bool))
    mask2 = binary_dilation(mask2, iterations=6)
    # v5 run-based: per scanline, runs of dark<130 or bright>200 >=40px
    # within ~15px of mask are reverted whole
    l2 = np.asarray(lan, np.float32).mean(2)
    near_mask = binary_dilation(mask2, iterations=15)
    rows, cols = mask2.shape
    run_mask = np.zeros_like(mask2)
    for axis in (0, 1):
        m = near_mask if axis == 0 else near_mask.T
        lum = l2 if axis == 0 else l2.T
        for i in range(m.shape[0]):
            line = m[i]
            if not line.any():
                continue
            dark = lum[i] < 130
            bright = lum[i] > 200
            for cand in (dark, bright):
                lab2, n2 = label(cand)
                for j in range(1, n2 + 1):
                    ys = np.where(lab2 == j)[0]
                    if len(ys) >= 40 and line[ys].any():
                        if axis == 0:
                            run_mask[i, ys] = True
                        else:
                            run_mask[ys, i] = True
    final = mask2 | run_mask
    out = np.asarray(ai.convert('RGB'), np.uint8).copy()
    ref = np.asarray(lan, np.uint8)
    out[final] = ref[final]
    res = Image.fromarray(out, 'RGB')
    if si.mode == 'RGBA':
        a = si.getchannel('A').resize(res.size, Image.LANCZOS)
        res = res.convert('RGBA')
        res.putalpha(a)
        return _clamp_alpha(res, si, dilate=0)
    return res


def recipe_unblended_fringe(si, rgb=None):
    """Number fonts (cg10171-73): AI RGB + orig alpha geometry; edge RGB
    decontaminated by un-blending against white backing."""
    out = recipe_ai(si, rgb)
    o = np.asarray(out.convert('RGBA'), np.float32).copy()
    a = np.asarray(si.convert('RGBA').getchannel('A'),
                   np.float32).repeat(2, 0).repeat(2, 1)
    # restore original alpha geometry (nearest)
    an = np.asarray(si.getchannel('A').resize(out.size, Image.NEAREST),
                    np.float32)
    o[:, :, 3] = an
    # un-blend edge RGB against white backing: rgb = (observed - (1-t)*255)/t
    edge = (an > 0) & (an < 255)
    t = (an[edge] / 255.0)[:, None]
    obs = o[:, :, :3][edge]
    o[:, :, :3][edge] = np.clip((obs - (1 - t) * 255) / np.maximum(t, 1e-3),
                                0, 255)
    return Image.fromarray(o.astype(np.uint8), 'RGBA')


def recipe_manual(si):
    """Hand-edited assets cannot be regenerated; caller should keep the
    shipped payload (exception)."""
    raise NotImplementedError('manual recipe asset -> exception payload')


RECIPES = {
    'nearest': recipe_nearest,
    'lanczos': recipe_lanczos,
    'ai': recipe_ai,
    'ai_nearest_alpha': recipe_ai_nearest_alpha,
    'ai_alpha_clamp': recipe_ai_alpha_clamp,
    'padded_ai': recipe_padded_ai,
    'component_revert': recipe_component_revert,
    'component_revert_aex': recipe_component_revert_aex,
    'hybrid_clamp': recipe_hybrid_clamp,
    'baked_text': recipe_baked_text,
    'unblended_fringe': recipe_unblended_fringe,
    'manual': recipe_manual,
}


def apply(recipe, si, rgb=None):
    fn = RECIPES.get(recipe)
    if fn is None:
        raise ValueError('unknown recipe %r' % recipe)
    if rgb is None:
        return fn(si)
    # pipelined path: precomputed AI RGB (for padded_ai the caller passes
    # the already-padded-canvas inference result)
    try:
        return fn(si, rgb=rgb)
    except TypeError:
        return fn(si)
