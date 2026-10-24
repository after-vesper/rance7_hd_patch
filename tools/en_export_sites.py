# -*- coding: utf-8 -*-
"""Transplant the jp-anchored HD sites onto the English (Kagura) AIN.

The en build rewrote a number of UI functions during localization, so the
shared hd_sites.json only resolves ~74% of its sites there; the rest fall
into the unsafe relaxed fallback or ambiguity. This tool aligns each jp
function body against its en counterpart and re-anchors every site at the
aligned en position, reading the live operand value straight out of the en
binary:

    en_val == site.old            -> keep site.new            (exact)
    site.new == 2 * site.old      -> new = 2 * en_val         (assumed x2)
    otherwise                     -> review queue (not emitted)

Groups that do not fully transplant are omitted from the en site file (they
would otherwise trigger the relaxed fallback, which blindly rewrites every
operand equal to `old`) and reported in the review JSON instead.

Usage:
    python tools/en_export_sites.py work/lang/en/Rance7.ain
       [--jp-dump dump/Rance7_raw.jam] [--en-dump <cached jam>]
       [--sites tools/hd_sites.json]
       [--out tools/hd_sites_en.json] [--review work/en_review.json]
"""
import bisect
import difflib
import json
import os
import re
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apply_hd_ain import (ALICE, CTX, VOLATILE_OPS, decrypt, is_encrypted,
                          norm_ops_tokens, norm_tok, parse_raw_dump,
                          parse_sections)

CTX_HALF = 3

# Operand-field offset per opcode (same convention as hd_sites.json delta).
DELTA_BY_OP = {"PUSH": 2, "F_PUSH": 2, "SH_LOCALASSIGN": 6,
               ".LOCALASSIGN": 10, ".LOCALPLUSA": 10, ".LOCALMINUSA": 10,
               ".STRUCTASSIGN": 10, ".F_STRUCTASSIGN": 10,
               ".F_LOCALASSIGN": 10}

