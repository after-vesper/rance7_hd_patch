// HdPatch.cs - HD patch engine for the Sengoku Rance HD asset patch installer.
//
// Ported from tools/apply_hd_ain.py (anchor-based AIN immediate patching)
// and tools/ald.py (ALD archive repack). Compiled at runtime via
// Add-Type so the installer needs nothing but stock Windows PowerShell
// and the bundled alice.exe.
//
// The MT19937 keystream uses the Sengoku Rance custom seeding
// (multiplier 69069, seed 0x5D3E3) - NOT the standard MT initializer.
//
// Requires: Add-Type -ReferencedAssemblies System.Web.Extensions

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Web.Script.Serialization;

public static class HdPatch
{
    // ---------- MT19937 keystream (Rance7 variant) ----------

    public static byte[] MtStream(int n)
    {
        const int N = 624, M = 397;
        uint[] st = new uint[N];
        st[0] = 0x5D3E3;
        for (int i = 1; i < N; i++)
            st[i] = (uint)((69069u * st[i - 1]) & 0xFFFFFFFF);
        int idx = N;
        byte[] outp = new byte[n];
        int filled = 0;
        while (filled < n)
        {
            if (idx >= N)
            {
                for (int kk = 0; kk < N - M; kk++)
                {
                    uint y = (st[kk] & 0x80000000) | (st[kk + 1] & 0x7FFFFFFF);
                    st[kk] = st[kk + M] ^ (y >> 1) ^ ((y & 1) != 0 ? 0x9908B0DFu : 0u);
                }
                for (int kk = N - M; kk < N - 1; kk++)
                {
                    uint y = (st[kk] & 0x80000000) | (st[kk + 1] & 0x7FFFFFFF);
                    st[kk] = st[kk + (M - N)] ^ (y >> 1) ^ ((y & 1) != 0 ? 0x9908B0DFu : 0u);
                }
                {
                    uint y = (st[N - 1] & 0x80000000) | (st[0] & 0x7FFFFFFF);
                    st[N - 1] = st[M - 1] ^ (y >> 1) ^ ((y & 1) != 0 ? 0x9908B0DFu : 0u);
                }
                idx = 0;
            }
            uint v = st[idx++];
            v ^= v >> 11;
            v ^= (v << 7) & 0x9D2C5680;
            v ^= (v << 15) & 0xEFC60000;
            v ^= v >> 18;
            outp[filled++] = (byte)(v & 0xFF);
        }
        return outp;
    }

    public static byte[] AinXor(byte[] data)
    {
        byte[] ks = MtStream(data.Length);
        byte[] outp = new byte[data.Length];
        for (int i = 0; i < data.Length; i++)
            outp[i] = (byte)(data[i] ^ ks[i]);
        return outp;
    }

    // ---------- AIN section table ----------

    public static Dictionary<string, long[]> ParseSections(byte[] dec)
    {
        var secs = new Dictionary<string, long[]>();
        long pos = 0;
        while (pos + 8 <= dec.Length)
        {
            string tag = Encoding.ASCII.GetString(dec, (int)pos, 4);
            if (!tag.All(c => c >= 32 && c < 127)) break;
            uint size = BitConverter.ToUInt32(dec, (int)pos + 4);
            secs[tag] = new long[] { pos + 8, size };
            pos += 8 + size;
            if (pos % 4 != 0) pos += 4 - pos % 4;
        }
        return secs;
    }

    // ---------- JAM raw dump parsing (mirror of parse_raw_dump) ----------

    private static readonly HashSet<string> VolatileOps = new HashSet<string>
    {
        "S_PUSH", "MSG", "CALLFUNC", "CALLSYS", "CALLMETHOD", "CALLHLL",
        "JUMP", "IFZ", "IFNZ", "SWITCH", "EOF", "FUNC", "ENDFUNC",
        "CALLONJUMP", "SJUMP", "CALLFUNCREF", "DELEGATE",
    };

    public class Instr { public long Addr; public string Op; public string Ops; }
    public class Func { public string Name; public int No; public List<Instr> Ins = new List<Instr>(); }

