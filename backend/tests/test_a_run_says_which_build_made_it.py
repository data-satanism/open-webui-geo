"""Tests that `build_revision` reports the commit and the tree state together, reports an unknown state as unknown, and
reaches the run log.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from open_webui.build_revision import (
    ABSENCE_KEY,
    CHECKOUT_VARIABLE,
    DEFAULT_CHECKOUT,
    FROM_GIT,
    UNREADABLE_ABSENCE,
    _git,
    build_revision,
    checkout_path,
)

SHA = 'b0e69529d40b36e39cc37888b3d2bc95f648456f'


@pytest.fixture(autouse=True)
def _uncached():
    """`build_revision` caches for the process; each case needs its own read."""
    build_revision.cache_clear()
    yield
    build_revision.cache_clear()


def _answers(monkeypatch, mapping):
    """Stub git: `{argv-tuple: stdout or None}`."""
    calls = []

    def fake(*args):
        calls.append(args)
        return mapping.get(args)

    monkeypatch.setattr('open_webui.build_revision._git', fake)
    return calls


def test_it_records_the_commit_and_the_tree_together(monkeypatch):
    _answers(monkeypatch, {('rev-parse', 'HEAD'): SHA + '\n', ('status', '--porcelain'): ''})

    assert build_revision() == {'revision': SHA, 'dirty': False, 'source': FROM_GIT}


def test_a_tree_edited_after_the_commit_says_so(monkeypatch):
    """A tree with changes after the commit reports `dirty: True`."""
    _answers(monkeypatch, {
        ('rev-parse', 'HEAD'): SHA + '\n',
        ('status', '--porcelain'): ' M backend/open_webui/asgi.py\n',
    })

    assert build_revision() == {'revision': SHA, 'dirty': True, 'source': FROM_GIT}


def test_an_unaskable_tree_is_unknown_and_never_clean(monkeypatch):
    """A tree whose status cannot be read reports `dirty: None`, never `False`."""
    _answers(monkeypatch, {('rev-parse', 'HEAD'): SHA + '\n', ('status', '--porcelain'): None})

    answer = build_revision()

    assert answer == {'revision': SHA, 'dirty': None, 'source': FROM_GIT}
    assert answer['dirty'] is not False


def test_an_unknown_commit_does_not_get_a_tree_verdict(monkeypatch):
    """An unreadable HEAD reports no tree state and never runs `status`."""
    calls = _answers(monkeypatch, {('rev-parse', 'HEAD'): None})

    assert build_revision() == {'revision': None, 'dirty': None, 'source': FROM_GIT,
     ABSENCE_KEY: UNREADABLE_ABSENCE}
    assert ('status', '--porcelain') not in calls


def test_the_reading_is_taken_once(monkeypatch):
    calls = _answers(monkeypatch, {('rev-parse', 'HEAD'): SHA, ('status', '--porcelain'): ''})

    build_revision()
    build_revision()
    build_revision()

    assert calls.count(('rev-parse', 'HEAD')) == 1


def test_the_path_comes_from_configuration_not_from_a_constant():
    """`checkout_path` takes the checkout from `CHECKOUT_VARIABLE`."""
    assert checkout_path({CHECKOUT_VARIABLE: '/srv/open-webui-geo'}) == Path(
        '/srv/open-webui-geo'
    )


def test_an_unset_variable_falls_back_to_where_this_file_is():
    assert checkout_path({}) == DEFAULT_CHECKOUT


def test_a_cleared_variable_is_not_read_as_the_current_directory():
    """An empty or blank `CHECKOUT_VARIABLE` falls back to `DEFAULT_CHECKOUT`."""
    assert checkout_path({CHECKOUT_VARIABLE: ''}) == DEFAULT_CHECKOUT
    assert checkout_path({CHECKOUT_VARIABLE: '   '}) == DEFAULT_CHECKOUT


def test_a_configured_path_that_does_not_exist_is_unknown_not_a_crash(monkeypatch):
    """A configured checkout that does not exist yields an unreadable revision, not an exception."""
    monkeypatch.setenv(CHECKOUT_VARIABLE, '/nonexistent/checkout')
    build_revision.cache_clear()

    answer = build_revision()

    assert answer == {'revision': None, 'dirty': None, 'source': FROM_GIT,
     ABSENCE_KEY: UNREADABLE_ABSENCE}


def test_git_absent_from_the_path_is_an_answer_not_an_exception(monkeypatch):
    """`_git` returns None when git is not installed."""
    def explode(*args, **kwargs):
        raise FileNotFoundError('git')

    monkeypatch.setattr(subprocess, 'run', explode)

    assert _git('rev-parse', 'HEAD') is None


def test_an_unreadable_checkout_is_the_same_answer(monkeypatch):
    def explode(*args, **kwargs):
        raise PermissionError('.git')

    monkeypatch.setattr(subprocess, 'run', explode)

    assert _git('rev-parse', 'HEAD') is None


def test_a_hanging_git_is_the_same_answer(monkeypatch):
    def explode(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd='git', timeout=5)

    monkeypatch.setattr(subprocess, 'run', explode)

    assert _git('status', '--porcelain') is None


def test_a_non_zero_exit_is_the_same_answer(monkeypatch):
    """`_git` returns None on a non-zero exit, whatever `stdout` holds."""
    class _Finished:
        returncode = 128
        stdout = 'fatal: not a git repository\n'

    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: _Finished())

    assert _git('rev-parse', 'HEAD') is None


def test_the_real_checkout_answers_both_fields():
    """On this repository's own checkout, `build_revision` returns `revision`, `dirty` and `source`."""
    answer = build_revision()

    assert set(answer) == {'revision', 'dirty', 'source'}
    assert answer['source'] == FROM_GIT
    assert answer['dirty'] in {True, False, None}
    if answer['revision'] is not None:
        assert len(answer['revision']) == 40