# Hand-ported pixel constants for functions the localization rewrote.
# Each entry is (named-dump instruction index, expected en value, new value)
# inside the *named* (-c) dump of the en function; new is normally 2x the
# en constant.  Values are ints except F_PUSH entries which are floats.
MANUAL_SITES = {
    "tagSankaList@drawInfo": [
        (13, 20, 40), (23, 37, 74), (24, 102, 204), (30, 258, 516),
        (31, 93, 186), (34, 6, 12), (35, 2, 4), (40, 31, 62),
        (142, 29, 58), (148, 262, 524), (149, 31, 62), (171, 29, 58),
        (184, 31, 62), (188, 2, 4), (189, 2, 4), (205, 31, 62),
        (230, 39, 78),
    ],
    "tagSelect@createText": [
        (17, 12, 24), (25, 2, 4), (27, 10, 20), (29, 42, 84),
        (44, 12, 24), (52, 20, 40), (80, 2, 4), (85, 364, 728),
        (92, 512, 1024), (159, 364, 728), (162, 364, 728), (193, 5, 10),
    ],
    "tagBattle@showNumber2": [
        (74, 34, 68), (75, 42, 84), (85, 34, 68), (86, 42, 84),
        (94, 312, 624), (109, 312, 624), (110, 312, 624),
        (125, 312, 624), (141, -34, -68), (156, -34, -68),
        (170, 42, 84), (174, 598, 1196), (189, 42, 84), (191, 34, 68),
        (198, 598, 1196), (200, 34, 68),
    ],
    "tagBattleButton@add": [
        (29, 38, 76), (38, 16, 32),
        (68, 2, 4), (73, 2, 4), (78, 2, 4), (83, 2, 4),
        (86, 7, 14), (87, 7, 14), (88, 7, 14), (89, 7, 14),
        (117, 97, 194), (122, 48, 96), (153, 128, 256), (157, 16, 32),
        (178, 172, 344), (183, 57, 114), (209, 150, 300), (223, 16, 32),
    ],
    "tagBattleButton@setActionShow": [(23, 38, 76)],
    "tagBattleDungeon@create": [
        (75, 18, 36), (107, 18, 36), (118, 18, 36),
        (127, 90, 180),
    ],
    "tagBattleFlag@draw": [(33, 14, 28)],
    # tagDrawText text area inside the battle balloon (en-only class):
    # setDimensions, setMargins and the -10 position offsets were left
    # in SD units; setFontSize(24->48) was already transplanted.
    "tagBattleMessage@create": [
        (174, 329, 658), (175, 115, 230),
        (178, 6, 12), (179, 2, 4), (180, 10, 20), (181, 4, 8),
        (187, 10, 20), (192, 10, 20),
    ],
    "tagBattleMessage@drawName": [(9, 188, 376), (25, 1.5, 3.0)],
    "tagBattlePreInfo@create": [
        (7, 1, 2), (8, 2, 4), (21, 365, 730), (37, 55, 110),
        (38, 142, 284), (29, 1.5, 3.0),
    ],
    "tagBattlePreInfo@drawInfo": [
        (21, 20, 40), (31, 102, 204), (32, 36, 72), (33, 262, 524),
        (34, 93, 186), (35, 31, 62), (141, 29, 58), (175, 29, 58),
        (198, 39, 78), (216, 2, 4), (217, 2, 4),
    ],
    "tagBushoInfo@createAction": [
        (16, 14, 28), (108, 14, 28), (134, 14, 28),
    ],
    "tagTitleBar@create": [
        (16, 4, 8), (21, 4, 8), (30, 24, 48), (39, 20, 40),
    ],
    "tagMapInfo@setMapNo": [(58, 20, 40)],
    "tagSankaList@create": [
        (7, 1, 2), (8, 282, 564), (16, 11, 22), (17, 37, 74),
        (22, 120, 240), (23, 28, 56), (31, 193, 386), (32, 424, 848),
        (40, 1, 2), (41, 282, 564), (43, 294, 588), (95, 299, 598),
        (96, 286, 572), (108, 13, 26), (109, 484, 968), (125, 71, 142),
        (51, 1.5, 3.0),
    ],
    "tagStoreData@create": [
        (70, 253, 506), (71, 53, 106), (79, 193, 386), (81, 60, 120),
        (82, 53, 106), (101, 12, 24), (128, 253, 506), (129, 53, 106),
        (143, 16, 32), (185, 193, 386), (186, 28, 56), (189, 2, 4),
        (190, 2, 4), (191, 2, 4), (192, 2, 4), (221, 193, 386),
        (222, 28, 56), (225, 2, 4), (226, 2, 4), (227, 2, 4),
        (228, 2, 4), (245, 25, 50), (251, 18, 36),
        (295, 14, 28), (296, 14, 28), (305, 14, 28),
    ],
    "tagSeiryoku@createMessage": [
        (33, 24, 48), (36, 448, 896), (37, 35, 70), (77, 35, 70),
        (104, 527, 1054), (105, 35, 70), (107, 102, 204),
        (138, 550, 1100),
    ],
    "tagMusicMode@create": [
        (44, 83, 166), (45, 135, 270), (57, 92, 184), (58, 4, 8),
        (60, 197, 394), (86, 699, 1398), (87, 132, 264),
        (117, 310, 620), (118, 451, 902), (123, 451, 902),
        (124, 451, 902), (129, 535, 1070), (130, 451, 902),
        (135, 619, 1238), (136, 451, 902), (141, 689, 1378),
        (142, 82, 164), (222, 97, 194), (223, 40, 80), (224, 12, 24),
        (68, 1.5, 3.0),
    ],
    "tagComment@show": [
        (39, 9, 18), (40, 5, 10), (41, 9, 18), (42, 5, 10),
        (47, 20.940722, 41.881444), (61, 320, 640), (62, 16, 32),
        (96, 4, 8), (107, 18.323132, 36.646264), (124, 320, 640),
        (125, 400, 800), (149, 11, 22), (175, 15, 30), (178, 8, 16),
        (222, 6, 12), (225, 6, 12), (233, 5, 10), (236, 5, 10),
        (241, 6, 12), (244, 6, 12), (252, 5, 10), (255, 5, 10),
        (261, 5, 10), (264, 5, 10), (265, 5, 10), (271, 5, 10),
        (273, 5, 10), (274, 5, 10),
    ],
    "tagComment@setPos": [
        (31, 11, 22), (38, 20, 40), (82, 568, 1136), (87, 568, 1136),
    ],
    "tagHoryo@drawText": [
        (18, 28.793491, 57.586982), (31, 36, 72), (33, 102, 204),
        (37, 258, 516), (38, 93, 186), (41, 6, 12), (42, 2, 4),
        (47, 31, 62), (80, 102.0, 204.0),
    ],
    "tagForceFull@drawText": [
        (18, 28.793491, 57.586982), (31, 36, 72), (33, 102, 204),
        (37, 258, 516), (38, 93, 186), (41, 6, 12), (42, 2, 4),
        (47, 31, 62), (82, 102.0, 204.0),
    ],
    # The en title added a 5th "Credits" button; its 4th nY pitch (39->78)
    # has no jp counterpart so it must be added by hand.
    "tagTitle@create": [(112, 39, 78)],
    # en duplicated code paths whose jp counterparts carry one site each:
    # the second copy needs the same x2 constants.
    # Number exit-slide animation: the 312 center-line assignments, row
    # spacing (42), digit height (34) and slide-in offset (-34) mirror
    # showNumber2 but sit inside PUSHLOCALPAGE/PUSH index sequences that
    # the index guard filters out, so they are ported by hand.
    "tagBattle@hideNumber": [
        (38, 34, 68), (42, 42, 84), (49, 34, 68), (53, 42, 84),
        (58, 312, 624), (73, 312, 624), (74, 312, 624), (89, 312, 624),
        (105, -34, -68), (120, -34, -68), (128, 250, 500),
    ],
    # Row spacing inside the en-only collection wrapper (this struct does
    # not exist in jp - jp keeps the 42 spacing inline in showNumber).
    "tagBattleNumberCollection@setPos": [(14, 42, 84), (32, 42, 84)],
    # Battle gauge fade-out: the alpha-map rows, gradient and fill rect
    # were left at SD coordinates so half of the bar survived the fade
    # as a translucent residue.
    "tagBattleBar@setTransparency": [
        (2, 16, 32), (10, 6, 12), (23, 16, 32), (32, -81, -162),
        (34, 16, 32), (36, 132, 264), (52, 6, 12), (64, 6, 12),
        (72, 10, 20), (77, 27, 54), (79, 400, 800), (80, 1, 2),
    ],
    "tagBattleBar@update": [(51, 16, 32), (72, 16, 32)],
    # Turn-transition display: the "Turn" word sprite position, its
    # digit-centering math and the per-digit/adjustment constants stayed
    # at SD values while the number itself was patched.
    "tagTurnStart@CalculateWordPosition": [(60, 17, 34), (62, 448, 896), (66, 73, 146)],
    "tagTurnStart@run": [(23, 464, 928)],
    "tagTurnStart@create": [(53, 448, 896), (54, 464, 928)],
    "tagBushoList@createButton": [
        (137, 5, 10), (141, 31, 62), (189, 5, 10),
    ],
    # Save/load window title-bar labels ("Load Window", "Auto-Save Data",
    # "Save Data Storage", deletion pane) - the en build moved them a few
    # pixels, so the jp positions do not transfer; double the en values.
    "tagSaveStore@create": [
        (37, 42, 84), (38, 12, 24), (42, 156, 312), (66, 2, 4),
        (67, 238, 476), (71, 256, 512), (95, 269, 538), (96, 2, 4),
        (100, 245, 490), (124, 706, 1412), (125, 448, 896),
        (129, 83, 166),
        (54, 1.5, 3.0), (83, 1.5, 3.0), (112, 1.5, 3.0),
        (141, 1.5, 3.0),
    ],
    # Empty entries: jp sites intentionally unmapped.  tagComment@create /
    # show2 are 3/7-instruction stubs in the en build (implementation
    # dropped), and tagBattle@showNumber is a thin wrapper - its pixel
    # constants were ported to tagBattle@showNumber2 above.
    # The en build replaced the message text layout engine with
    # WordWrapperSR (word wrap + alignment); none of it exists in jp.
    # Its SD window metrics, margins, and font sizes need x2.
    "WordWrapperSR@SetInitialValuesToMessageWindowDefaults": [
        (12, 521, 1042), (13, 6, 12), (14, 6, 12),
        (15, 69, 138), (16, 7, 14), (17, 9, 18),
        (31, 752, 1504), (34, 552, 1104),
    ],
    "WordWrapperSR@SetInitialValuesToDefaultValues": [
        (10, 26.0, 52.0),
        (20, 521, 1042), (21, 6, 12), (22, 6, 12),
        (23, 69, 138), (24, 7, 14), (25, 9, 18),
    ],
    "WordWrapperSR@RestartForMessageLog": [
        (9, 773, 1546), (10, 20, 40), (11, 20, 40), (22, 20, 40),
    ],
    # font-size threshold (>26) and TryAdjustTextRect x nudge (-8/+8 px)
    "WordWrapperSR@Run": [
        (159, 26.0, 52.0), (407, -8, -16), (408, 8, 16),
    ],
    # BoldWidth/EdgeWidth for the main message window + default-size
    # substitution (floatValue==24->48 then floatValue=26->52) + second
    # BoldWidth normalization block for per-entry styles
    "WordWrapperSR@ConvertInputMessageTextModel": [
        (91, 0.38, 0.76), (97, 0.25, 0.5), (102, 1.75, 3.5),
        (332, 24.0, 48.0), (351, 26.0, 52.0),
        (816, 0.25, 0.5), (822, 0.38, 0.76),
        (845, 0.38, 0.76), (851, 0.25, 0.5),
    ],
    "TextStyle@SetDefaults": [(1, 24.0, 48.0), (2, 0.25, 0.5)],
    # System Information panes: tagDrawText areas kept SD dimensions so
    # text wrapped at half width.  Also title-bar width, edge width,
    # metrics max width, and the hyotan X formula.
    # NOTE: metrics member4 (1400) is deliberately NOT doubled - the jp
    # patch leaves it at 1400 too; doubling made textDrawCenter digits
    # render with a doubled stroke.
    "tagSystemInfo@create": [
        (31, 424, 848), (43, 1.5, 3.0),
        (263, 262, 524), (264, 125, 250),
        (357, 416, 832), (358, 140, 280),
    ],
    "tagSystemInfo@getHyotanX": [(0, 20, 40), (1, 54, 108)],
    # Remaining tagDrawText / tagTitleBar pixel constants that the auto
    # transplant missed (the localization rewrote these functions; the jp
    # anchors do not cover them).  Colors, alpha and z-order args are
    # intentionally untouched.
    "tagTitleBar@setMargin": [(17, 24, 48)],
    "tagMessageName@create": [
        (41, -20, -40), (45, -8, -16), (49, 205, 410), (50, 460, 920),
    ],
    "tagBattleBar@create": [(87, 2, 4)],
    "tagSelect@create": [(158, 308, 616), (166, 1.5, 3.0)],
    "tagSansenList@create": [
        (16, 1, 2), (17, 282, 564), (19, 294, 588), (27, 1.5, 3.0),
    ],
    "tagSansenTeki@create": [
        (16, 37, 74), (17, 282, 564), (19, 336, 672), (166, 1.5, 3.0),
    ],
    "tagHoryo@create": [
        (26, 355, 710), (27, 69, 138),
        (30, 8, 16), (31, 8, 16), (32, 5, 10), (33, 5, 10),
        (50, 1, 2), (51, 282, 564), (53, 355, 710), (61, 1.5, 3.0),
    ],
    "tagItemList@create": [
        (23, 1, 2), (24, 282, 564), (26, 336, 672), (34, 1.5, 3.0),
    ],
    "tagForceFull@create": [(23, 360, 720), (31, 1.5, 3.0)],
    "tagForce@create": [
        (18, 1, 2), (19, 282, 564), (21, 294, 588), (29, 1.5, 3.0),
    ],
    "tagBushoList@create": [(140, 385, 770), (158, 1.5, 3.0)],
    "tagBushoInfo@create": [(36, 1.5, 3.0)],
    "tagBusho@create": [
        (55, 14, 28), (68, 2, 4), (69, 2, 4), (74, 14, 28),
        (97, 51, 102), (98, 14, 28), (107, 2, 4), (108, 2, 4),
    ],
    "tagBusho@create2": [
        (90, 14, 28), (103, 2, 4), (104, 2, 4), (109, 14, 28),
        (148, 80, 160), (149, 14, 28), (158, 2, 4), (159, 2, 4),
    ],
    "tagSystemMessage@create": [
        (62, 61, 122), (65, 351, 702), (75, 4, 8), (76, 2, 4),
        (116, 329, 658), (117, 115, 230),
        (120, 8, 16), (121, 2, 4), (122, 8, 16), (123, 8, 16),
        (175, 546, 1092), (183, 1.5, 3.0),
    ],
    "tagSystemMessage@createRelation": [
        (43, 4, 8), (44, 4, 8), (49, 318, 636), (50, 258, 516),
    ],
    "tagMikadoNote@create": [(30, 424, 848), (38, 1.5, 3.0)],
    # Action-list item (map commands): the difficulty-number column and
    # the label margins stayed in SD units, so the number was squeezed
    # into a 16px box at the chip edge.
    "tagCommand@create": [
        (149, 2, 4), (150, 1, 2), (151, 2, 4), (152, 2, 4),
        (159, 2, 4), (160, 16, 32), (161, 2, 4), (162, 2, 4),
        (219, 2, 4), (220, 4, 8), (221, 2, 4),
        (224, 16, 32), (239, 16, 32),
    ],
    # Commander-list rows: drawParamSpecial got the 14->28 font site but
    # drawParamNormal did not, leaving troop counts and stats at SD size.
    "tagBusho@drawParamNormal": [(9, 14, 28)],
    # Item sprite fallback text (no-CG items): font size stayed at 10.
    "tagItem@loadCg": [(21, 10, 20)],
    "tagCgMode@create": [
        (49, 21, 42), (50, 5, 10), (52, 720, 1440), (60, 1.5, 3.0),
    ],
    "tagComment@create": [],
    "tagComment@show2": [],
    "tagBattle@showNumber": [],
    # Drag out-of-bounds clamp blocks (en-only code).  The jp functions
    # instead warp the cursor back to the last valid mouse position, so
    # the jp sites only cover the initial OOB test and leave the clamp
    # constants at SD scale.  Without these the clamped face position,
    # the boundary re-test and the cursor recompute disagree with the
    # doubled grab offset, so the no-UPDATE loop never converges and the
    # game hard-locks with the cursor pinned to the top-left corner.
    "tagSankaList@dragBusho": [
        (174, 1, 2), (180, 1, 2),
        (183, 65, 130), (191, -67, -134),
        (197, 72, 144), (205, -74, -148),
        (213, 32, 64), (220, 36, 72),
    ],
    "tagSansenList@dragBusho": [
        (219, 1, 2), (225, 1, 2),
        (228, 65, 130), (236, -67, -134),
        (242, 72, 144), (250, -74, -148),
        (258, 32, 64), (265, 36, 72),
    ],
    "tagItemList@dragItem": [
        (197, 1, 2), (203, 1, 2),
        (206, 64, 128), (214, -66, -132),
        (220, 64, 128), (228, -66, -132),
        (236, 32, 64), (243, 32, 64),
    ],
    "tagBushoInfo@dragItem": [
        (196, 1, 2), (202, 1, 2),
        (205, 64, 128), (213, -66, -132),
        (219, 64, 128), (227, -66, -132),
        (235, 32, 64), (242, 32, 64),
    ],
    "tagSaveStore@dragData": [
        (207, 1, 2), (213, 1, 2),
        (216, 60, 120), (224, -62, -124),
        (230, 53, 106), (238, -55, -110),
        (246, 30, 60), (253, 26, 52),
    ],
}

