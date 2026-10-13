# -*- coding: utf-8 -*-
"""Regenerate hd_sites.json entries for sites that the byte-diff export
missed, by diffing the dev-era symbolized dump against the pristine jp
dump and anchoring results via the raw -C dump.

Usage: python tools/ain_missing_sites.py [--check]
  --check : only report missing sites, do not modify hd_sites.json
"""
import json
import re
import sys

sys.path.insert(0, "tools")
from ain_export_sites import parse_raw_dump, norm_ops, CTX

ORIG_C = "work/jp_orig.jam"          # -c dump of pristine jp ain
DEV_C = "dump/Rance7.jam"            # -c dump of the dev HD build
RAW = "dump/Rance7_raw.jam"          # -C dump of pristine jp ain
SITES_JSON = "tools/hd_sites.json"
SITES_JSON2 = "installer/data/hd_sites.json"

int_re = re.compile(r"-?\d+")


def parse_cdump(path):
    funcs = {}
    cur = None
    addr_re = re.compile(r"0x([0-9a-fA-F]+):")
    name = None
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"; (\S+)", line)
        if m and not line.startswith(("; ARG", "; VAR", "; RETURN")):
            name = m.group(1)
            continue
        if line.startswith("FUNC "):
            cur = {"name": name, "instrs": []}
            funcs.setdefault(name, []).append(cur)
            continue
        if "ENDFUNC" in line:
            cur = None
            continue
        s = line.strip()
        if not s or cur is None:
            continue
        if s.startswith("0x") and s.endswith(":"):
            continue
        a = addr_re.match(s)
        if a:
            s = s[a.end():].strip()
            if not s:
                continue
        parts = s.split(None, 1)
        cur["instrs"].append((parts[0], parts[1] if len(parts) > 1 else ""))
    return funcs


def diff_sites(orig, dev):
    out = []
    for name, of in orig.items():
        df = dev.get(name)
        if not df:
            continue
        for fi, (o, d) in enumerate(zip(of, df)):
            oi, di = o["instrs"], d["instrs"]
            if len(oi) != len(di):
                continue
            for idx, ((oop, oops), (dop, dops)) in enumerate(zip(oi, di)):
                if oop != dop:
                    break
                ov = int_re.findall(oops)
                dv = int_re.findall(dops)
                if ov == dv or len(ov) != len(dv):
                    continue
                for a, b in zip(ov, dv):
                    if a != b:
                        out.append({"func": name, "copy": fi, "idx": idx,
                                    "op": oop, "old": int(a), "new": int(b)})
    return out


def main():
    check_only = "--check" in sys.argv
    orig = parse_cdump(ORIG_C)
    dev = parse_cdump(DEV_C)
    diffs = diff_sites(orig, dev)

    js = json.load(open(SITES_JSON, encoding="utf-8"))
    have_fn = {}
    for s in js["sites"]:
        have_fn.setdefault(s["func"], set()).add((s["old"], s["new"]))
    missing = [s for s in diffs
               if (s["old"], s["new"]) not in have_fn.get(s["func"], set())]

    # Exclude offsets deliberately reverted by ain_zfix.py: those are
    # z-order immediates that must NOT be doubled (z is a sort key;
    # doubling only some of them flips layer ordering).
    from ain_export_sites import parse_sections, decrypt
    zfix_src = open("tools/ain_zfix.py", encoding="utf-8").read()
    zfix_pairs = re.findall(r"\(0x([0-9A-Fa-f]+),\s*(-?\d+)\)", zfix_src)
    dec0 = decrypt("jp/backup/hd_20261013_210614/Rance7.ain")
    code_off0 = parse_sections(dec0)["CODE"][0]
    # map: instr-addr -> (orig value) for zfix entries
    zfix_map = {fo - code_off0 - 2: v for fo, v in
                ((int(a, 16), int(b)) for a, b in zfix_pairs)}
    print("diff sites:", len(diffs), " missing:", len(missing))
    if not missing:
        return

    # instruction indices in the -c dump can shift vs the -C dump for a
    # few functions; pin those by raw code address instead
    addr_overrides = {
        # (func, old) -> (raw addr, new)
        ("tagBushoList@create", 10): (0x1EC2B8, 20),   # nZ+10 -> nZ+20
        ("tagBushoList@create", 31): (0x1EC308, 62),   # nZ+31 -> nZ+62
    }

    # anchor each missing site in the raw dump
    rfuncs, _ = parse_raw_dump(RAW)
    raw_by_name = {}
    instrs_by_addr = {}
    for f in rfuncs:
        if f["lo"] is not None:
            raw_by_name.setdefault(f["name"], []).append(f)
            for i, (a, o, p) in enumerate(f["instrs"]):
                instrs_by_addr[a] = (f, i)

    new_sites = []
    for s in missing:
        ov = addr_overrides.get((s["func"], s["old"]))
        if ov is not None:
            rf, cidx = instrs_by_addr[ov[0]]
            ins = rf["instrs"]
            addr, op, ops = ins[cidx]
        else:
            rfs = raw_by_name.get(s["func"])
            if not rfs or s["copy"] >= len(rfs):
                print("  !! no raw func", s["func"], "copy", s["copy"])
                continue
            rf = rfs[s["copy"]]
            ins = rf["instrs"]
            if s["idx"] >= len(ins):
                print("  !! idx out of range", s["func"], s["idx"])
                continue
            cidx = s["idx"]
            addr, op, ops = ins[cidx]
            if op != s["op"]:
                print("  !! op mismatch", s["func"], s["idx"], op,
                      "!=", s["op"])
                continue
            # raw dump operands are hex; match old value as int
            tokvals = []
            for t in ops.split():
                try:
                    tokvals.append(int(t, 0))
                except ValueError:
                    pass
            if s["old"] not in tokvals:
                print("  !! old not in ops", s["func"], s["idx"], ops)
                continue
        if addr in zfix_map:
            print(f"  - skip (zfix revert): {s['func']} @{hex(addr)} "
                  f"{s['old']}->{s['new']}")
            continue
        ctx = []
        for j in range(max(0, cidx - CTX), min(len(ins), cidx + CTX + 1)):
            a, o2, p2 = ins[j]
            ctx.append([a, o2, norm_ops(o2, p2)])
        newv = ov[1] if ov is not None else s["new"]
        new_sites.append({"func": s["func"], "idx": cidx, "addr": addr,
                          "delta": 2, "op": op, "old": s["old"],
                          "new": newv, "ctx": ctx, "rank": -1})
        print(f"  + {s['func']} @{hex(addr)} {op} {s['old']}->{newv}")

    if check_only:
        return

    js["sites"].extend(new_sites)
    js["sites"].sort(key=lambda s: s["addr"])
    js["count"] = len(js["sites"])
    for p in (SITES_JSON, SITES_JSON2):
        json.dump(js, open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0)
    print("sites total:", js["count"], "-> wrote", SITES_JSON, "and", SITES_JSON2)


if __name__ == "__main__":
    main()
