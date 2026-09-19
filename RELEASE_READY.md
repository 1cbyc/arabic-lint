# arabic-lint 0.7.0 — built, tested, NOT released

Prepared 2026-09-19. Everything below was run; nothing was pushed, tagged or uploaded.
**The release is yours to authorise.** A PyPI version number is consumed permanently,
so it is not something to try and undo.

## What the feature does

A third check: **invisible bidi control characters** surviving in Arabic text and in
source. It reports the codepoint, the Unicode name, line, column and absolute offset,
the kind and bidi class, and whether the scope is balanced.

It grades two genuinely different problems apart, the same way stored severity does:

| risk | what it is | why it is not the other one |
|---|---|---|
| `residue` | a lone ALM / LRM / RLM | invisible and harmless to display, but **not consistently stripped** |
| `scoped` | an embedding, override or isolate, opened and closed | ordinary directional markup; nothing is wrong with it |
| `unpaired` | a scope with no terminator, or a terminator with no scope | the rest of the paragraph **displays in an order it is not stored in** — the Trojan Source class |

`residue` is the generalisation of the sentencepiece finding: `nmt_nfkc`, the default
normalizer for SentencePiece training, strips `U+200E` and `U+200F` and leaves `U+061C`
ARABIC LETTER MARK, which does the same job. Same visible text, different token
sequence, decided by which pipeline saw it.

Two things about it that are deliberate and worth reading before the release:

- **The nine explicit formatting characters are derived from their Unicode bidi class,
  not tabulated**, so a future addition classifies itself — the same rule the
  presentation-form check uses. The three directional marks are *named*, because the
  identifying property is `Bidi_Control` and stdlib `unicodedata` does not expose it.
  The obvious substitute is wrong: `Cf` + a strong bidi class matches **23** characters
  on Unicode 16.0, including the Syriac abbreviation mark, two Kaithi number signs and
  sixteen Egyptian hieroglyph joiners — characters people type on purpose. A test
  asserts that over-match, so the reason cannot quietly go stale.
- **The silence is half the feature.** A mark or a closed scope is reported only when
  its paragraph contains Arabic; otherwise it would fire on every correctly marked-up
  Hebrew document. An *unpaired* control is reported whatever the script, because an
  unterminated override reorders whatever follows it and the Trojan Source case lands
  in files with no Arabic in them.

Also new: `--no-controls`. `--min-severity` gates the new findings by position on its
own ladder, so `--min-severity reshaped` (the pre-commit and GitHub Action default)
narrows controls to unpaired ones only. `--fix` never touches a control.

## Tests

**75 passed, 0 failed** (`pytest -q`), up from 47. The 28 new tests are
`tests/test_controls.py`, in the repo's existing style and runnable standalone
(`python3 tests/test_controls.py` → `28/28 passed`).

The balance logic is asserted both ways, which was the point: a balanced `RLE … PDF`
comes back `scoped` and the same override without its `PDF` comes back `unpaired`, and
one test holds the two strings side by side so the difference is visibly one character.
Also asserted: a `PDF` cannot close an isolate (UBA X7), an embedding inside a closed
isolate does **not** count as leaking (UBA X6a — reporting it would be a false positive
on correct markup), a scope does not survive a paragraph break, and an unmatched
terminator says the text was spliced rather than claiming it reorders anything.

## Verified, not asserted

- `pytest -q` → **75 passed**.
- Wheel built in a throwaway venv: `dist/arabic_lint-0.7.0-py3-none-any.whl`.
  `twine check` → PASSED on both artifacts.
- Installed **from that wheel** into a clean venv (`/tmp/wheelcheck`, nothing else in
  it) and ran the **shipped console script** on a real four-file sample:

  ```
  /tmp/sample/auth.py:2:26: U+202E RIGHT-TO-LEFT OVERRIDE [unpaired]
      kind      : override (bidi class RLO), offset 42
      balance   : never closed, so its scope runs to the end of the paragraph
  /tmp/sample/balanced.txt:1:10: U+202B RIGHT-TO-LEFT EMBEDDING [scoped]
      balance   : paired
  /tmp/sample/invoice_ar.json:3:18: U+061C ARABIC LETTER MARK [residue]
      balance   : a directional mark has no scope to pair, so balance does not apply

  4 bidi control(s) (1 residue, 2 scoped, 1 unpaired) - in 4 file(s) scanned.
  ```

  Clean Arabic (`الإمارات العربية المتحدة`, `مرحبا بالعالم ١٢٣`) → `clean - 1 file(s)
  scanned`, exit 0. `--min-severity reshaped` → the unpaired RLO alone. `--no-controls`
  → exit 0. JSON carries the new `control_findings` key beside the untouched `findings`
  and `source_findings`.
- **Zero runtime dependencies survived the release build.** Read off the wheel's own
  METADATA, not the source tree: every `Requires-Dist` line carries `extra == "test"`,
  and `importlib.metadata.requires()` in the clean venv returns no bare requirement.
  `controls.py` imports `unicodedata` and `dataclasses` only.
- The existing CI fixtures behave exactly as before at the Action's default gate:
  `.github/fixtures/clean` → 0, `.github/fixtures/stray` → 0, `demo` → 1.
- The repository does not flag itself. Every control in the new tests is written as a
  `\u` escape rather than a literal, so the file is plain ASCII on disk — a literal
  U+202E in a fixture would have made the repo fail its own linter. A self-scan
  reports `control_findings: none` across 26 files.

## One thing to know before upgrading anyone

A repository that already carries an unpaired control will now **fail a gate it passed
before**. That is the check working, but it is a new failure mode on upgrade, and it is
recorded at the top of the CHANGELOG rather than buried.

## The release, once you say go

Artifacts for 0.7.0 are already built and checked in `dist/`. From
`~/jarvis/workspace/arabic_lint`:

```
.relvenv/bin/twine upload dist/arabic_lint-0.7.0*
```

(The token is `__token__` in `~/.pypirc`. There is no local `twine`; use the one in
`.relvenv`, which is gitignored.)

Then, and only if the upload succeeds:

```
git add -A && git commit -m "Release 0.7.0: find the invisible bidi controls, and grade an unterminated scope apart from residue"
git tag -a v0.7.0 -m "0.7.0" && git push && git push --tags
```

`git tag -a` needs a real `user.email` set in this clone; the `-c` flags on the commit
are not enough for it.

Worth doing after, the way 0.2.0–0.6.x were proved: install from **PyPI** into a fresh
venv and re-run the console script on `/tmp/sample`, rather than trusting the upload
output.
