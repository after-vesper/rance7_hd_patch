# -*- coding: utf-8 -*-
"""Export the net HD patch effect (jp AIN orig -> deployed) as anchored sites.

Instead of hardcoded file offsets, each site is anchored to a function name
plus a local instruction-context signature, so the patch can be re-applied to
other AIN variants (vanilla / NE-patched) whose layouts differ.

Output: tools/hd_sites.json
    {
      "code_base": <file offset of CODE section data in decrypted ain>,
      "sites": [
        {"func": str, "addr": int (code-relative addr of instruction),
         "delta": int (byte offset of operand within instruction),
         "op": str (opcode), "old": int, "new": int,
         "ctx": [[op, operands_text], ...]  # instructions around the site
        }, ...
      ]
    }
"""
import json
import re
import struct
import sys

sys.path.insert(0, "tools")
from ain_hd_patch import _mt_stream

JP_AIN = "jp/Rance7.ain"
DEPLOYED_AIN = "game/Rance7.ain"
RAW_DUMP = "dump/Rance7_raw.jam"  # -C dump of jp/Rance7.ain (must match JP_AIN)
OUT = "tools/hd_sites.json"

# Opcodes whose operand text is volatile across AIN variants
# (indexes into function/string/switch tables or jump addresses).
VOLATILE_OPS = {
    "S_PUSH", "MSG", "CALLFUNC", "CALLSYS", "CALLMETHOD", "CALLHLL",
    "JUMP", "IFZ", "IFNZ", "SWITCH", "EOF", "FUNC", "ENDFUNC",
    "CALLONJUMP", "SJUMP", "CALLFUNCREF", "DELEGATE",
}

CTX = 3  # instructions of context on each side


def decrypt(path):
    d = open(path, "rb").read()
    ks = _mt_stream(0x5D3E3, len(d))
    return bytes(b ^ k for b, k in zip(d, ks))


def parse_sections(dec):
    """Return {tag: (data_off, size)} for the decrypted AIN section table."""
    secs = {}
    pos = 0
    while pos + 8 <= len(dec):
        tag = dec[pos:pos + 4]
        size = struct.unpack_from("<I", dec, pos + 4)[0]
        if not all(32 <= b < 127 for b in tag):
            break
        secs[tag.decode("ascii")] = (pos + 8, size)
        pos += 8 + size
        if pos % 4:
            pos += 4 - pos % 4  # sections are 4-byte aligned
    return secs


def parse_raw_dump(path):
    """Parse alice -C dump.

    Returns (funcs, instrs):
      funcs: list of dicts {name, lo, hi, instrs:[(addr,op,ops)], func_no}
      instrs: dict addr -> (op, ops_text)
    """
    funcs = []
    instrs = {}
    name = None
    cur = None
    addr_re = re.compile(r"0x([0-9a-fA-F]+):")
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"; (\S+)", line)
        if m:
            if not any(line.startswith(p) for p in ("; ARG", "; VAR", "; RETURN")):
                if cur is not None:
                    funcs.append(cur)
                    cur = None
                name = m.group(1)
            continue
        if line.startswith("FUNC "):
            cur = {"name": name, "no": int(line.split()[1]), "lo": None,
                   "hi": None, "instrs": []}
            continue
        a = addr_re.match(line)
        if not a:
            continue
        addr = int(a.group(1), 16)
        body = line[a.end():].strip()
        if "ENDFUNC" in body:
            if cur is not None:
                cur["hi"] = addr
                funcs.append(cur)
                cur = None
            continue
        if not body:
            # blank separator line; ends an unfinished function block
            if cur is not None:
                funcs.append(cur)
                cur = None
            continue
        parts = body.split(None, 1)
        op = parts[0]
        ops = parts[1] if len(parts) > 1 else ""
        instrs[addr] = (op, ops)
        if cur is not None:
            if cur["lo"] is None:
                cur["lo"] = addr
            cur["hi"] = addr
            cur["instrs"].append((addr, op, ops))
    if cur is not None:
        funcs.append(cur)
    return funcs, instrs


def norm_ops(op, ops):
    """Mask operand text that is not stable across AIN variants."""
    if op in VOLATILE_OPS:
        return "*"
    return ops