def test_the_run_log_carries_it():
    """The `build_revision` passed to the workflow reaches `run_log.build_revision` in the `finalize` payload."""
    import asyncio
    import json

    from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

    sent = {}

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'build-e2e',
                'object_name': 'Лекын',
                'datacube': {},
                'next_batch': None,
            }
        if payload['action'] == 'submit_batch':
            return {'workflow_status': 'collecting', 'run_id': 'build-e2e', 'next_batch': None}
        sent.update(payload)
        return {
            'workflow_status': 'finalized',
            'run_id': 'build-e2e',
            'xlsx': {'download_path': '/geotizer/files/build-e2e/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        return json.dumps({'patches': []}, ensure_ascii=False)

    asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            build_revision={'revision': SHA, 'dirty': True, 'source': FROM_GIT},
        )
    )

    assert sent['run_log']['build_revision'] == {
        'revision': SHA, 'dirty': True, 'source': FROM_GIT,
    }


def test_a_run_told_nothing_records_nothing_rather_than_a_placeholder():
    """A workflow given no `build_revision` sends no `build_revision` key in the run log."""
    import asyncio
    import json

    from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

    sent = {}

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting', 'run_id': 'r', 'object_name': 'Л',
                'datacube': {}, 'next_batch': None,
            }
        if payload['action'] == 'submit_batch':
            return {'workflow_status': 'collecting', 'run_id': 'r', 'next_batch': None}
        sent.update(payload)
        return {
            'workflow_status': 'finalized', 'run_id': 'r',
            'xlsx': {'download_path': '/geotizer/files/r/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        return json.dumps({'patches': []}, ensure_ascii=False)

    asyncio.run(
        run_geotizer_workflow(
            object_name='Л', project_id=None, model_run_id=None, run_id=None,
            allow_draft=True, gis_call=gis_call, agent_call=agent_call,
        )
    )

    assert 'build_revision' not in (sent.get('run_log') or {})


def _hostile_checkout(tmp_path: Path) -> tuple[Path, Path]:
    """A git checkout whose `core.fsmonitor` names a hook that creates a sentinel file; returns the repository and the
    sentinel path.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()
    sentinel = tmp_path / 'the-command-ran'
    hook = repo / 'hook.sh'
    hook.write_text(
        f'#!/usr/bin/env sh\ntouch {sentinel}\nexit 1\n', encoding='utf-8'
    )
    hook.chmod(0o755)
    identity = ('-c', 'user.email=t@example.invalid', '-c', 'user.name=t')
    for argv in (
        ('init', '-q', '.'),
        identity + ('commit', '-q', '--allow-empty', '-m', 'one'),
        ('config', 'core.fsmonitor', str(hook)),
    ):
        subprocess.run(('git', *argv), cwd=repo, check=True, capture_output=True)
    return repo, sentinel


def test_a_directory_does_not_get_to_decide_what_runs(tmp_path):
    """`_git` does not run a command named by the checkout's own git config."""
    repo, sentinel = _hostile_checkout(tmp_path)

    _git('status', '--porcelain', cwd=repo)

    assert not sentinel.exists()


def test_that_checkout_really_would_run_it(tmp_path):
    """Plain `git status` in the hostile checkout does run its hook."""
    repo, sentinel = _hostile_checkout(tmp_path)

    subprocess.run(
        ('git', 'status', '--porcelain'), cwd=repo, check=False, capture_output=True
    )

    assert sentinel.exists()


def test_a_null_revision_says_which_kind_of_null_it_is(monkeypatch):
    """An unreadable revision carries `ABSENCE_KEY` set to `UNREADABLE_ABSENCE`."""
    _answers(monkeypatch, {})
    answer = build_revision()

    assert answer['revision'] is None
    assert answer[ABSENCE_KEY] == UNREADABLE_ABSENCE


def test_a_revision_that_was_read_says_nothing_about_absence():
    """A revision that was read carries no `ABSENCE_KEY`."""
    answer = build_revision()

    assert answer['revision'] is not None
    assert ABSENCE_KEY not in answer