# Auto-ported sites that must be dropped: the en build happens to carry
# the same constant at a position whose meaning differs (e.g. an RGB
# color argument where jp had a pixel value), so x2 would corrupt data.
# Entries are (named_idx) resolved the same way as MANUAL_SITES.
DROP_SITES = {
    # tagTitleBar@setShadowColor(198, 110, 90) - the 110/90 are RGB
    # channels, not pixel values; the auto transplant doubled them.
    "tagBattleMessage@drawName": [21, 22],
    # tagDrawText@create(nLineCount, nCharCount, nSpace, nMode):
    # nLineCount/nCharCount are counts, not pixels - only nSpace (arg2)
    # may be doubled.  These sites doubled the count arguments.
    "tagHoryo@create": [16],                      # nLineCount 18
    "tagItemList@create": [44],                   # nLineCount 8
    "tagBusho@create": [92],                      # nCharCount 1
    "tagBusho@create2": [143],                    # nCharCount 1
    "tagSystemMessage@createRelation": [34],      # nCharCount 1
    "tagBattleMessage@create": [169],             # nCharCount 1
    # tagTitleBar@setShadowColor(98, 161, 105): RGB channels, not pixels.
    # The 105 stayed unpatched while 98/161 were doubled.
    "tagSankaList@create": [46, 47],
    "tagItemList@create": [29, 30],
    "tagCgMode@create": [55, 56],
    "tagMusicMode@create": [63, 64],
}


