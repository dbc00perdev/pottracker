"""Tests for scripts/extract_focas_signatures.py.

Runs against synthetic header text that exercises the parsing edge cases
encountered in real Fwlib64.h: multi-line declarations, leading comments,
nested anonymous structs in typedefs, and missing functions.

These tests run on Linux CI without needing the real header or DLL.
"""

from __future__ import annotations

import textwrap

from scripts.extract_focas_signatures import (
    emit_markdown,
    extract_all,
    extract_referenced_types,
    find_declaration,
    find_typedef,
)

SYNTHETIC = textwrap.dedent("""
    /* fake fragment of Fwlib64.h for testing */

    typedef struct iodbtofs {
        short  datano ;
        short  type ;
        long   data ;
    } IODBTOFS ;

    typedef struct odbsysex {
        short addinfo ;
        struct {
            char  series[16] ;
            char  version[16] ;
        } cnc_sw ;
        char machine_type[16] ;
    } ODBSYSEX ;

    /* allocate library handle (Ethernet) */
    FWLIBAPI short WINAPI cnc_allclibhndl3( const char *ipaddr,
                                            unsigned short port,
                                            long timeout,
                                            unsigned short *FlibHndl ) ;

    /* free library handle */
    FWLIBAPI short WINAPI cnc_freelibhndl( unsigned short FlibHndl ) ;

    /* read tool offset; 0i-MF and 30i family supported */
    FWLIBAPI short WINAPI cnc_rdtofs( unsigned short FlibHndl, short num,
                                      short type, short length,
                                      IODBTOFS *tofs ) ;
""").strip()


class TestFindDeclaration:
    def test_basic_match(self):
        decl = find_declaration(SYNTHETIC, "cnc_rdtofs")
        assert decl is not None
        assert "cnc_rdtofs(" in decl
        assert "IODBTOFS *tofs" in decl
        assert decl.rstrip().endswith(";")

    def test_captures_leading_comment(self):
        decl = find_declaration(SYNTHETIC, "cnc_rdtofs")
        assert decl is not None
        assert "0i-MF and 30i family supported" in decl

    def test_multiline_declaration(self):
        decl = find_declaration(SYNTHETIC, "cnc_allclibhndl3")
        assert decl is not None
        assert "ipaddr" in decl
        assert "FlibHndl" in decl
        # Should not gobble subsequent declarations
        assert "cnc_freelibhndl" not in decl

    def test_missing_returns_none(self):
        assert find_declaration(SYNTHETIC, "cnc_does_not_exist") is None


class TestExtractReferencedTypes:
    def test_picks_user_struct(self):
        decl = find_declaration(SYNTHETIC, "cnc_rdtofs")
        assert decl is not None
        types = extract_referenced_types(decl)
        assert "IODBTOFS" in types

    def test_drops_qualifier_macros(self):
        decl = find_declaration(SYNTHETIC, "cnc_rdtofs")
        assert decl is not None
        types = extract_referenced_types(decl)
        for noise in ("FWLIBAPI", "WINAPI"):
            assert noise not in types

    def test_no_user_types_for_simple_fn(self):
        decl = find_declaration(SYNTHETIC, "cnc_freelibhndl")
        assert decl is not None
        assert extract_referenced_types(decl) == []


class TestFindTypedef:
    def test_simple_typedef(self):
        td = find_typedef(SYNTHETIC, "IODBTOFS")
        assert td is not None
        assert "datano" in td
        assert td.startswith("typedef")
        assert td.rstrip().endswith(";")

    def test_typedef_with_nested_anonymous_struct(self):
        td = find_typedef(SYNTHETIC, "ODBSYSEX")
        assert td is not None
        assert "cnc_sw" in td
        assert "machine_type" in td
        # both braces present, not truncated mid-struct
        assert td.count("{") == td.count("}")

    def test_missing_typedef_returns_none(self):
        assert find_typedef(SYNTHETIC, "NEVER_EXISTED_T") is None


class TestExtractAll:
    def test_marks_missing_functions(self):
        results = extract_all(SYNTHETIC, names=("cnc_rdtofs", "cnc_rdmagazine"))
        by_name = {r["name"]: r for r in results}
        assert by_name["cnc_rdtofs"]["decl"] is not None
        assert by_name["cnc_rdmagazine"]["decl"] is None

    def test_resolves_typedef_for_referenced_type(self):
        results = extract_all(SYNTHETIC, names=("cnc_rdtofs",))
        r = results[0]
        assert "IODBTOFS" in r["types"]
        assert r["typedefs"]["IODBTOFS"] is not None
        assert "datano" in r["typedefs"]["IODBTOFS"]


class TestEmitMarkdown:
    def test_includes_summary_and_per_function_sections(self):
        results = extract_all(SYNTHETIC, names=("cnc_rdtofs", "cnc_rdmagazine"))
        md = emit_markdown("synthetic.h", results)
        assert "## Summary" in md
        assert "## `cnc_rdtofs`" in md
        assert "## `cnc_rdmagazine`" in md
        assert "**NOT FOUND**" in md
        # verbatim signature block
        assert "```c" in md
        assert "IODBTOFS *tofs" in md

    def test_lists_missing_at_bottom(self):
        results = extract_all(SYNTHETIC, names=("cnc_rdtofs", "cnc_rdmagazine"))
        md = emit_markdown("synthetic.h", results)
        assert "## Missing functions" in md
        assert "- `cnc_rdmagazine`" in md
