"""Tests for `target_line`: it states the basic fill figure against the target
the record reports, under a label that does not say strict."""

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
    """The target line's label does not say strict."""
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
    """A verdict judged on the strict figure is withheld, and the percentage is
    derived from the audit's basic pair."""
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
    """With neither figure the line says the fill is undetermined rather than
    0%."""
    line = target_line({})

    assert 'не определена' in line
    assert '0%' not in line


def test_a_card_with_no_cells_does_not_divide_by_its_own_absence():
    line = target_line(
        {'audit': {'completeness': {'basic': {'filled': 0, 'of': 0}}}}
    )

    assert 'не определена' in line


def test_the_bar_comes_from_the_record_rather_than_from_this_file():
    """The target comes from `target_fill_rate` in the record."""
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
    """Without a target the line gives the figure and no verdict."""
    line = target_line({'fill_quality': {
        'basic_fill_percent': 69.2, 'target_measured_on': 'basic',
        'target_met': True,
    }})

    assert 'цель не сообщена' in line
    assert 'достигнута' not in line


def test_a_card_with_no_cells_gives_no_verdict_either():
    """With `target_met` None the verdict is undetermined, not missed."""
    line = target_line(_final(
        basic_fill_percent=0.0, target_measured_on='basic', target_met=None,
    ))

    assert 'не определено' in line
    assert 'не достигнута' not in line


def test_the_line_reaches_the_markdown_a_reader_is_handed(monkeypatch):
    """The adapter's result Markdown carries the target line and the
    strict/basic pair with percentages."""
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
    assert '189 из 351 (53.8%, строго)' in result
    assert '243 из 351 (69.2%, с учётом расхождений)' in result