def align_tok(ins):
    """(op, normalized operand tuple) with volatile operands masked."""
    _addr, op, ops = ins
    if op in VOLATILE_OPS:
        return (op,)
    return (op, tuple(norm_ops_tokens(op, ops) or ()))


def func_index(funcs):
    """name -> [func, ...]; also flat sorted addr list for lookup."""
    by_name = {}
    for f in funcs:
        by_name.setdefault(f["name"], []).append(f)
    return by_name


def find_jp_func(jp_by_name, func_name, site_addr):
    """Return the jp function body whose instruction list contains
    site_addr (fall back to the first copy)."""
    cands = jp_by_name.get(func_name, [])
    for f in cands:
        for a, _o, _ops in f["instrs"]:
            if a == site_addr:
                return f
    return cands[0] if cands else None


def i32_at(dec, code_off, addr, delta):
    off = code_off + addr + delta
    if off + 4 > len(dec):
        return None
    return struct.unpack_from("<i", dec, off)[0]


CALL_OPS = frozenset(["CALLFUNC", "CALLMETHOD", "CALLSYS", "CALLHLL"])


def parse_named_dump(path):
    """Parse a `-c` (named) jam dump -> {func name: [[(op, ops)], ...]}.

    Operand text keeps resolved call-target names (e.g. CALLFUNC 文字サイズ),
    which stay identical across localized builds even when the call index
    differs - unlike the raw -C dump which only carries volatile indices.
    """
    out = {}
    name = None
    buf = None
    for line in open(path, encoding="utf-8", errors="replace"):
        if line.startswith("; "):
            n = line[2:].strip()
            if n.startswith(("ARG", "VAR", "RETURN", "LOCAL")):
                continue
            if name is not None and buf:
                out.setdefault(name, []).append(buf)
            name = n
            buf = None
        elif line.startswith("FUNC "):
            buf = []
        elif line.startswith("ENDFUNC"):
            if name is not None and buf is not None:
                out.setdefault(name, []).append(buf)
            buf = None
        elif buf is not None and line.startswith("\t"):
            parts = line.strip().split(None, 1)
            if parts:
                buf.append((parts[0], parts[1] if len(parts) > 1 else ""))
    if name is not None and buf:
        out.setdefault(name, []).append(buf)
    return out


def call_sig(named_ops, i, half=6):
    """Ordered (offset, callee-name) pairs for call instructions near i."""
    sig = []
    lo = max(0, i - half)
    hi = min(len(named_ops), i + half + 1)
    for k in range(lo, hi):
        op, ops = named_ops[k]
        if op in CALL_OPS:
            sig.append((k - i, ops.strip()))
    return tuple(sig)


def pair_named(named_list, raw_func):
    """Pick the named-dump copy whose opcode sequence matches raw_func.

    The raw (-C) dump emits `EOF` pseudo-instructions that the named (-c)
    dump omits, so comparison masks them.  Returns (named_ops, n2r) where
    n2r maps named index -> raw instr index, or (None, None) on mismatch.
    """
    raw_ops = [ins[1] for ins in raw_func["instrs"]]
    real_idx = [i for i, op in enumerate(raw_ops) if op != "EOF"]
    real_ops = [raw_ops[i] for i in real_idx]
    for cand in named_list:
        if [op for op, _o in cand] == real_ops:
            return cand, real_idx
    return None, None


