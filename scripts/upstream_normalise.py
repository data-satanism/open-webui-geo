"""Normalise Python source so formatting differences stop hiding real ones.

**At the currently pinned ref this is a no-op, and that is worth knowing.**
The premise it was written for -- "the fork reformatted the whole backend from
double to single quotes" -- does not hold: `routers/files.py`,
`storage/provider.py`, `models/files.py` and `config.py` are byte-identical to
upstream v0.11.0, same blob hash. Upstream is single-quoted at v0.11.0 (398
single, 36 double in `files.py`) and double-quoted at v0.7.0 (14 single, 282
double). **Upstream changed its own style; the fork did not change upstream's
files.**

So this is kept as insurance rather than as the fix. The style has flipped once
between versions already, so a comparison that survives it is worth the
thirty lines -- and a check that fails the day upstream reformats again would
be a check nobody trusts.

Deliberately crude. It is a comparison aid, not a parser: it must never be used
to rewrite a file, only to decide whether two files differ in substance.
"""

from __future__ import annotations

import io
import re
import tokenize


def normalise(source: str) -> str:
    """Quote style, whitespace runs and comments removed, in that order.

    Tokenised rather than regexed for comments and strings, because
    `# not a comment` inside a string literal and `'` inside a docstring both
    defeat a regex, and this runs over `config.py` where both certainly occur.
    Falls back to the regex form only if the file will not tokenise, which for
    a syntactically valid tree means never.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return _normalise_by_regex(source)
    parts: list[str] = []
    for token in tokens:
        if token.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE):
            continue
        if token.type in (tokenize.INDENT, tokenize.DEDENT):
            continue
        text = token.string
        if token.type == tokenize.STRING:
            text = _normalise_string(text)
        parts.append(text)
    return '\n'.join(part for part in parts if part.strip())


_SIMPLE_SINGLE = re.compile(r"^([rbfu]*)'([^'\\\n]*)'$", re.IGNORECASE)


def _normalise_string(text: str) -> str:
    """`'x'` and `"x"` become the same token; anything harder is left alone.

    Only the unambiguous case is rewritten. A literal containing a quote or an
    escape is left exactly as written, because turning `'it\\'s'` into a
    double-quoted form is a source transformation and this is not allowed to
    be one -- getting it wrong would report a difference where there is none,
    or worse, hide one.
    """
    match = _SIMPLE_SINGLE.match(text)
    if not match:
        return text
    prefix, body = match.groups()
    if '"' in body:
        return text
    return f'{prefix}"{body}"'


def _normalise_by_regex(source: str) -> str:  # pragma: no cover - unparseable files
    source = re.sub(r"'([^'\\\n]*)'", r'"\1"', source)
    source = re.sub(r'#.*$', '', source, flags=re.MULTILINE)
    return '\n'.join(
        ' '.join(line.split()) for line in source.splitlines() if line.strip()
    )