    public static List<Func> ParseRawDump(string path)
    {
        var funcs = new List<Func>();
        string name = null;
        Func cur = null;
        var addrRe = new System.Text.RegularExpressions.Regex(@"^0x([0-9a-fA-F]+):");
        var headRe = new System.Text.RegularExpressions.Regex(@"^; (\S+)");
        foreach (var line in File.ReadLines(path, Encoding.UTF8))
        {
            var m = headRe.Match(line);
            if (m.Success)
            {
                if (!line.StartsWith("; ARG") && !line.StartsWith("; VAR") &&
                    !line.StartsWith("; RETURN"))
                {
                    if (cur != null) { funcs.Add(cur); cur = null; }
                    name = m.Groups[1].Value;
                }
                continue;
            }
            if (line.StartsWith("FUNC "))
            {
                cur = new Func { Name = name, No = int.Parse(line.Split(' ')[1]) };
                continue;
            }
            var a = addrRe.Match(line);
            if (!a.Success) continue;
            long addr = Convert.ToInt64(a.Groups[1].Value, 16);
            string body = line.Substring(a.Length).Trim();
            if (body.Contains("ENDFUNC"))
            {
                if (cur != null) { funcs.Add(cur); cur = null; }
                continue;
            }
            if (body.Length == 0)
            {
                if (cur != null) { funcs.Add(cur); cur = null; }
                continue;
            }
            int sp = body.IndexOfAny(new[] { ' ', '\t' });
            string op = sp < 0 ? body : body.Substring(0, sp);
            string ops = sp < 0 ? "" : body.Substring(sp + 1).Trim();
            if (cur != null)
                cur.Ins.Add(new Instr { Addr = addr, Op = op, Ops = ops });
        }
        if (cur != null) funcs.Add(cur);
        return funcs;
    }

    // ---------- operand normalization (mirror of norm_tok / norm_ops_tokens) ----------

    // A token is either ("num", value) or ("str", raw).
    private class Tok
    {
        public bool IsNum; public long Num; public string Str;
        public override bool Equals(object o)
        {
            var t = o as Tok;
            if (t == null) return false;
            return IsNum == t.IsNum && Num == t.Num && Str == t.Str;
        }
        public override int GetHashCode()
        { return IsNum.GetHashCode() ^ Num.GetHashCode() ^ (Str ?? "").GetHashCode(); }
    }

    private static Tok NormTok(string tok)
    {
        tok = tok.Trim();
        try
        {
            if (tok.StartsWith("0x") || tok.StartsWith("0X"))
                return new Tok { IsNum = true, Num = Convert.ToInt64(tok.Substring(2), 16) };
            if (tok.StartsWith("-0x") || tok.StartsWith("-0X"))
                return new Tok { IsNum = true, Num = -Convert.ToInt64(tok.Substring(3), 16) };
            return new Tok { IsNum = true, Num = long.Parse(tok) };
        }
        catch
        {
            return new Tok { IsNum = false, Str = tok };
        }
    }

    private static List<Tok> NormOpsTokens(string op, string ops)
    {
        if (VolatileOps.Contains(op)) return null;
        var outp = new List<Tok>();
        if (ops.Length > 0)
            foreach (var t in ops.Split(new[] { ' ', '\t' },
                     StringSplitOptions.RemoveEmptyEntries))
                outp.Add(NormTok(t));
        return outp;
    }

    // ---------- sites model (from JavaScriptSerializer dictionaries) ----------

    private class Site
    {
        public long Addr;
        public System.Collections.ArrayList Ctx; // items: ArrayList{addr, op, ops}
        public int Delta;
        public string Func;
        public int Idx;
        public int New, Old;
        public string Op;
        public int Rank;          // -1 when absent
        public int CtxIdx;        // index of self inside Ctx
        public List<Tok> SelfToks;
    }

    private static long CtxAddr(System.Collections.ArrayList c) { return Convert.ToInt64(c[0]); }
    private static string CtxOp(System.Collections.ArrayList c) { return (string)c[1]; }
    private static string CtxOps(System.Collections.ArrayList c) { return c.Count > 2 ? (string)c[2] : ""; }

