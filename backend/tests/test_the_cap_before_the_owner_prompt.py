"""20 000 characters of contributor evidence, and nothing tested the cap.

`normalize_contributor_evidence` bounds `output` with
`MAX_CONTRIBUTOR_EVIDENCE_CHARS` before KB, web and vision evidence reaches
the owner LLM's prompt. `bounded_text` was unit-tested with `max_chars=40`;
this call site — the one that decides what an owner actually sees — had no
test at all, and the constant appeared exactly twice in the tree, both times
in `proposals.py`.

Same family as the two unbounded upstream reads already fixed: a producer this
side does not control feeding a consumer that has a limit. The difference is
that here the limit was already written and simply unverified, so a refactor
could have dropped it silently.
"""

from __future__ import annotations

import pytest

from open_webui.services.core.text import bounded_text
from open_webui.services.project_evidence.proposals import (
    MAX_CONTRIBUTOR_EVIDENCE_CHARS,
    normalize_contributor_evidence,
)

OVERSIZE = 60_000


def _evidence(chars, **extra):
    return {'source_domain': 'kb', 'output': 'ф' * chars, **extra}


def test_the_constant_is_the_one_the_call_site_uses():
    """Pins the wiring, not the number: `bounded_text`'s own test passes
    `max_chars=40` and proves nothing about this call site."""
    assert MAX_CONTRIBUTOR_EVIDENCE_CHARS == 20_000
    expected = bounded_text('ф' * OVERSIZE, max_chars=MAX_CONTRIBUTOR_EVIDENCE_CHARS)
    assert normalize_contributor_evidence(_evidence(OVERSIZE))['output'] == expected


def test_oversized_evidence_is_bounded_before_the_owner_sees_it():
    out = normalize_contributor_evidence(_evidence(OVERSIZE))['output']
    assert len(out) < OVERSIZE
    assert len(out) <= MAX_CONTRIBUTOR_EVIDENCE_CHARS + 200, (
        'the omission notice is the only thing allowed past the cap'
    )


def test_the_truncation_says_it_truncated():
    """A silently shortened evidence blob reads to the owner as the whole of
    what the contributor found."""
    out = normalize_contributor_evidence(_evidence(OVERSIZE))['output']
    assert 'omitted by orchestrator' in out
    assert str(OVERSIZE - MAX_CONTRIBUTOR_EVIDENCE_CHARS) in out


def test_the_tail_survives_because_provenance_lives_there():
    """`bounded_text` keeps head and tail on purpose: citations sit at the end."""
    marked = 'ф' * OVERSIZE + 'ХВОСТ-МАРКЕР'
    out = normalize_contributor_evidence({'source_domain': 'kb', 'output': marked})['output']
    assert out.endswith('ХВОСТ-МАРКЕР')
    assert out.startswith('ф')


@pytest.mark.parametrize('chars', [0, 1, MAX_CONTRIBUTOR_EVIDENCE_CHARS])
def test_evidence_within_the_cap_is_untouched(chars):
    """At exactly the cap it passes whole — `bounded_text` uses `<=`."""
    payload = _evidence(chars)
    assert normalize_contributor_evidence(payload)['output'] == payload['output']


@pytest.mark.parametrize('domain', ['kb', 'web', 'vision', 'gis', '', 'unknown'])
def test_every_domain_is_bounded_not_only_the_default_branch(domain):
    """`gis` and `vision` take different branches above the bound; all three
    reach the same `output` line and all three must be capped."""
    out = normalize_contributor_evidence(_evidence(OVERSIZE, source_domain=domain))['output']
    assert len(out) < OVERSIZE