def build_ctx(ins, j):
    """CTX_HALF instructions each side of ins[j]; same [addr, op, ops]
    schema as hd_sites.json."""
    lo = max(0, j - CTX_HALF)
    hi = min(len(ins), j + CTX_HALF + 1)
    return [[a, op, ops] for a, op, ops in ins[lo:hi]]


def transplant_group(jp_func, en_copies, grp, dec, code_off,
                     jp_named_list=None, en_named_list=None):
    """Try to re-anchor every site in grp inside an en function body.

    Alignment runs on the opcode-only sequence: the localization kept
    instruction structure but changed operand values, so opcode alignment
    survives where token alignment would split on every differing
    immediate.  Operand differences are then validated per site by
    reading the en binary.

    Returns (en_sites, reasons) - en_sites is None when the group did not
    fully transplant.
    """
    # Alignment ignores pure type-cast ops: the en build sprinkles extra
    # ITOB/ITOF casts around arguments, which would otherwise shatter every
    # equal block.  Mapping is kept in terms of real instruction indices.
    SKIP = frozenset(["ITOB", "ITOF", "FTOI", "FTOB"])
    jp_idx = [i for i, ins in enumerate(jp_func["instrs"])
              if ins[1] not in SKIP]
    jp_ops = [jp_func["instrs"][i][1] for i in jp_idx]
    best = None
    for en_f in en_copies:
        en_idx = [i for i, ins in enumerate(en_f["instrs"])
                  if ins[1] not in SKIP]
        en_ops_seq = [en_f["instrs"][i][1] for i in en_idx]
        sm = difflib.SequenceMatcher(None, jp_ops, en_ops_seq,
                                     autojunk=False)
        blocks = sm.get_matching_blocks()
        score = sum(b.size for b in blocks)
        if best is None or score > best[0]:
            best = (score, sm, en_f, en_idx)
    if best is None:
        return None, ["no en copy"]
    _score, sm, en_f, en_idx = best
    en_ins = en_f["instrs"]
    jp_named, jp_n2r = (pair_named(jp_named_list, jp_func)
                        if jp_named_list else (None, None))
    en_named, en_n2r = (pair_named(en_named_list, en_f)
                        if en_named_list else (None, None))
    # raw instr index -> named-dump index (raw dumps contain extra EOF
    # pseudo-instructions that named dumps omit)
    jp_r2n = ({r: n for n, r in enumerate(jp_n2r)}
              if jp_n2r is not None else None)
    en_r2n = ({r: n for n, r in enumerate(en_n2r)}
              if en_n2r is not None else None)

    # map: jp instruction index -> en instruction index.  Equal blocks map
    # directly; equal-length "replace" regions are paired positionally when
    # the opcodes agree (same instruction shape, different operands).
    j2e = {}
    for tag, a1, a2, b1, b2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(a2 - a1):
                j2e[jp_idx[a1 + k]] = en_idx[b1 + k]
        elif tag == "replace" and (a2 - a1) == (b2 - b1):
            for k in range(a2 - a1):
                if jp_ops[a1 + k] == en_ops_seq[b1 + k]:
                    j2e[jp_idx[a1 + k]] = en_idx[b1 + k]

    fallback_extras = []

    # call-name fallback: when the jp site sits in a rewritten block, try to
    # re-anchor it by the ordered callee names surrounding it (function and
    # method names survive localization even when code is restructured).
    # Indexes j/e are raw instr indexes; named dumps omit EOF pseudo-ops so
    # lookups go through r2n maps.
    def fallback_map(j, s):
        if jp_r2n is None or en_r2n is None:
            return None
        nj = jp_r2n.get(j)
        if nj is None:
            return None
        want = call_sig(jp_named, nj)
        if want:
            cand = None
            for e in range(len(en_ins)):
                if en_ins[e][1] != s["op"]:
                    continue
                ne = en_r2n.get(e)
                if ne is not None and call_sig(en_named, ne) == want:
                    if cand is not None:
                        cand = None  # ambiguous
                        break
                    cand = e
            if cand is not None:
                return cand
        # call-argument fallback: site is an operand push feeding a known
        # callee (e.g. PUSH 15 before CALLFUNC 文字サイズ).  Anchor by the
        # callee name plus the instruction distance to that call, which
        # encodes the argument position counting from the last argument.
        def next_call(ops_list, i, limit=12):
            for k in range(i + 1, min(len(ops_list), i + 1 + limit)):
                if ops_list[k][0] in CALL_OPS:
                    return (k - i, ops_list[k][1].strip())
            return None
        want2 = next_call(jp_named, nj)
        if want2 is None:
            return None
        cands = []
        for e in range(len(en_ins)):
            if en_ins[e][1] != s["op"]:
                continue
            ne = en_r2n.get(e)
            if ne is not None and next_call(en_named, ne) == want2:
                cands.append(e)
        if len(cands) == 1:
            return cands[0]
        # Multi-candidate: for repetitive calls like 文字サイズ(15) every
        # occurrence carries the same pixel constant, so patch all
        # candidates.  Candidates whose en value differs from jp `old` are
        # only rewritten when the site is a plain x2 transform and the en
        # value is a plausible pixel constant (same sign, not a -1
        # sentinel) - e.g. the localization bumped an emphasis font size
        # from 40 to 80, which still needs its own doubling.
        extra = []
        for e in cands:
            ev = i32_at(dec, code_off, en_ins[e][0], s["delta"])
            if ev is None:
                continue
            if ev == s["old"]:
                extra.append(e)
            elif (s["new"] == 2 * s["old"] and ev != -1
                  and (ev > 0) == (s["old"] > 0) and abs(ev) <= 4000):
                extra.append(e)
        if extra:
            fallback_extras.extend((s, e) for e in extra)
        return extra[0] if extra else None

    out_sites = []
    reasons = []
    for s in grp:
        # locate the site's own instruction in the jp body
        try:
            j = next(i for i, (a, _o, _ops) in enumerate(jp_func["instrs"])
                     if a == s["addr"])
        except StopIteration:
            reasons.append("site addr 0x%x not in jp body" % s["addr"])
            continue
        e = j2e.get(j)
        anchor = "align"
        if e is None:
            e = fallback_map(j, s)
            anchor = "callsig"
        if e is None:
            reasons.append("site @jp 0x%x inside changed block" % s["addr"])
            continue
        e_addr, e_op, e_ops = en_ins[e]
        if e_op != s["op"]:
            reasons.append("op mismatch @en 0x%x: %s vs %s"
                           % (e_addr, e_op, s["op"]))
            continue
        # operand must actually exist in the en instruction
        en_toks = norm_ops_tokens(e_op, e_ops)
        if s["op"] in VOLATILE_OPS or en_toks is None:
            reasons.append("volatile op site @en 0x%x" % e_addr)
            continue
        en_val = i32_at(dec, code_off, e_addr, s["delta"])
        if en_val is None:
            reasons.append("operand read OOB @en 0x%x" % e_addr)
            continue
        assumed = False
        if en_val == s["old"]:
            new_val = s["new"]
        elif s["new"] == 2 * s["old"]:
            new_val = 2 * en_val
            assumed = True
        else:
            reasons.append("en operand differs @0x%x: jp %d en %d "
                           "(non-x2 transform %d->%d)"
                           % (e_addr, s["old"], en_val, s["old"], s["new"]))
            continue
        out_sites.append({
            "func": s["func"],
            "idx": s["idx"],
            "addr": e_addr,
            "delta": s["delta"],
            "op": e_op,
            "old": en_val,
            "new": new_val,
            "ctx": build_ctx(en_ins, e),
            "rank": s.get("rank", 0),
            "n_match": s.get("n_match", 1),
            **({"assumed": 1} if assumed else {}),
            **({"callsig": 1} if anchor == "callsig" else {}),
        })
    # emit multi-candidate call-argument matches collected along the way,
    # skipping en positions already emitted by the per-site pass
    emitted_e = {s["addr"] for s in out_sites}
    done_e = set()
    for s, e in fallback_extras:
        e_addr = en_ins[e][0]
        if e_addr in emitted_e or e_addr in done_e:
            continue
        en_val = i32_at(dec, code_off, e_addr, s["delta"])
        if en_val is None:
            continue
        if en_val == s["old"]:
            new_val, assumed = s["new"], False
        elif s["new"] == 2 * s["old"]:
            new_val, assumed = 2 * en_val, True
        else:
            continue
        done_e.add(e_addr)
        out_sites.append({
            "func": s["func"],
            "idx": s["idx"],
            "addr": e_addr,
            "delta": s["delta"],
            "op": en_ins[e][1],
            "old": en_val,
            "new": new_val,
            "ctx": build_ctx(en_ins, e),
            "rank": s.get("rank", 0),
            "n_match": s.get("n_match", 1),
            "callsig": 1,
            **({"assumed": 1} if assumed else {}),
        })
    if not out_sites:
        return None, reasons

    # recompute rank: the position of each en-anchored site among all
    # positions matching the group signature in the chosen en copy, so
    # the applier's extra-match disambiguation stays correct
    from apply_hd_ain import ctx_match_at, instr_matches
    b0 = out_sites[0]
    tok_idx = (b0["delta"] - 2) // 4
    ci = next((i for i, c in enumerate(b0["ctx"]) if c[0] == b0["addr"]),
              -1)
    self_toks = (norm_ops_tokens(b0["op"], b0["ctx"][ci][2])
                 if ci >= 0 else None)
    probe = {"tok_idx": tok_idx, "old": b0["old"], "new": b0["new"]}
    matches = []
    for j in range(len(en_ins)):
        if not instr_matches(en_ins[j], b0["op"], self_toks,
                             skip_tok=tok_idx):
            continue
        if not ctx_match_at(en_ins, j, b0["ctx"], ci, site=probe):
            continue
        matches.append(j)
    addr_pos = {en_ins[j][0]: n for n, j in enumerate(matches)}
    for s in out_sites:
        if s["addr"] in addr_pos:
            s["rank"] = addr_pos[s["addr"]]
        else:
            s["rank"] = -1
    return out_sites, []