def main():
    orig = decrypt(JP_AIN)
    dep = decrypt(DEPLOYED_AIN)
    assert len(orig) == len(dep)

    code_off, code_size = parse_sections(orig)["CODE"]

    funcs, instrs = parse_raw_dump(RAW_DUMP)
    funcs = [f for f in funcs if f["lo"] is not None]
    funcs.sort(key=lambda f: f["lo"])
    sorted_addrs = sorted(instrs)

    import bisect

    def instr_at(code_addr):
        """Instruction containing byte code_addr (operand or opcode)."""
        i = bisect.bisect_right(sorted_addrs, code_addr) - 1
        if i < 0:
            return None
        a = sorted_addrs[i]
        return a

    def func_of(code_addr):
        """Owning function: last FUNC block whose lo <= addr and hi >= addr,
        or whose extent reaches into a trailing dead-code gap."""
        i = bisect.bisect_right([f["lo"] for f in funcs], code_addr) - 1
        if i < 0:
            return None
        return funcs[i]

    # net byte differences
    diffs = [i for i in range(len(orig)) if orig[i] != dep[i]]
    sites = []
    errors = []
    for d in diffs:
        if not (code_off <= d < code_off + code_size):
            errors.append(("outside CODE", d))
            continue
        ca = d - code_off
        ia = instr_at(ca)
        if ia is None:
            errors.append(("no instr", d))
            continue
        op, ops = instrs[ia]
        delta = ca - ia
        if delta < 2 or (ia + delta) % 1:  # operand region starts at +2
            pass
        # operand field is a 4-byte int32 slot containing d
        field = ia + 2 + ((d - code_off - (ia + 2)) // 4) * 4
        # recompute in code space
        field_ca = ia + 2 + ((ca - (ia + 2)) // 4) * 4
        file_off = code_off + field_ca
        ov = struct.unpack_from("<i", orig, file_off)[0]
        nv = struct.unpack_from("<i", dep, file_off)[0]
        if ov == nv:
            continue  # diff byte belonged to an adjacent field boundary
        fn = func_of(ia)
        sites.append({
            "func": fn["name"] if fn else None,
            "addr": ia, "delta": field_ca - ia, "op": op,
            "old": ov, "new": nv,
        })
    # dedupe (multiple diff bytes in one field produce the same site)
    uniq = {}
    for s in sites:
        k = (s["addr"], s["delta"])
        if k in uniq and uniq[k]["new"] != s["new"]:
            errors.append(("conflict", hex(s["addr"])))
        uniq[k] = s
    sites = list(uniq.values())

    # attach context and instruction index
    out_sites = []
    for s in sites:
        fn = func_of(s["addr"])
        if fn is None:
            errors.append(("no func", hex(s["addr"])))
            continue
        ins = fn["instrs"]
        idx = next((i for i, (a, _, _) in enumerate(ins) if a == s["addr"]), None)
        if idx is None:
            # site inside trailing dead code: find insertion point
            idx = bisect.bisect_left([a for a, _, _ in ins], s["addr"])
        ctx = []
        for j in range(max(0, idx - CTX), min(len(ins), idx + CTX + 1)):
            a, op, ops = ins[j]
            ctx.append([a, op, norm_ops(op, ops)])
        out_sites.append({
            "func": fn["name"], "idx": idx, "addr": s["addr"],
            "delta": s["delta"], "op": s["op"], "old": s["old"],
            "new": s["new"], "ctx": ctx,
        })

    # Disambiguation rank: for signature-identical sites inside one function,
    # record the site's rank among ALL positions matching its signature, so a
    # target function with extra matches can still be resolved.
    def sig_of(s):
        toks = norm_ops(s["op"], s["ctx"][
            next((i for i, c in enumerate(s["ctx"]) if c[0] == s["addr"]), 0)][2]
            ) if s["ctx"] else ""
        ci = next((i for i, c in enumerate(s["ctx"]) if c[0] == s["addr"]), 0)
        return (s["op"], s["delta"], toks,
                tuple((c[1], c[2]) for c in s["ctx"]), ci)

    def match_positions(fn, s):
        """Positions in fn matching s's context signature."""
        ins = fn["instrs"]
        key = sig_of(s)
        ci = key[4]
        res = []
        for j in range(len(ins)):
            ok = True
            for k, (a, op, ops) in enumerate(s["ctx"]):
                jj = j + k - ci
                if jj < 0 or jj >= len(ins):
                    ok = False
                    break
                _, op2, ops2 = ins[jj]
                if op2 != op or norm_ops(op, ops) != norm_ops(op2, ops2):
                    ok = False
                    break
            if ok:
                res.append(j)
        return res

    by_func = {}
    for s in out_sites:
        by_func.setdefault(s["func"], []).append(s)
    fn_map = {}
    for f in funcs:
        fn_map.setdefault(f["name"], f)
    for fname, ss in by_func.items():
        groups = {}
        for s in ss:
            groups.setdefault(sig_of(s), []).append(s)
        for sig, g in groups.items():
            f0 = fn_map.get(fname)
            if f0 is None:
                continue
            matches = match_positions(f0, g[0])
            for s in g:
                # rank of this site's own instruction among matches
                pos = next((i for i, j in enumerate(matches)
                            if f0["instrs"][j][0] == s["addr"]), None)
                s["rank"] = pos
                s["n_match"] = len(matches)

    json.dump({"code_base": code_off, "count": len(out_sites),
               "sites": out_sites},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("sites:", len(out_sites), "errors:", len(errors))
    for e in errors[:20]:
        print("  ", e)


if __name__ == "__main__":
    main()
