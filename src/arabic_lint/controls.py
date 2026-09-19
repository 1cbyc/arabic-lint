"""Find invisible bidi control characters left in Arabic text, and in source.

`detect.py` finds Arabic whose *letters* were rewritten before storage. This finds
the characters that were never letters at all: the twelve zero-width bidi controls.
They are invisible, they survive a proofread, and they are handled inconsistently by
almost everything that touches text.

Two separate problems share one signal.

**Residue.** A lone directional mark (ALM, LRM, RLM) changes nothing you can see, but
it is not consistently normalized. Measured on google/sentencepiece 2026-09-19:
`nmt_nfkc`, the default normalizer for SentencePiece training, maps U+200E and U+200F
to a space and leaves the other ten alone -- including U+061C ARABIC LETTER MARK,
which does the same job for Arabic-script runs that the two stripped marks do
everywhere else. The cost is not cosmetic: on google/mt5-base, inserting an ALM takes a
test phrase from 5 pieces to 7, and the word `بالعالم` stops being one word-initial
piece and becomes a bare word-start marker, the ALM, then the word -- so the piece the
model actually learned for that word at a word boundary is never used. An RLM in the
same position changes nothing, because it is stripped. Visually identical text,
different token sequence, and which one you get depends on which pipeline saw it. That
is the recurring blind spot this check exists for: a sanitizer strips some format
characters of a class and misses others of the same class.

**Unterminated scope.** An embedding or override with no matching terminator applies
to everything after it, to the end of the paragraph. `RLO` in particular makes the
rest of the line *display* in an order that is not the order it is stored in, which is
the Trojan Source class of defect. A balanced pair is ordinary directional markup and
is reported as such, quietly.

The two are graded differently on purpose, exactly as stored corruption is: see
`RISK_ORDER` below.

Zero dependencies. `unicodedata` only.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from .detect import is_arabic, is_presentation_form

# The nine explicit directional formatting characters are DERIVED, not tabulated.
# Unicode gives these nine bidi classes to exactly those nine characters and to
# nothing else, so reading the class off `unicodedata` *is* the question "is this an
# explicit directional formatting character". Anything Unicode adds to the set will
# classify itself, the same way a new presentation form does in detect.py.
EXPLICIT = {
    "LRE": "embedding",
    "RLE": "embedding",
    "LRO": "override",
    "RLO": "override",
    "LRI": "isolate",
    "RLI": "isolate",
    "FSI": "isolate",
    "PDF": "pop",
    "PDI": "pop-isolate",
}

# Anything in here opens a scope that something else has to close.
OPENERS = ("embedding", "override", "isolate")

# The three directional MARKS cannot be derived the same way, and the obvious
# derivation is wrong in a way worth writing down rather than discovering twice.
#
# A mark is a Cf character whose bidi class is strong (L, R or AL). Measured over the
# whole codespace on Unicode 16.0, that description matches 23 characters, only three
# of which are directional controls:
#
#     U+061C  ARABIC LETTER MARK                 AL   <- control
#     U+070F  SYRIAC ABBREVIATION MARK           AL      a Syriac character
#     U+200E  LEFT-TO-RIGHT MARK                 L    <- control
#     U+200F  RIGHT-TO-LEFT MARK                 R    <- control
#     U+110BD KAITHI NUMBER SIGN                 L       a Kaithi character
#     U+110CD KAITHI NUMBER SIGN ABOVE           L       a Kaithi character
#     U+13430..U+1343F  Egyptian hieroglyph joiners and segment marks (16 of them)
#
# The property that separates them is `Bidi_Control=Yes`, and stdlib `unicodedata`
# does not expose it (nor `Script`, which would also do it). So these three are named
# rather than derived, and `test_the_naive_mark_derivation_over_matches` asserts the
# over-match so this comment cannot quietly become false. Flagging the Syriac
# abbreviation mark as bidi residue would be the same mistake as flagging the ornate
# Quranic parentheses as a shaping artefact: a character somebody typed on purpose,
# reported as damage.
DIRECTIONAL_MARKS = frozenset({0x061C, 0x200E, 0x200F})


def control_kind(ch: str) -> str | None:
    """'mark', 'embedding', 'override', 'isolate', 'pop', 'pop-isolate', or None.

    The `isprintable()` guard is a cheap C-level pre-filter, not a shortcut around
    the derivation: every character in category Cf is non-printable, so nothing that
    could be a control is skipped by it. `test_every_control_is_non_printable`
    asserts that rather than trusting it.
    """
    if ch.isprintable():
        return None
    return _kind_from(ch, unicodedata.bidirectional(ch))


def _kind_from(ch: str, bidi_class: str) -> str | None:
    kind = EXPLICIT.get(bidi_class)
    if kind is not None:
        return kind
    if ord(ch) in DIRECTIONAL_MARKS:
        return "mark"
    return None


def is_bidi_control(ch: str) -> bool:
    return control_kind(ch) is not None


# Arabic script beyond the main block. `detect.is_arabic` covers U+0600-U+06FF, which
# is where the letters are, but Arabic text carries characters from the supplements
# too and a paragraph made only of those would otherwise read as "no Arabic here".
ARABIC_SUPPLEMENTS = (
    (0x0750, 0x077F),      # Arabic Supplement
    (0x0870, 0x089F),      # Arabic Extended-B
    (0x08A0, 0x08FF),      # Arabic Extended-A
)


def _arabic_here(ch: str) -> bool:
    if is_arabic(ch) or is_presentation_form(ch):
        return True
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in ARABIC_SUPPLEMENTS)


# Risk, and why it is a separate ladder from stored severity.
#
# It has the same three levels in the same order, so ONE `--min-severity` floor gates
# both checks: index 0 reports everything, index 2 reports only the top band. What it
# does not do is reuse the words. A stored finding graded "reshaped" means a shaping
# pass ran over the text; an unterminated RLO means nothing of the sort, and printing
# "reshaped" beside it would be false in the one place the tool is asked to be exact.
#
#   residue    a lone directional mark. Invisible, harmless to display, and stripped
#              by some normalizers and not others -- so the same string tokenizes two
#              ways depending on which pipeline saw it.
#   scoped     an explicit directional run that is opened and closed. This is what the
#              control is for. Reported because normalizers disagree about whether it
#              survives, not because it is wrong.
#   unpaired   a scope that is not closed, or a terminator with nothing to terminate.
#              The first leaks its reordering to the end of the paragraph; the second
#              says the text was spliced.
RISK_ORDER = ("residue", "scoped", "unpaired")

RISK_ADVICE = {
    "residue": "an invisible directional mark in Arabic text. It is not consistently "
               "normalized: SentencePiece's nmt_nfkc strips U+200E and U+200F but "
               "leaves U+061C, so the same word can tokenize two ways. Remove it "
               "unless it is there on purpose.",
    "scoped": "an explicit directional run, opened and closed. Nothing is wrong with "
              "it; it is reported because text pipelines disagree about whether these "
              "survive, and because a reader cannot see it.",
    "unpaired": "the directional scope is not paired. An unclosed embedding or "
                "override applies to everything after it to the end of the paragraph, "
                "so what is displayed is not the order the text is stored in. Close "
                "it, or remove it.",
}

# Notes that depend on the shape of the defect rather than its band. The band decides
# whether CI fails; the note has to be true.
UNCLOSED = ("never closed, so its scope runs to the end of the paragraph")
UNMATCHED_POP = ("there is no open scope for this to close. The bidirectional "
                 "algorithm ignores an unmatched terminator, so it cannot itself "
                 "reorder anything: what it tells you is that the opener was lost, "
                 "i.e. this text was spliced or truncated")
CLOSED_BY_SCOPE = ("terminated by the enclosing isolate's PDI rather than by its own "
                   "PDF, so its scope does not leak past it")
MARK_NOTE = "a directional mark has no scope to pair, so balance does not apply"


@dataclass
class ControlFinding:
    """One bidi control character."""

    line: int
    col: int
    offset: int                  # absolute character offset into the scanned text
    char: str
    kind: str
    bidi_class: str
    balanced: bool | None = None       # None only for a mark: nothing to pair
    partner_offset: int | None = None
    note: str = ""

    @property
    def codepoint(self) -> int:
        return ord(self.char)

    @property
    def name(self) -> str:
        return unicodedata.name(self.char, f"U+{self.codepoint:04X}")

    @property
    def risk(self) -> str:
        if self.kind == "mark":
            return "residue"
        return "scoped" if self.balanced else "unpaired"

    @property
    def advice(self) -> str:
        return RISK_ADVICE[self.risk]

    def __str__(self) -> str:
        return (f"{self.line}:{self.col}: U+{self.codepoint:04X} {self.name} "
                f"[{self.risk}]")


@dataclass
class ControlReport:
    findings: list[ControlFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def unpaired(self) -> list[ControlFinding]:
        return [f for f in self.findings if f.risk == "unpaired"]


def _pair(opener: ControlFinding | None, closer: ControlFinding) -> None:
    if opener is None:
        closer.balanced = False
        closer.note = UNMATCHED_POP
        return
    opener.balanced = closer.balanced = True
    opener.partner_offset = closer.offset
    closer.partner_offset = opener.offset
    opener.note = closer.note = "paired"


def _balance(para: list[ControlFinding]) -> None:
    """Decide, for one paragraph, which scopes are closed.

    A simplified reading of the Unicode bidirectional algorithm's explicit-level
    rules, and the simplifications are deliberate:

      * a PDF matches the nearest unterminated embedding or override, but an isolate
        initiator opened more recently blocks the match (UBA X7);
      * a PDI matches the nearest unterminated isolate initiator and implicitly
        terminates anything opened inside it (UBA X6a), so those are closed, not
        leaking;
      * a paragraph break terminates everything, which is why balance is computed per
        paragraph and never across one.

    What this does NOT do is track the 125-level depth limit or resolve levels. It
    answers one question -- does this scope end where the author said it ends -- and
    anything further would be reimplementing the algorithm to report a linting result.
    """
    stack: list[ControlFinding] = []
    for f in para:
        if f.kind == "mark":
            f.note = MARK_NOTE
            continue
        if f.kind in OPENERS:
            stack.append(f)
            continue
        if f.kind == "pop":                                  # PDF
            partner = None
            for i in range(len(stack) - 1, -1, -1):
                if stack[i].kind == "isolate":
                    break                                    # blocked, UBA X7
                if stack[i].kind in ("embedding", "override"):
                    partner = stack.pop(i)
                    break
            _pair(partner, f)
            continue
        # pop-isolate (PDI)
        partner = None
        for i in range(len(stack) - 1, -1, -1):
            if stack[i].kind == "isolate":
                partner = stack[i]
                for inner in stack[i + 1:]:
                    inner.balanced = True
                    inner.note = CLOSED_BY_SCOPE
                del stack[i:]
                break
        _pair(partner, f)

    for f in stack:
        f.balanced = False
        f.note = UNCLOSED


def scan_text(text: str) -> ControlReport:
    """Find bidi controls. One finding per control character.

    **What is reported, and what stays quiet.** The silence is as much the point here
    as it is in the source check:

      * an *unpaired* control is always reported, whatever script surrounds it. An
        unterminated override reorders whatever follows it, and that is true of a
        Python file with no Arabic in it at all -- which is the Trojan Source case.
      * a *mark* or a *closed* scope is reported only when its paragraph actually
        contains Arabic. Otherwise this would fire on every Hebrew document and every
        correctly marked-up mixed-direction paragraph on earth, and a checker that
        fires on correct text gets switched off.

    Paragraph, not line: a paragraph ends at any character whose bidi class is B,
    which is derived rather than assumed to be `\\n`.
    """
    report = ControlReport()
    line = 1
    col = 1
    para: list[ControlFinding] = []
    has_arabic = False

    def close_paragraph() -> None:
        nonlocal para, has_arabic
        if para:
            _balance(para)
            for f in para:
                if f.risk == "unpaired" or has_arabic:
                    report.findings.append(f)
        para = []
        has_arabic = False

    for offset, ch in enumerate(text):
        if ch.isprintable():
            if _arabic_here(ch):
                has_arabic = True
        else:
            cls = unicodedata.bidirectional(ch)
            if cls == "B":
                close_paragraph()
                if ch == "\n":
                    line += 1
                    col = 1
                    continue
            else:
                kind = _kind_from(ch, cls)
                if kind is not None:
                    para.append(ControlFinding(line=line, col=col, offset=offset,
                                               char=ch, kind=kind, bidi_class=cls))
        col += 1

    close_paragraph()
    return report


# The stored check exports `scan_text` under the same name. Anything importing both
# wants an unambiguous one, and `scan_controls` is what the CLI uses.
scan_controls = scan_text