def emit_manual_sites(en_by_name, en_named, dec, code_off):
    """Resolve the hand-ported MANUAL_SITES table against the en binary.

    Each entry (named_idx, expected, new) is verified by reading the live
    operand: a site is only emitted when the en instruction at that
    position carries exactly `expected`, so a table that drifts out of
    sync with the binary reports mismatches instead of patching wrong
    bytes.  Returns (sites, review_entries).
    """
    from apply_hd_ain import ctx_match_at, instr_matches
    sites, review = [], []
    for fname, entries in MANUAL_SITES.items():
        copies = en_by_name.get(fname)
        if not copies:
            review.append({"func": fname, "reason": "manual: missing_func",
                           "count": len(entries)})
            continue
        en_f = copies[0]
        en_ins = en_f["instrs"]
        nops, n2r = (pair_named(en_named.get(fname), en_f)
                     if en_named.get(fname) else (None, None))
        if n2r is None:
            review.append({"func": fname,
                           "reason": "manual: named/raw pairing failed",
                           "count": len(entries)})
            continue
        grp_sites, bad = [], []
        for n, (nidx, old, new) in enumerate(entries):
            if nidx >= len(n2r):
                bad.append("idx %d OOB" % nidx)
                continue
            e = n2r[nidx]
            addr, op, _ops = en_ins[e]
            delta = DELTA_BY_OP.get(op)
            if delta is None:
                bad.append("idx %d op %s" % (nidx, op))
                continue
            raw = i32_at(dec, code_off, addr, delta)
            if raw is None:
                bad.append("idx %d operand OOB" % nidx)
                continue
            if op in ("F_PUSH", ".F_STRUCTASSIGN", ".F_LOCALASSIGN"):
                got = struct.unpack("<f", struct.pack("<i", raw))[0]
                if abs(got - float(old)) > 1e-3:
                    bad.append("idx %d: en %r != expected %r"
                               % (nidx, got, old))
                    continue
                new_bits = struct.unpack("<i",
                                         struct.pack("<f", float(new)))[0]
                old_bits = raw
            else:
                if raw != old:
                    bad.append("idx %d: en %d != expected %d"
                               % (nidx, raw, old))
                    continue
                old_bits, new_bits = raw, new
            s = {"func": fname, "idx": 90000 + n, "addr": addr,
                 "delta": delta, "op": op, "old": old_bits,
                 "new": new_bits, "ctx": build_ctx(en_ins, e),
                 "rank": 0, "n_match": 1, "manual": 1}
            grp_sites.append((e, s))
        # rank = this site's position among all same-signature matches in
        # the en body (identical constants repeat, e.g. PUSH 451)
        for e, s in grp_sites:
            tok_idx = (s["delta"] - 2) // 4
            ci = next((i for i, c in enumerate(s["ctx"])
                       if c[0] == s["addr"]), -1)
            self_toks = (norm_ops_tokens(s["op"], s["ctx"][ci][2])
                         if ci >= 0 else None)
            probe = {"tok_idx": tok_idx, "old": s["old"],
                     "new": s["new"]}
            matches = [j for j in range(len(en_ins))
                       if instr_matches(en_ins[j], s["op"], self_toks,
                                        skip_tok=tok_idx)
                       and ctx_match_at(en_ins, j, s["ctx"], ci,
                                        site=probe)]
            s["rank"] = matches.index(e) if e in matches else -1
            s["n_match"] = len(matches)
        sites.extend(s for _e, s in grp_sites)
        if bad:
            review.append({"func": fname,
                           "reason": "manual: " + "; ".join(bad[:4]),
                           "count": len(bad)})
    return sites, review


