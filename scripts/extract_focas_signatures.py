"""Extract verbatim FOCAS function signatures + referenced struct definitions
from FANUC `Fwlib64.h` for Decision-2 / `tasks/spec-focas-calls.md`.

Usage (Git Bash on the Windows dev box, repo venv active):

    python scripts/extract_focas_signatures.py \\
        --header "C:/Fanuc/FwLib64-runtime/Fwlib64.h" \\
        --out tasks/spec-focas-calls.generated.md

Then review `tasks/spec-focas-calls.generated.md`, merge it into
`tasks/spec-focas-calls.md`, commit, push.

This is a developer tool, NOT product code:
- pure stdlib, no dependencies
- does not call the SDK / DLL / control
- output is verbatim text from the header — interpretation happens in the
  spec doc review, not here
- functions not present in the header are flagged `NOT FOUND` so we know
  whether 0i-MF actually exposes them (Decision-2 outcome)

R9 mitigation: nothing in `client.py` may reference a FOCAS function until
that function appears in `tasks/spec-focas-calls.md` with a verbatim
signature taken from this header.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_HEADER = r"C:\Fanuc\FwLib64-runtime\Fwlib64.h"
DEFAULT_OUT = "tasks/spec-focas-calls.generated.md"

# Target FOCAS functions for v1 read coverage (plus the Phase 6 write call).
#
# Names verified against `Fwlib64.h` from `C:\Fanuc\FwLib64-runtime\` on the
# Lance dev box. The first session brief used several FS-16/18/21-era names
# that the FS30i processing DLL (which serves 0i-MF) does not expose; this
# list reflects the names actually present in our header. Resolutions:
#
#   cnc_rdsysinfo     -> dropped; cnc_sysinfo is the real name on this DLL
#   cnc_rdmode        -> dropped; cnc_statinfo returns mode + run + alarm + estop
#   cnc_rdtcode       -> dropped; cnc_modal with T-type covers active T number
#   cnc_rdtoolgrp_id  -> dropped; cnc_rdngrp + cnc_rdgrpid(2) + cnc_rdusegrpid
#                                 plus cnc_rd1tlifedata cover tool life
#
# Order preserved in output.
TARGET_FUNCTIONS: tuple[str, ...] = (
    # Connection lifecycle
    "cnc_allclibhndl3",
    "cnc_freelibhndl",
    "cnc_settimeout",
    # System info
    "cnc_sysinfo",
    "cnc_sysinfo_ex",
    # Machine status (mode, running, e-stop) and modal info (current T)
    "cnc_statinfo",
    "cnc_statinfo2",
    "cnc_modal",
    # Tool offsets
    "cnc_rdtofs",
    "cnc_rdtofsr",
    "cnc_rdtofsinfo",
    "cnc_wrtofs",  # captured for Phase 6 reference; NOT used until then
    # Magazine / pot table
    "cnc_rdmagazine",
    # Tool life management
    "cnc_rdngrp",
    "cnc_rdgrpid",
    "cnc_rdgrpid2",
    "cnc_rdusegrpid",
    "cnc_rd1tlifedata",
    # Alarms
    "cnc_rdalmmsg",
    "cnc_rdalmmsg2",
)

# Identifiers that are NOT user-defined struct types we want to chase down.
# Anything matched by `[A-Z][A-Za-z0-9_]*` in an arg list that's in this set
# is dropped before we go looking for a typedef.
NOT_A_STRUCT: frozenset[str] = frozenset(
    {
        "FAR",
        "WINAPI",
        "FWLIBAPI",
        "CONST",
        "VOID",
        "BYTE",
        "WORD",
        "DWORD",
        "LONG",
        "SHORT",
        "INT",
        "CHAR",
        "FLOAT",
        "DOUBLE",
        "UINT",
        "ULONG",
        "USHORT",
        "UCHAR",
        "HANDLE",
        "BOOL",  # Win32 — present in some FOCAS headers, not data structs
    }
)


def read_header(path: Path) -> str:
    """Read header bytes; decode latin-1 to survive any non-UTF-8 comments
    (FANUC headers occasionally carry Shift-JIS comments on JP-region builds)."""
    return path.read_bytes().decode("latin-1", errors="replace")


def find_declaration(text: str, fn_name: str) -> str | None:
    """Return verbatim declaration text for `fn_name`, or None if absent.

    Walks back from the function-name match to the previous `;` or `}` to
    capture preceding return-type qualifiers and any inline comment block.
    Walks forward from the open paren, brace-matched, to the next `;` to
    capture the full prototype.
    """
    pat = re.compile(rf"\b{re.escape(fn_name)}\s*\(")
    m = pat.search(text)
    if not m:
        return None

    start = m.start()
    cut = max(text.rfind(";", 0, start), text.rfind("}", 0, start), -1) + 1
    head_region = text[cut:start]

    depth = 0
    i = m.end() - 1
    end_idx: int | None = None
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                semi = text.find(";", i)
                if semi != -1:
                    end_idx = semi + 1
                break
        i += 1
    if end_idx is None:
        return None

    body = text[start:end_idx]
    return (head_region + body).strip()


def extract_referenced_types(decl: str) -> list[str]:
    """Pick out candidate struct/typedef names referenced in the arg list.

    Heuristic: tokens matching `[A-Z][A-Z0-9_]{2,}` (all-uppercase, length
    >= 3) inside the outermost parens that aren't in NOT_A_STRUCT. FANUC
    struct typedefs are conventionally all-caps (`IODBTOFS`, `ODBSYS`,
    `ODBTLIFE5`, `ODBALM`); parameter names use camelCase (`FlibHndl`),
    so the case rule excludes parameter names cleanly.
    """
    paren_start = decl.find("(")
    paren_end = decl.rfind(")")
    if paren_start == -1 or paren_end == -1 or paren_end <= paren_start:
        return []
    args = decl[paren_start + 1 : paren_end]
    seen: list[str] = []
    seen_set: set[str] = set()
    for tok in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", args):
        if tok in NOT_A_STRUCT or tok in seen_set:
            continue
        seen.append(tok)
        seen_set.add(tok)
    return seen


def find_typedef(text: str, type_name: str) -> str | None:
    """Return the verbatim `typedef struct ... <type_name> ;` block, or None.

    Brace-matched so nested anonymous structs/unions inside the body don't
    trip us up.
    """
    open_pat = re.compile(r"typedef\s+struct\s*(?:\w+\s*)?\{")
    for m in open_pat.finditer(text):
        depth = 0
        i = m.end() - 1
        while i < len(text):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    rest = text[i + 1 :]
                    name_match = re.match(r"\s*(\w+)\s*;", rest)
                    if name_match and name_match.group(1) == type_name:
                        end = i + 1 + name_match.end()
                        return text[m.start() : end]
                    break
            i += 1
    return None


def extract_all(text: str, names: tuple[str, ...] = TARGET_FUNCTIONS) -> list[dict]:
    out: list[dict] = []
    for name in names:
        decl = find_declaration(text, name)
        types = extract_referenced_types(decl) if decl else []
        typedefs = {t: find_typedef(text, t) for t in types}
        out.append({"name": name, "decl": decl, "types": types, "typedefs": typedefs})
    return out


def emit_markdown(header_path: str, results: list[dict]) -> str:
    found = [r["name"] for r in results if r["decl"] is not None]
    missing = [r["name"] for r in results if r["decl"] is None]

    lines: list[str] = [
        "# tasks/spec-focas-calls.generated.md",
        "",
        f"_Auto-extracted from `{header_path}` by `scripts/extract_focas_signatures.py`._",
        "_Verbatim text — review, then merge relevant sections into `tasks/spec-focas-calls.md`._",
        "",
        "## Summary",
        "",
        f"- Found: {len(found)} / {len(results)}",
        f"- Missing: {len(missing)}",
        "",
        "| Function | Status |",
        "|---|---|",
    ]
    for r in results:
        status = "found" if r["decl"] is not None else "**NOT FOUND**"
        lines.append(f"| `{r['name']}` | {status} |")
    lines.append("")

    for r in results:
        lines.append(f"## `{r['name']}`")
        lines.append("")
        if r["decl"] is None:
            lines.append("**NOT FOUND in this header.**")
            lines.append("")
            lines.append(
                "Likely reasons: function not exposed by the FS30i processing DLL "
                "(`fwlib30i64.dll`) for the 0i-MF series, or the SDK uses a different "
                "name. Cross-check the FOCAS2 developer manual for an equivalent."
            )
            lines.append("")
            continue
        lines.append("Signature (verbatim):")
        lines.append("")
        lines.append("```c")
        lines.append(r["decl"])
        lines.append("```")
        lines.append("")
        if r["types"]:
            lines.append("Referenced struct/type names: " + ", ".join(f"`{t}`" for t in r["types"]))
            lines.append("")
            for t in r["types"]:
                td = r["typedefs"].get(t)
                if td is None:
                    lines.append(
                        f"- `{t}`: typedef NOT FOUND in this header "
                        "(may be a primitive alias, a Win32 typedef, or defined elsewhere)"
                    )
                else:
                    lines.append(f"- `{t}`:")
                    lines.append("")
                    lines.append("```c")
                    lines.append(td)
                    lines.append("```")
            lines.append("")
        else:
            lines.append("No referenced user-defined types in arg list.")
            lines.append("")

    if missing:
        lines.append("---")
        lines.append("")
        lines.append("## Missing functions")
        lines.append("")
        lines.append(
            "These are the functions the session brief asked for that do not "
            "appear in this header. Each one needs a follow-up: either find an "
            "equivalent name, or accept that the 0i-MF doesn't support it and "
            "remove it from the v1 read set."
        )
        lines.append("")
        for n in missing:
            lines.append(f"- `{n}`")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--header", default=DEFAULT_HEADER, help=f"path to Fwlib64.h (default: {DEFAULT_HEADER})"
    )
    p.add_argument(
        "--out", default=DEFAULT_OUT, help=f"output markdown path (default: {DEFAULT_OUT})"
    )
    args = p.parse_args(argv)

    header_path = Path(args.header)
    if not header_path.exists():
        print(f"header not found: {header_path}", file=sys.stderr)
        return 2

    text = read_header(header_path)
    results = extract_all(text)
    md = emit_markdown(str(header_path), results)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

    found = sum(1 for r in results if r["decl"] is not None)
    missing = [r["name"] for r in results if r["decl"] is None]
    print(f"wrote {out_path} ({found}/{len(results)} found)", file=sys.stderr)
    if missing:
        print(f"NOT FOUND: {', '.join(missing)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
