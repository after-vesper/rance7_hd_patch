# -*- coding: utf-8 -*-
"""Revert wrongly-doubled z-order immediates in Rance7.ain.

The HD patch tables doubled several PUSH immediates that feed layer-order
(z) arguments - tagSprite@setZ / tagDrawText@setZ / *@create(nZ,...) args and
`nZ + k` offsets. z is a sort key, not a coordinate: doubling only some of
them flips ordering vs. unmodified z values (e.g. tagButtonGroup z stays at
202 while a panel z went 201->402, hiding buttons behind the baked panel
image - this made the prisoner screen recruit button look always-normal).

Fix: restore the original immediates in-place (same byte layout, so this
reuses the same MT19937 decrypt/encrypt trick as ain_hd_patch.py).

Usage:
    python tools/ain_zfix.py <encrypted ain> <output ain>
"""

import struct
import sys
from ain_hd_patch import _mt_stream

# (file offset of the int32 immediate, original value)
FIXES = [
    # tagHoryo@create: panel/text z + button group sits at fixed 202
    (0x1B2E04, 201), (0x1B2E54, 202), (0x1B2EE4, 202),
    # tagItemList@create: panel/text/scrollbar/item z
    (0x1BBCB6, 201), (0x1BBD06, 202), (0x1BBDFE, 202),
    (0x1BBE66, 202), (0x1BC09E, 202),
    # tagForce@create: panel z, titlebar z, tagForceScroll z x3
    (0x1BF1D4, 201), (0x1BF1F4, 202),
    (0x1BF212, 202), (0x1BF24E, 202), (0x1BF28A, 202),
    # tagBattleEffect@setPosFromBusho: getZ()+50 offset
    (0x1D2172, 50),
    # tagBattleTime@create / tagBattleMessage / tagBattlePreInfo z+k offsets
    (0x1D72A4, 1), (0x1D90DC, 1), (0x1D929A, 1), (0x1D94D8, 2),
    (0x1DA210, 1), (0x1DA2C2, 1),
    # tagBushoList@create: sprite z offset +31, tagBushoManager z +10,
    # tagButtonGroup create arg0 (nZ+1)
    (0x1EC322, 31), (0x1EC2D2, 10), (0x1EC37C, 1),
    # tagBushoList@createBase / createBase2 / createBright: sprite z
    (0x1ED870, 201), (0x1ED8E6, 203), (0x1ED994, 201),
    (0x1EDBD4, 202), (0x1EDC86, 202),
    # tagBushoInfo@create: z+k offsets on text/sprite/bushoFace
    (0x1EEB10, 1), (0x1EEC16, 2), (0x1EEC56, 3), (0x1EECAC, 2),
    # tagBushoInfo@createUnit: tagItem array index + z
    (0x1EEEC2, 29), (0x1EEEC8, 204),
    # tagBushoInfo@createUnit / tagBushoArrange@create / @arrange
    (0x1F013C, 1), (0x1F1CE6, 1),
    (0x1F1D52, 911), (0x1F1DA8, 912), (0x1F1DD0, 913),
    (0x1F282A, 1),
]


def main(src_path, dst_path):
    enc = open(src_path, "rb").read()
    ks = _mt_stream(0x5D3E3, len(enc))
    dec = bytearray(b ^ k for b, k in zip(enc, ks))

    fixed = 0
    for off, orig in FIXES:
        cur = struct.unpack_from("<i", dec, off)[0]
        if cur == orig:
            continue  # already fixed
        if cur != orig * 2:
            raise SystemExit(
                "unexpected value @0x%x: %d (expected %d or %d)"
                % (off, cur, orig, orig * 2))
        if dec[off - 2:off] != b"\x00\x00":
            raise SystemExit("not a PUSH immediate @0x%x" % off)
        struct.pack_into("<i", dec, off, orig)
        fixed += 1

    out = bytes(b ^ k for b, k in zip(dec, ks))
    open(dst_path, "wb").write(out)
    print("z-order immediates restored: %d/%d -> %s" % (fixed, len(FIXES), dst_path))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