def group_key(s):
    """Mirror apply_hd_ain.py's grouping."""
    ci = next((i for i, c in enumerate(s["ctx"]) if c[0] == s["addr"]), -1)
    self_toks = (norm_ops_tokens(s["op"], s["ctx"][ci][2])
                 if ci >= 0 else None)
    return (s["func"], s["op"],
            tuple(tuple(t) if t else None for t in (self_toks or [])),
            s["delta"],
            tuple((c[1], c[2]) for c in s["ctx"]))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("en_ain")
    ap.add_argument("--jp-dump", default="dump/Rance7_raw.jam")
    ap.add_argument("--jp-named", default="dump/Rance7.jam",
                    help="named (-c) jp dump for call-name fallback")
    ap.add_argument("--en-dump", default=None,
                    help="reuse an existing -C dump instead of running "
                         "alice.exe")
    ap.add_argument("--en-named", default=None,
                    help="reuse an existing -c named dump")
    ap.add_argument("--sites", default="tools/hd_sites.json")
    ap.add_argument("--out", default="tools/hd_sites_en.json")
    ap.add_argument("--review", default="work/en_review.json")
    args = ap.parse_args()

    data = open(args.en_ain, "rb").read()
    enc = is_encrypted(data)
    dec = bytes(decrypt(data)) if enc else data
    code_off, _code_size = parse_sections(dec)["CODE"]

    import subprocess
    if args.en_dump:
        en_dump_path = args.en_dump
    else:
        fd, en_dump_path = tempfile.mkstemp(suffix=".jam")
        os.close(fd)
        subprocess.run([ALICE, "ain", "dump", "-C", "-o", en_dump_path,
                        args.en_ain], check=True)
    if args.en_named:
        en_named_path = args.en_named
    else:
        fd, en_named_path = tempfile.mkstemp(suffix=".jam")
        os.close(fd)
        subprocess.run([ALICE, "ain", "dump", "-c", "-o", en_named_path,
                        args.en_ain], check=True)

    jp_funcs = parse_raw_dump(args.jp_dump)
    en_funcs = parse_raw_dump(en_dump_path)
    jp_by_name = func_index(jp_funcs)
    en_by_name = func_index(en_funcs)
    jp_named = (parse_named_dump(args.jp_named)
                if os.path.exists(args.jp_named) else {})
    en_named = parse_named_dump(en_named_path)

    sites = json.load(open(args.sites, encoding="utf-8"))["sites"]
    groups = {}
    for s in sites:
        groups.setdefault(group_key(s), []).append(s)

    en_sites = []
    review = []
    n_exact = n_assumed = 0
    for key, grp in groups.items():
        grp = sorted(grp, key=lambda g: g["idx"])
        fname = key[0]
        if fname not in en_by_name:
            review.append({"func": fname, "reason": "missing_func",
                           "count": len(grp)})
            continue
        jp_f = find_jp_func(jp_by_name, fname, grp[0]["addr"])
        if jp_f is None:
            review.append({"func": fname, "reason": "no jp body",
                           "count": len(grp)})
            continue
        es, reasons = transplant_group(jp_f, en_by_name[fname], grp,
                                       dec, code_off,
                                       jp_named.get(fname),
                                       en_named.get(fname))
        if es is None:
            if fname not in MANUAL_SITES:
                review.append({"func": fname,
                               "reason": "; ".join(reasons[:4]),
                               "count": len(grp),
                               "addrs": ["0x%x" % s["addr"]
                                         for s in grp]})
            continue
        en_sites.extend(es)
        n_exact += sum(1 for s in es if not s.get("assumed"))
        n_assumed += sum(1 for s in es if s.get("assumed"))
        # per-site failures inside an otherwise transplanted group.
        # NOTE: es can exceed len(grp) when a callarg fallback fans out to
        # multiple en positions (patch-all), so count by unemitted jp idx.
        emitted_idx = {s["idx"] for s in es}
        failed = [s for s in grp if s["idx"] not in emitted_idx]
        # jp-side failures for functions covered by MANUAL_SITES are
        # superseded by the hand-ported en-native sites
        if failed and fname not in MANUAL_SITES:
            review.append({"func": fname,
                           "reason": "; ".join(reasons[:4]),
                           "count": len(failed), "partial": 1,
                           "addrs": ["0x%x" % s["addr"] for s in failed]})

    # hand-ported sites for functions the localization rewrote; drop
    # entries whose en position was already covered by an automatic
    # transplant (a duplicate addr would split the applier's signature
    # group into a count_mismatch)
    msites, mreview = emit_manual_sites(en_by_name, en_named, dec, code_off)
    have = {(s["func"], s["addr"]) for s in en_sites}
    msites = [s for s in msites if (s["func"], s["addr"]) not in have]
    en_sites.extend(msites)
    review.extend(mreview)
    n_manual = len(msites)

    # operand-kind guard: a PUSH immediately after PUSHLOCALPAGE /
    # PUSHGLOBALPAGE is a variable *index*, never a pixel constant - an
    # auto-transplanted site there crashes the VM (index OOB on ASSIGN).
    # For PUSHSTRUCTPAGE the PUSH can be a method argument, so only treat
    # it as an index when the next instruction dereferences/assigns.
    en_ins_by_addr = {}
    for f in en_funcs:
        for i, (a, _o, _p) in enumerate(f["instrs"]):
            en_ins_by_addr[a] = (f, i)
    IDX_PREV = {"PUSHLOCALPAGE", "PUSHGLOBALPAGE", "PUSHSTRUCTPAGE",
                "SH_LOCALREF", "SH_GLOBALREF", "SH_STRUCTREF"}
    IDX_DEREF = {"REF", "REFREF", "A_REF", "F_REF", "S_REF", "R_REF",
                 "SR_REF", "DELETE"}
    IDX_PUSHLIKE = {"PUSH", "F_PUSH", "S_PUSH", "SH_LOCALREF",
                    "SH_GLOBALREF", "SH_STRUCTREF", "SH_LOCALREFREF",
                    "SH_GLOBALREFREF", "DUP", "DUP2"}
    IDX_ASSIGN = {"ASSIGN", "F_ASSIGN", "S_ASSIGN", "R_ASSIGN",
                  "SR_ASSIGN", "A_ASSIGN", "REF", "REFREF", "DELETE"}
    filtered = []
    for s in en_sites:
        if s["op"] == "PUSH" and s["addr"] in en_ins_by_addr:
            f, i = en_ins_by_addr[s["addr"]]
            ins = f["instrs"]
            prev_op = ins[i - 1][1] if i > 0 else None
            next_op = ins[i + 1][1] if i + 1 < len(ins) else None
            n2_op = ins[i + 2][1] if i + 2 < len(ins) else None
            # var[idx]=val / var[idx].ref: a PUSH right after a ref-op is
            # a member/array index, not a pixel constant.  A PUSH that is
            # itself followed by the ASSIGN is the *value* (x = v) and is
            # left alone.
            is_index = (prev_op in IDX_PREV and
                        (next_op in IDX_DEREF or
                         (next_op in IDX_PUSHLIKE and
                          n2_op in IDX_ASSIGN)))
            if is_index:
                review.append({"func": s["func"],
                               "reason": "site is a variable index, "
                                         "not a pixel constant",
                               "count": 1,
                               "addrs": ["0x%x" % s["addr"]]})
                continue
        filtered.append(s)
    if len(filtered) != len(en_sites):
        print("note: dropped %d index-operand sites"
              % (len(en_sites) - len(filtered)))
    en_sites = filtered

    # denylist: positions where a transplanted jp constant has a
    # different meaning in the en build (see DROP_SITES)
    drop_addrs = set()
    for fname, idxs in DROP_SITES.items():
        copies = en_by_name.get(fname)
        nps = en_named.get(fname)
        if not copies or not nps:
            continue
        _nops, n2r = pair_named(nps, copies[0])
        if n2r is None:
            continue
        ins = copies[0]["instrs"]
        for nidx in idxs:
            if nidx < len(n2r):
                drop_addrs.add((fname, ins[n2r[nidx]][0]))
    if drop_addrs:
        kept = [s for s in en_sites
                if (s["func"], s["addr"]) not in drop_addrs]
        if len(kept) != len(en_sites):
            print("note: dropped %d denylisted sites"
                  % (len(en_sites) - len(kept)))
        en_sites = kept

    # one operand = one site: collapse any remaining addr duplicates
    deduped, seen = [], set()
    for s in en_sites:
        k = (s["func"], s["addr"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(s)
    if len(deduped) != len(en_sites):
        print("note: dropped %d duplicate-addr sites"
              % (len(en_sites) - len(deduped)))
    en_sites = deduped

    # Final rank pass: sites emitted through the callsig/callarg fallback
    # carry a ctx rebuilt at the en position, so they may regroup under
    # signatures other than their original jp group's.  Recompute rank per
    # emitted group exactly the way the applier will: find every position
    # matching the group's signature, then rank = index of this site.
    from apply_hd_ain import ctx_match_at, instr_matches
    e_groups = {}
    for s in en_sites:
        e_groups.setdefault(group_key(s), []).append(s)
    for key, grp in e_groups.items():
        copies = en_by_name.get(key[0])
        if not copies:
            continue
        b0 = grp[0]
        tok_idx = (b0["delta"] - 2) // 4
        ci = next((i for i, c in enumerate(b0["ctx"])
                   if c[0] == b0["addr"]), -1)
        self_toks = (norm_ops_tokens(b0["op"], b0["ctx"][ci][2])
                     if ci >= 0 else None)
        probe = {"tok_idx": tok_idx, "old": b0["old"], "new": b0["new"]}
        for fcopy in copies:
            ins = fcopy["instrs"]
            addr2pos = {ins[j][0]: j for j in range(len(ins))}
            if grp[0]["addr"] not in addr2pos:
                continue
            matches = [j for j in range(len(ins))
                       if instr_matches(ins[j], b0["op"], self_toks,
                                        skip_tok=tok_idx)
                       and ctx_match_at(ins, j, b0["ctx"], ci,
                                        site=probe)]
            mset = {ins[j][0]: n for n, j in enumerate(matches)}
            for s in grp:
                if s["addr"] in mset:
                    s["rank"] = mset[s["addr"]]
                    s["n_match"] = len(matches)
            break

    json.dump({"code_base": code_off, "count": len(en_sites),
               "sites": en_sites},
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(review, open(args.review, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("en sites written: %d (%d exact, %d assumed-x2, %d manual) -> %s"
          % (len(en_sites), n_exact, n_assumed, n_manual, args.out))
    print("review queue: %d groups (%d sites) -> %s"
          % (len(review), sum(r["count"] for r in review), args.review))


if __name__ == "__main__":
    main()