    public class PatchResult
    {
        public int Ok, MissingFunc, Ambiguous, Relaxed, AlreadyPatched;
        public List<string> Problems = new List<string>();
        public int Writes;
    }

    private static bool InstrMatches(Instr ins, string op, List<Tok> wantToks, int skipTok)
    {
        if (ins.Op != op) return false;
        if (wantToks == null) return true;
        var got = NormOpsTokens(ins.Op, ins.Ops);
        if (got == null || got.Count != wantToks.Count) return false;
        for (int i = 0; i < got.Count; i++)
        {
            if (i == skipTok) continue;
            if (wantToks[i] == null) continue;
            if (!got[i].Equals(wantToks[i])) return false;
        }
        return true;
    }

    private static bool CtxMatchAt(List<Instr> ins, int j, System.Collections.ArrayList ctx, int ci)
    {
        for (int k = 0; k < ctx.Count; k++)
        {
            int jj = j + k - ci;
            if (jj < 0 || jj >= ins.Count) return false;
            var ce = (System.Collections.ArrayList)ctx[k];
            string op = CtxOp(ce);
            if (ins[jj].Op != op) return false;
            var wt = NormOpsTokens(op, CtxOps(ce));
            if (wt == null) continue;
            var gt = NormOpsTokens(ins[jj].Op, ins[jj].Ops);
            if (gt == null || gt.Count != wt.Count) return false;
            for (int i = 0; i < gt.Count; i++)
                if (!gt[i].Equals(wt[i])) return false;
        }
        return true;
    }

    private static string GroupKey(Site s)
    {
        var sb = new StringBuilder();
        sb.Append(s.Func).Append('\x01').Append(s.Op).Append('\x01').Append(s.Delta);
        if (s.SelfToks == null) sb.Append("|*");
        else
            foreach (var t in s.SelfToks)
                sb.Append(t == null ? "|~" : "|" + (t.IsNum ? "n" : "s") + ":" +
                          (t.IsNum ? t.Num.ToString() : t.Str));
        foreach (var c in s.Ctx)
            sb.Append('\x02').Append(CtxOp((System.Collections.ArrayList)c))
              .Append('\x03').Append(CtxOps((System.Collections.ArrayList)c));
        return sb.ToString();
    }

