"""The line judging a run against 80% counted the cells nobody disagreed about.

Two figures reach the envelope and the card prints both:

    Заполнено: 189 из 351 (строго) · 243 из 351 (с учётом расхождений)

and the next line said «Строгая полнота: 53.8%». One document, two numbers,
one word pointing at the smaller of them. A cell holding a sourced value with
a second sourced value recorded beside it is answered; that is `basic`, and on
run `06d1f455` it is 54 cells and 15.4 points more than `strict`.

The label loses «строгая» because the line no longer carries the strict figure,
and a label naming the wrong one is worse than no label at all.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.terminal import (
    FILL_TARGET_LABEL,
    target_line,
)


def _final(**quality):
    quality.setdefault('target_fill_rate', 0.8)
    return {'fill_quality': quality}


def test_it_prints_the_answered_figure_and_the_verdict():
    line = target_line(
        _final(
            strict_fill_percent=53.8,
            basic_fill_percent=69.2,
            target_measured_on='basic',
            target_met=False,
        )
    )

    assert line == f'- {FILL_TARGET_LABEL}: 69.2% (цель 80%: не достигнута)\n'


def test_the_label_no_longer_claims_the_strict_figure():
    """The other half of the change, and separable from it: a document that
    already prints «строго 189 · с расхождениями 243» must not then offer
    «Строгая полнота: 69.2%», which is neither."""
    line = target_line(
        _final(basic_fill_percent=69.2, target_measured_on='basic', target_met=False)
    )

    assert 'строг' not in line.lower()
    assert line.startswith('- Заполненность: ')


def test_a_met_target_says_so():
    line = target_line(
        _final(basic_fill_percent=84.1, target_measured_on='basic', target_met=True)
    )

    assert 'достигнута' in line and 'не достигнута' not in line


def test_an_older_service_does_not_get_its_verdict_restated(reason=None):
    """Skew, and the reason it is not papered over. A build that judged the
    strict figure sent a verdict about a different population; printing it
    beside the answered percentage would make one look like the measurement of
    the other. The percentage is derived from the pair on the audit -- the
    same division -- and the verdict is withheld."""
    line = target_line(
        {
            'fill_quality': {
                'strict_fill_percent': 53.8,
                'target_met': False,
                'target_fill_rate': 0.8,
            },
            'audit': {'completeness': {'basic': {'filled': 243, 'of': 351}}},
        }
    )

    assert '69.2%' in line
    assert 'по строгой цифре' in line
    assert 'не достигнута' not in line


def test_a_run_that_sent_neither_figure_says_so_rather_than_printing_zero():
    """`0%` is a measurement saying nothing was answered. Nothing was sent."""
    line = target_line({})

    assert 'не определена' in line
    assert '0%' not in line


def test_a_card_with_no_cells_does_not_divide_by_its_own_absence():
    line = target_line(
        {'audit': {'completeness': {'basic': {'filled': 0, 'of': 0}}}}
    )

    assert 'не определена' in line


def test_the_bar_comes_from_the_record_rather_than_from_this_file():
    """Two repositories each held «80%»: the one deciding `target_met` and the
    one printing what it was decided against. A second copy of a number is a
    number that goes stale, and this one had already been copied once."""
    line = target_line(
        _final(
            basic_fill_percent=69.2,
            target_measured_on='basic',
            target_met=False,
            target_fill_rate=0.9,
        )
    )

    assert 'цель 90%' in line
    assert '80%' not in line


def test_a_record_with_no_bar_gives_no_verdict():
    """A figure without a target is still a figure. A verdict without a target
    is invented."""
    line = target_line({'fill_quality': {
        'basic_fill_percent': 69.2, 'target_measured_on': 'basic',
        'target_met': True,
    }})

    assert 'цель не сообщена' in line
    assert 'достигнута' not in line


def test_a_card_with_no_cells_gives_no_verdict_either():
    """`target_met` is `None` when there is nothing to measure, and «не
    достигнута» would read as a run that missed the bar."""
    line = target_line(_final(
        basic_fill_percent=0.0, target_measured_on='basic', target_met=None,
    ))

    assert 'не определено' in line
    assert 'не достигнута' not in line


def test_the_line_reaches_the_markdown_a_reader_is_handed(monkeypatch):
    """Assert on the artefact.

    Every test above calls `target_line` and reads what it returns, which
    proves the function and nothing about whether the adapter still calls it.
    Measured: reverting `tools/geotizer.py` to the inline «Строгая полнота»
    literal left 709 tests green across every file that drives the adapter,
    because none of them asserts on this line. It is the line this whole round
    exists to fix and the one a user actually reads.
    """
    import asyncio

    import open_webui.tools.geotizer as adapter

    final = {
        'run_id': 'run-1',
        'object_name': 'Лекын',
        'counts': {
            'filled': 189, 'not_found': 71,
            'requires_expert_review': 46, 'conflicted': 12,
        },
        'fill_quality': {
            'strict_fill_percent': 53.8,
            'basic_fill_percent': 69.2,
            'target_fill_rate': 0.8,
            'target_measured_on': 'basic',
            'target_met': False,
        },
        'xlsx': {'download_path': '/geotizer/files/run-1/geotizer.xlsx', 'sha256': 'abc'},
        'audit': {
            'summary': {'failed': 0, 'warnings': 0},
            'gates': {'publication': 'blocked'},
            'completeness': {
                'strict': {'filled': 189, 'of': 351},
                'basic': {'filled': 243, 'of': 351},
            },
        },
    }

    async def _noop(*args, **kwargs):
        return None

    async def _pair(runtime):
        from open_webui.services.artifacts.geotizer.terminal import StatusSettings

        return (None, StatusSettings(), None)

    async def _workflow(**kwargs):
        return final

    monkeypatch.setattr(adapter, '_user_model', _noop)
    monkeypatch.setattr(adapter, '_resolve_geotizer_callable', _noop)
    monkeypatch.setattr(adapter, '_build_agent_caller', _pair)
    monkeypatch.setattr(adapter, '_build_rag_dispatcher', lambda request, user: None)
    monkeypatch.setattr(adapter, '_build_vision_evidence_caller', _noop)
    monkeypatch.setattr(adapter, 'run_geotizer_workflow', _workflow)

    result = asyncio.run(
        adapter.fill_geotizer(
            object_name='Лекын',
            __request__=object(),
            __user__={'id': 'u1'},
            __message_id__='m1',
        )
    )

    assert '- Заполненность: 69.2% (цель 80%: не достигнута)' in result
    assert 'Строгая полнота' not in result
    # And the pair is still two lines above it, so the reader can see where
    # 69.2% comes from rather than being asked to trust it.
    assert '189 из 351 (строго)' in result
    assert '243 из 351' in result
