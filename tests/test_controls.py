"""Tests for the bidi control check. Run: python3 -m pytest -q
(or python3 tests/test_controls.py)

Every control in here is written as a `\\u` escape, never as a literal character.
That is not cosmetic: this file is scanned by the tool's own CI run over the
repository, and a literal U+202E in a test fixture would make the repository fail its
own linter. An escape is ordinary ASCII on disk and only becomes a control at runtime,
which is exactly what a fixture should be.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arabic_lint.controls import (  # noqa: E402
    DIRECTIONAL_MARKS, EXPLICIT, RISK_ADVICE, RISK_ORDER,
    control_kind, is_bidi_control, scan_controls,
)
from arabic_lint.detect import SEVERITY_ORDER  # noqa: E402

ALM = "\u061c"
LRM = "\u200e"
RLM = "\u200f"
LRE, RLE, PDF, LRO, RLO = "\u202a", "\u202b", "\u202c", "\u202d", "\u202e"
LRI, RLI, FSI, PDI = "\u2066", "\u2067", "\u2068", "\u2069"

ARABIC = "مرحبا بالعالم"


# --- classification, derived rather than tabulated --------------------------------

def test_the_nine_explicit_controls_classify_from_their_bidi_class():
    """No codepoint table: the bidi class is the answer, so Unicode extends it."""
    assert control_kind(LRE) == "embedding"
    assert control_kind(RLE) == "embedding"
    assert control_kind(LRO) == "override"
    assert control_kind(RLO) == "override"
    assert control_kind(LRI) == control_kind(RLI) == control_kind(FSI) == "isolate"
    assert control_kind(PDF) == "pop"
    assert control_kind(PDI) == "pop-isolate"


def test_the_three_marks_are_controls():
    for ch in (ALM, LRM, RLM):
        assert control_kind(ch) == "mark", f"U+{ord(ch):04X}"
        assert is_bidi_control(ch)


def test_ordinary_text_is_not_a_control():
    for ch in "abc مرحبا ١٢٣\n\t":
        assert control_kind(ch) is None, repr(ch)


def test_other_invisible_format_characters_are_not_bidi_controls():
    """These are Cf and zero-width too, and they are a different problem."""
    for ch in ("\u00ad", "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
        assert control_kind(ch) is None, f"U+{ord(ch):04X}"


def test_every_control_is_non_printable():
    """`control_kind` pre-filters on isprintable() for speed. Prove nothing is lost."""
    import unicodedata
    controls = [chr(cp) for cp in DIRECTIONAL_MARKS]
    controls += [chr(cp) for cp in range(0x110000)
                 if unicodedata.bidirectional(chr(cp)) in EXPLICIT]
    assert len(controls) == 12
    for ch in controls:
        assert not ch.isprintable(), f"U+{ord(ch):04X} would be skipped by the filter"
        assert control_kind(ch) is not None


def test_the_naive_mark_derivation_over_matches():
    """Why the three marks are named and not derived.

    Cf + a strong bidi class looks like the definition of a directional mark and is
    not: on Unicode 16.0 it also returns the Syriac abbreviation mark, two Kaithi
    number signs and sixteen Egyptian hieroglyph joiners. Flagging those as bidi
    residue would be the ornate-parentheses mistake in a new block.
    """
    import unicodedata
    naive = {cp for cp in range(0x110000)
             if unicodedata.category(chr(cp)) == "Cf"
             and unicodedata.bidirectional(chr(cp)) in {"L", "R", "AL"}}
    assert DIRECTIONAL_MARKS < naive
    assert 0x070F in naive          # SYRIAC ABBREVIATION MARK, a real character
    assert 0x110BD in naive         # KAITHI NUMBER SIGN
    assert control_kind("\u070f") is None
    assert control_kind("\U000110bd") is None


# --- the risk ladder --------------------------------------------------------------

def test_risk_ladder_lines_up_with_the_stored_severity_ladder():
    """One --min-severity floor gates both checks, by index. If these ever differ in
    length the gate silently stops meaning the same thing."""
    assert len(RISK_ORDER) == len(SEVERITY_ORDER)
    assert RISK_ORDER == ("residue", "scoped", "unpaired")
    assert all(r in RISK_ADVICE for r in RISK_ORDER)


# --- balance: the assertion the whole feature turns on ----------------------------

def test_a_balanced_pair_is_not_high_risk():
    r = scan_controls(f"{RLE}{ARABIC}{PDF}")
    assert len(r.findings) == 2
    assert [f.risk for f in r.findings] == ["scoped", "scoped"]
    assert all(f.balanced is True for f in r.findings)
    assert r.unpaired == []


def test_a_balanced_pair_records_its_partner():
    r = scan_controls(f"{RLE}{ARABIC}{PDF}")
    opener, closer = r.findings
    assert opener.partner_offset == closer.offset
    assert closer.partner_offset == opener.offset


def test_an_unpaired_override_is_high_risk():
    """RLO with no PDF: everything after it displays in an order it is not stored in."""
    r = scan_controls(f"{ARABIC} {RLO}admin.exe")
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.kind == "override"
    assert f.bidi_class == "RLO"
    assert f.balanced is False
    assert f.risk == "unpaired"
    assert "never closed" in f.note
    assert r.unpaired == [f]


def test_the_same_override_closed_is_not_high_risk():
    """The difference between the two is one character, and it is the whole point."""
    bad = scan_controls(f"{ARABIC} {RLO}admin.exe")
    good = scan_controls(f"{ARABIC} {RLO}admin.exe{PDF}")
    assert bad.findings[0].risk == "unpaired"
    assert [f.risk for f in good.findings] == ["scoped", "scoped"]


def test_an_unbalanced_isolate_is_high_risk():
    r = scan_controls(f"{ARABIC} {RLI}2026")
    assert [f.risk for f in r.findings] == ["unpaired"]
    r2 = scan_controls(f"{ARABIC} {RLI}2026{PDI}")
    assert [f.risk for f in r2.findings] == ["scoped", "scoped"]


def test_a_pdf_cannot_close_an_isolate():
    """UBA X7: a PDF does not terminate an isolate, and an isolate blocks it from
    reaching an embedding opened before it. Both controls here are unpaired."""
    r = scan_controls(f"{ARABIC} {RLI}{PDF}")
    assert [f.kind for f in r.findings] == ["isolate", "pop"]
    assert [f.risk for f in r.findings] == ["unpaired", "unpaired"]


def test_an_embedding_inside_a_closed_isolate_does_not_leak():
    """UBA X6a terminates it at the PDI, so it is closed even with no PDF of its own.
    Reporting it as unpaired would be a false positive on correct markup."""
    r = scan_controls(f"{ARABIC} {RLI}{LRE}2026{PDI}")
    inner = [f for f in r.findings if f.kind == "embedding"][0]
    assert inner.balanced is True
    assert inner.risk == "scoped"
    assert "isolate" in inner.note


def test_a_terminator_with_nothing_to_close_says_the_text_was_spliced():
    r = scan_controls(f"{ARABIC}{PDF}")
    f = r.findings[0]
    assert f.risk == "unpaired"
    assert "no open scope" in f.note
    assert "spliced or truncated" in f.note


def test_a_scope_does_not_survive_a_paragraph_break():
    """An embedding ends at the paragraph, so an opener on line 1 and a PDF on line 2
    are two unpaired controls, not a pair."""
    r = scan_controls(f"{RLE}{ARABIC}\n{ARABIC}{PDF}")
    assert [f.line for f in r.findings] == [1, 2]
    assert [f.risk for f in r.findings] == ["unpaired", "unpaired"]


# --- residue: the measured sentencepiece case -------------------------------------

def test_a_lone_arabic_letter_mark_is_reported_as_residue():
    """The U+061C case: nmt_nfkc strips LRM and RLM and leaves this one, so the same
    word tokenizes two ways depending on which pipeline saw it."""
    r = scan_controls(f"مرحبا {ALM}بالعالم")
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.codepoint == 0x061C
    assert f.name == "ARABIC LETTER MARK"
    assert f.kind == "mark"
    assert f.risk == "residue"
    assert f.balanced is None
    assert "U+061C" in f.advice


def test_lrm_and_rlm_are_residue_too():
    for ch in (LRM, RLM):
        r = scan_controls(f"{ARABIC}{ch}")
        assert [f.risk for f in r.findings] == ["residue"], f"U+{ord(ch):04X}"


def test_a_mark_reports_its_codepoint_name_and_offset():
    r = scan_controls(f"مرحبا{RLM} بالعالم")
    f = r.findings[0]
    assert f.codepoint == 0x200F
    assert f.name == "RIGHT-TO-LEFT MARK"
    assert f.offset == 5
    assert f.line == 1 and f.col == 6


def test_line_and_column_are_reported():
    text = f"line one\nok here\n{ARABIC}{ALM}\n"
    f = scan_controls(text).findings[0]
    assert f.line == 3
    assert f.col == len(ARABIC) + 1


# --- silence, which is the other half of the feature ------------------------------

def test_clean_arabic_is_quiet():
    for s in [ARABIC, "الإمارات العربية المتحدة", "مَرْحَبًا بِكُمْ",
              "Total: 1,250 درهم", "hello world", "المبيعات ٢٠٢٦"]:
        assert scan_controls(s).ok, f"false positive on {s!r}"


def test_marks_outside_arabic_are_not_this_tool_s_business():
    """An LRM in a Hebrew or Latin paragraph is somebody else's linting problem, and
    firing on it is how a checker gets switched off."""
    assert scan_controls(f"שלום{LRM} עולם").ok
    assert scan_controls(f"hello{LRM} world").ok


def test_a_closed_scope_outside_arabic_is_quiet():
    assert scan_controls(f"{RLE}שלום עולם{PDF}").ok


def test_an_unpaired_override_is_reported_even_with_no_arabic_present():
    """The Trojan Source case lands in source files that contain no Arabic at all, and
    an unterminated override reorders whatever follows it whatever script that is."""
    r = scan_controls(f"if access_level != 'user' {RLO} # begin admin only")
    assert [f.risk for f in r.findings] == ["unpaired"]


def test_arabic_anywhere_in_the_paragraph_counts():
    """Around, not only inside: a mark at the start of a line whose Arabic comes later
    is still residue in Arabic text."""
    r = scan_controls(f"{ALM}label: {ARABIC}")
    assert [f.risk for f in r.findings] == ["residue"]


# --- CLI wiring -------------------------------------------------------------------

def test_cli_json_shape_and_severity_gate():
    """The floor named for stored severity gates controls at the same index."""
    import json
    import io
    import contextlib
    from arabic_lint.cli import main

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sample.txt"
        p.write_text(f"{ARABIC}{ALM}\n{ARABIC} {RLO}whatever\n", encoding="utf-8")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main([str(p), "--json"])
        assert code == 1
        data = json.loads(buf.getvalue())
        risks = [c["risk"] for c in data["control_findings"]]
        assert risks == ["residue", "unpaired"]
        first = data["control_findings"][0]
        assert first["codepoint"] == "U+061C"
        assert first["name"] == "ARABIC LETTER MARK"
        assert first["balanced"] is None
        assert set(first) >= {"file", "line", "col", "offset", "codepoint", "name",
                              "kind", "bidi_class", "balanced", "partner_offset",
                              "risk", "note", "advice"}

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main([str(p), "--json", "--min-severity", "reshaped"])
        gated = json.loads(buf.getvalue())
        assert [c["risk"] for c in gated["control_findings"]] == ["unpaired"]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main([str(p), "--json", "--no-controls"])
        off = json.loads(buf.getvalue())
        assert off["control_findings"] == []
        assert code == 0


def test_cli_text_output_names_the_character():
    import io
    import contextlib
    import tempfile
    from arabic_lint.cli import main

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sample.txt"
        p.write_text(f"{ARABIC} {RLO}admin.exe\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert main([str(p)]) == 1
        out = buf.getvalue()
        assert "U+202E RIGHT-TO-LEFT OVERRIDE" in out
        assert "[unpaired]" in out
        assert "override (bidi class RLO)" in out
        assert "1 bidi control(s) (1 unpaired)" in out


def test_cli_stays_quiet_on_clean_arabic():
    import io
    import contextlib
    import tempfile
    from arabic_lint.cli import main

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "clean.txt"
        p.write_text("الإمارات العربية المتحدة\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert main([str(p)]) == 0
        assert "clean" in buf.getvalue()


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


# Kept at the very end, for the reason recorded in test_detect.py: `_run()` collects
# from globals(), so anything defined below this point would be skipped in silence.
if __name__ == "__main__":
    raise SystemExit(_run())