    /// <summary>
    /// Apply the anchor-based HD patch to an AIN file.
    /// srcPath -> dstPath. sitesJsonPath = hd_sites.json.
    /// aliceExe = bundled alice-tools used to produce the raw -C dump.
    /// </summary>
    public static PatchResult ApplyAinPatch(string srcPath, string dstPath,
        string sitesJsonPath, string aliceExe, Action<string> log)
    {
        var res = new PatchResult();
        byte[] data = File.ReadAllBytes(srcPath);
        bool enc = !(data[0] == 'V' && data[1] == 'E' && data[2] == 'R' && data[3] == 'S');
        byte[] dec = enc ? AinXor(data) : data;
        var secs = ParseSections(dec);
        if (!secs.ContainsKey("CODE"))
            throw new Exception("CODE section not found - not an AIN file");
        long codeOff = secs["CODE"][0];

        string dumpPath = Path.Combine(Path.GetTempPath(),
            "hd_dump_" + Guid.NewGuid().ToString("N") + ".jam");
        try
        {
            var psi = new ProcessStartInfo(aliceExe,
                "ain dump -C -o \"" + dumpPath + "\" \"" + srcPath + "\"")
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardError = true, RedirectStandardOutput = true
            };
            var p = Process.Start(psi);
            // drain async to avoid pipe deadlock on large dumps
            var so = new StringBuilder(); var se = new StringBuilder();
            p.OutputDataReceived += (s, e) => { if (e.Data != null) so.AppendLine(e.Data); };
            p.ErrorDataReceived += (s, e) => { if (e.Data != null) se.AppendLine(e.Data); };
            p.BeginOutputReadLine(); p.BeginErrorReadLine();
            p.WaitForExit();
            if (p.ExitCode != 0)
                throw new Exception("alice.exe ain dump failed: " + se);
            var funcs = ParseRawDump(dumpPath);
            if (funcs.Count < 100)
                throw new Exception("dump parse yielded only " + funcs.Count +
                    " functions - refusing to patch");
            var byName = new Dictionary<string, List<Func>>();
            foreach (var f in funcs)
            {
                List<Func> l;
                if (!byName.TryGetValue(f.Name, out l))
                    byName[f.Name] = l = new List<Func>();
                l.Add(f);
            }

            var ser = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
            var root = ser.Deserialize<Dictionary<string, object>>(
                File.ReadAllText(sitesJsonPath, Encoding.UTF8));
            var rawSites = (System.Collections.ArrayList)root["sites"];

            var sites = new List<Site>(rawSites.Count);
            foreach (var o in rawSites)
            {
                var d = (Dictionary<string, object>)o;
                var s = new Site
                {
                    Addr = Convert.ToInt64(d["addr"]),
                    Delta = Convert.ToInt32(d["delta"]),
                    Func = (string)d["func"],
                    Idx = Convert.ToInt32(d["idx"]),
                    New = Convert.ToInt32(d["new"]),
                    Old = Convert.ToInt32(d["old"]),
                    Op = (string)d["op"],
                    Rank = d.ContainsKey("rank") ? Convert.ToInt32(d["rank"]) : -1,
                    Ctx = (System.Collections.ArrayList)d["ctx"],
                    CtxIdx = -1,
                };
                for (int i = 0; i < s.Ctx.Count; i++)
                    if (CtxAddr((System.Collections.ArrayList)s.Ctx[i]) == s.Addr) { s.CtxIdx = i; break; }
                s.SelfToks = s.CtxIdx >= 0
                    ? NormOpsTokens(s.Op, CtxOps((System.Collections.ArrayList)s.Ctx[s.CtxIdx])) : null;
                sites.Add(s);
            }

            var groups = new Dictionary<string, List<Site>>();
            foreach (var s in sites)
            {
                string key = GroupKey(s);
                List<Site> l;
                if (!groups.TryGetValue(key, out l)) groups[key] = l = new List<Site>();
                l.Add(s);
            }

            var writes = new List<long[]>(4096); // fileOff, newValue
            foreach (var grp in groups.Values)
            {
                grp.Sort((a, b) => a.Idx.CompareTo(b.Idx));
                var b0 = grp[0];
                string fname = b0.Func;
                if (!byName.ContainsKey(fname))
                {
                    res.MissingFunc += grp.Count;
                    res.Problems.Add("missing_func " + fname + " x" + grp.Count);
                    continue;
                }
                int tokIdx = (b0.Delta - 2) / 4;
                foreach (var fcopy in byName[fname])
                {
                    var ins = fcopy.Ins;
                    var matches = new List<int>();
                    for (int j = 0; j < ins.Count; j++)
                    {
                        if (!InstrMatches(ins[j], b0.Op, b0.SelfToks, tokIdx))
                            continue;
                        if (!CtxMatchAt(ins, j, b0.Ctx, b0.CtxIdx)) continue;
                        matches.Add(j);
                    }
                    if (matches.Count == grp.Count)
                    {
                        for (int i = 0; i < grp.Count; i++)
                        {
                            long fileOff = codeOff + ins[matches[i]].Addr + grp[i].Delta;
                            int cur = BitConverter.ToInt32(dec, (int)fileOff);
                            if (cur == grp[i].New) { res.AlreadyPatched++; continue; }
                            if (cur != grp[i].Old)
                            {
                                res.Ambiguous++;
                                res.Problems.Add("value_mismatch " + fname +
                                    " @0x" + ins[matches[i]].Addr.ToString("x") +
                                    " want " + grp[i].Old + " got " + cur);
                                continue;
                            }
                            writes.Add(new long[] { fileOff, grp[i].New });
                            res.Ok++;
                        }
                    }
                    else if (matches.Count == 0)
                    {
                        // Relaxed fallback: the function body was rewritten by
                        // another mod - patch every i32 operand equal to old.
                        int relaxed = 0;
                        foreach (var b in grp)
                        {
                            for (int j2 = 0; j2 < ins.Count; j2++)
                            {
                                long a2 = ins[j2].Addr;
                                long lim = j2 + 1 < ins.Count
                                    ? ins[j2 + 1].Addr : a2 + 64;
                                for (long pos = a2 + 2; pos < lim; pos += 4)
                                {
                                    long fileOff = codeOff + pos;
                                    if (BitConverter.ToInt32(dec, (int)fileOff) == b.Old)
                                    {
                                        writes.Add(new long[] { fileOff, b.New });
                                        relaxed++;
                                    }
                                }
                            }
                        }
                        res.Relaxed += relaxed;
                        res.Problems.Add("relaxed " + fname + " x" + relaxed);
                    }
                    else if (matches.Count > grp.Count &&
                             grp.All(b => b.Rank >= 0 && b.Rank < matches.Count))
                    {
                        foreach (var b in grp)
                        {
                            int j = matches[b.Rank];
                            long fileOff = codeOff + ins[j].Addr + b.Delta;
                            int cur = BitConverter.ToInt32(dec, (int)fileOff);
                            if (cur == b.Old)
                            {
                                writes.Add(new long[] { fileOff, b.New });
                                res.Ok++;
                            }
                            else if (cur != b.New)
                            {
                                res.Ambiguous++;
                                res.Problems.Add("value_mismatch " + fname +
                                    " @0x" + ins[j].Addr.ToString("x"));
                            }
                        }
                    }
                    else
                    {
                        res.Ambiguous += grp.Count;
                        res.Problems.Add("count_mismatch " + fname +
                            " want " + grp.Count + " got " + matches.Count);
                    }
                }
            }

            var seen = new Dictionary<long, long>();
            foreach (var w in writes)
            {
                long v;
                if (seen.TryGetValue(w[0], out v) && v != w[1])
                    throw new Exception("conflicting write @0x" + w[0].ToString("x"));
                seen[w[0]] = w[1];
                Array.Copy(BitConverter.GetBytes((int)w[1]), 0, dec, w[0], 4);
            }
            res.Writes = writes.Count;
            File.WriteAllBytes(dstPath, enc ? AinXor(dec) : dec);
            return res;
        }
        finally
        {
            try { File.Delete(dumpPath); } catch { }
        }
    }

    // ---------- ALD archive repack ----------

    private static int U24(byte[] d, long pos)
    {
        return d[pos] | (d[pos + 1] << 8) | (d[pos + 2] << 16);
    }

    private static void W24(Stream s, int v)
    {
        s.WriteByte((byte)v);
        s.WriteByte((byte)(v >> 8));
        s.WriteByte((byte)(v >> 16));
    }

    private static long Align256(long v) { return (v + 255) & ~255L; }

    private class AldEntry
    {
        public long Pos; public int Hsize, Dsize;
        public string Name; public byte[] Extra;
    }

    private static List<AldEntry> AldEntries(byte[] ptable, FileStream fs)
    {
        int ptrSecs = U24(ptable, 0);
        int n = (ptrSecs * 256) / 3;
        var outp = new List<AldEntry>(n);
        var ehead = new byte[16];
        for (int i = 1; i < n; i++)
        {
            int sec = U24(ptable, i * 3);
            if (sec == 0) break;           // padding: end of pointer table
            long pos = (long)sec << 8;
            fs.Seek(pos, SeekOrigin.Begin);
            fs.Read(ehead, 0, 16);
            int hs = BitConverter.ToInt32(ehead, 0);
            int ds = BitConverter.ToInt32(ehead, 4);
            // the last pointer is the terminator (points at the NL footer)
            if (hs < 16 || hs > 1024 || pos + hs + ds > fs.Length)
                continue;
            var nb = new byte[hs - 16];
            fs.Seek(pos + 16, SeekOrigin.Begin);
            fs.Read(nb, 0, hs - 16);
            string name = Encoding.GetEncoding(932).GetString(nb).TrimEnd('\0');
            if (name.Length == 0) continue;   // terminator pseudo-entry
            var extra = new byte[8];
            Array.Copy(ehead, 8, extra, 0, 8);
            outp.Add(new AldEntry
            { Pos = pos, Hsize = hs, Dsize = ds, Name = name, Extra = extra });
        }
        return outp;
    }

    public static int AldFileNumber(string name)
    {
        var m = System.Text.RegularExpressions.Regex.Match(
            Path.GetFileNameWithoutExtension(name), @"\d+");
        return m.Success ? int.Parse(m.Value) : -1;
    }

    /// <summary>List entry names of an .ald in pointer-table order.</summary>
    public static List<string> ListAldNames(string path)
    {
        using (var fs = new FileStream(path, FileMode.Open,
                   FileAccess.Read, FileShare.Read))
        {
            var head = new byte[256];
            fs.Read(head, 0, 256);
            int ptrSecs = U24(head, 0);
            var ptable = new byte[ptrSecs * 256];
            fs.Seek(0, SeekOrigin.Begin);
            fs.Read(ptable, 0, ptable.Length);
            return AldEntries(ptable, fs).Select(e => e.Name).ToList();
        }
    }

    /// <summary>
    /// Rebuild an .ald at dstPath from the original archive, applying
    /// payload overrides/additions from payloadDirs (searched in order;
    /// later dirs win on name collision). Original entry order is
    /// preserved; added entries are appended in name order.
    /// extraLinkRows: additional link-table overrides
    /// (fileNumber -> {disk, filesIndex}) applied after own entries.
    /// Returns { fileCount, overridden, added }.
    /// </summary>
    public static int[] RepackAld(string srcPath, string dstPath,
        string[] payloadDirs, int disk, Action<string> log,
        Dictionary<int, int[]> extraLinkRows)
    {
        using (var fs = new FileStream(srcPath, FileMode.Open,
                   FileAccess.Read, FileShare.Read))
        {
            var head = new byte[256];
            fs.Read(head, 0, 256);
            int ptrSecs = U24(head, 0);
            var ptable = new byte[ptrSecs * 256];
            fs.Seek(0, SeekOrigin.Begin);
            if (fs.Read(ptable, 0, ptable.Length) != ptable.Length)
                throw new Exception("short read on pointer table");

            var entries = AldEntries(ptable, fs);
            if (entries.Count == 0)
                throw new Exception(srcPath + ": not an ALD archive?");
            long firstData = (long)U24(ptable, 3) << 8;
            long mapPos = (long)ptrSecs << 8;
            var lt = new byte[firstData - mapPos];
            fs.Seek(mapPos, SeekOrigin.Begin);
            if (fs.Read(lt, 0, lt.Length) != lt.Length)
                throw new Exception("short read on link table");

            var payloads = new Dictionary<string, string>();
            if (payloadDirs != null)
                foreach (var dir in payloadDirs)
                    if (dir != null && Directory.Exists(dir))
                        foreach (var f in Directory.GetFiles(dir))
                            payloads[Path.GetFileName(f)] = f;
            var present = new HashSet<string>(entries.Select(e => e.Name));
            var added = payloads.Keys.Where(n => !present.Contains(n))
                .OrderBy(n => n, StringComparer.Ordinal).ToList();
            int overridden = payloads.Count - added.Count;

            // original order preserved (other archives' link tables hold
            // pointer indices into this archive); additions appended.
            var files = new List<KeyValuePair<string, AldEntry>>();
            foreach (var e in entries)
                files.Add(new KeyValuePair<string, AldEntry>(e.Name, e));
            foreach (var n in added)
                files.Add(new KeyValuePair<string, AldEntry>(n, null));

            int count = files.Count;
            int newPtrSecs = ((count + 2) * 3 + 255) / 256;
            int ltEntries = lt.Length / 3;
            int newMapSecs = (ltEntries * 3 + 255) / 256;
            long dataStartSec = newPtrSecs + newMapSecs;

            using (var w = new FileStream(dstPath, FileMode.Create,
                       FileAccess.Write, FileShare.None))
            {
                long pos = dataStartSec << 8;
                var offsets = new List<int>(count + 1);
                var enc932 = Encoding.GetEncoding(932);
                var copyBuf = new byte[1 << 20];
                var padBuf = new byte[256];

                w.Position = pos;
                for (int i = 0; i < count; i++)
                {
                    var name = files[i].Key;
                    var e = files[i].Value;
                    offsets.Add((int)(pos >> 8));
                    byte[] nb = enc932.GetBytes(name);
                    int hs = 0x10 + Math.Max(16, (nb.Length + 16) & ~15);
                    string pf;
                    long dsize = payloads.TryGetValue(name, out pf)
                        ? new FileInfo(pf).Length : e.Dsize;
                    w.Write(BitConverter.GetBytes(hs), 0, 4);
                    w.Write(BitConverter.GetBytes((int)dsize), 0, 4);
                    w.Write(e != null ? e.Extra : new byte[8], 0, 8);
                    var nameField = new byte[hs - 0x10];
                    Array.Copy(nb, nameField, nb.Length);
                    w.Write(nameField, 0, nameField.Length);
                    if (pf != null)
                    {
                        using (var pfs = File.OpenRead(pf))
                            pfs.CopyTo(w);
                    }
                    else
                    {
                        fs.Seek(e.Pos + e.Hsize, SeekOrigin.Begin);
                        long left = e.Dsize;
                        while (left > 0)
                        {
                            int n = fs.Read(copyBuf, 0,
                                (int)Math.Min(left, copyBuf.Length));
                            w.Write(copyBuf, 0, n);
                            left -= n;
                        }
                    }
                    long pad = Align256(pos + hs + dsize) - pos - hs - dsize;
                    while (pad > 0)
                    {
                        int n = (int)Math.Min(pad, padBuf.Length);
                        w.Write(padBuf, 0, n);
                        pad -= n;
                    }
                    pos = Align256(pos + hs + dsize);
                }
                offsets.Add((int)(pos >> 8));

                // pointer table
                w.Position = 0;
                W24(w, newPtrSecs);
                foreach (var o in offsets) W24(w, o);
                long ptEnd = (long)newPtrSecs << 8;
                while (w.Position < ptEnd) w.WriteByte(0);

                // link table: original contents, then re-point only the
                // rows of entries whose payload came from payloadDirs.
                // Untouched entries keep their rows verbatim so that a
                // re-run on an already-patched archive cannot clobber
                // redirects installed by extraLinkRows.
                // Row index = numeric name minus 1 (cg00001 -> row 0);
                // stored pointer = files index + 1.
                w.Position = (long)newPtrSecs << 8;
                w.Write(lt, 0, lt.Length);
                long ltEnd = ((long)newPtrSecs + newMapSecs) << 8;
                while (w.Position < ltEnd) w.WriteByte(0);
                for (int i = 0; i < count; i++)
                {
                    if (!payloads.ContainsKey(files[i].Key)) continue;
                    int no = AldFileNumber(files[i].Key) - 1;
                    if (no < 0 || no >= ltEntries) continue;
                    w.Position = ((long)newPtrSecs << 8) + no * 3;
                    w.WriteByte((byte)(disk + 1));
                    w.WriteByte((byte)((i + 1) & 0xFF));
                    w.WriteByte((byte)(((i + 1) >> 8) & 0xFF));
                }
                if (extraLinkRows != null)
                    foreach (var kv in extraLinkRows)
                    {
                        if (kv.Key < 0 || kv.Key >= ltEntries) continue;
                        w.Position = ((long)newPtrSecs << 8) + kv.Key * 3;
                        w.WriteByte((byte)(kv.Value[0] + 1));
                        w.WriteByte((byte)((kv.Value[1] + 1) & 0xFF));
                        w.WriteByte((byte)(((kv.Value[1] + 1) >> 8) & 0xFF));
                    }

                // footer
                w.Position = pos;
                w.Write(new byte[] { (byte)'N', (byte)'L', 1, 0 }, 0, 4);
                w.Write(BitConverter.GetBytes(0x10), 0, 4);
                w.WriteByte((byte)(disk + 1));
                w.Write(BitConverter.GetBytes((ushort)count), 0, 2);
                w.Write(new byte[5], 0, 5);
            }
            return new[] { count, overridden, added.Count };
        }
    }
}
