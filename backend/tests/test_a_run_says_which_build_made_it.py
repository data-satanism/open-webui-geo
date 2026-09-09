"""A-352. Neither run knew which build produced it.

`0b5ae763` and `bc4af304` both recorded `run_variance.measured: false`,
`reason: build_not_readable`, and `build_ref` null for GMM, gis_service and
open-webui-geo alike. Every comparison between their numbers rests on the
assumption that one build made both, and nothing checked it.

Two values, never one. `rev-parse` alone returns the last commit whether or not
files changed after it, and this contour edits files in place — so a dirty tree
reports a commit it is no longer running. «b0e6952, dirty» is honest;
«b0e6952» alone is worse than «unknown», because it reads as a measurement.

And `unknown` is its own answer, not `clean`. «We did not look» and «we looked
and nothing had changed» are different facts; collapsing them is the shape this
project keeps finding — an absent measurement wearing a measurement's clothes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from open_webui.build_revision import (
    CHECKOUT_VARIABLE,
    DEFAULT_CHECKOUT,
    FROM_GIT,
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
    """The case the contour is in: files changed in place after checkout."""
    _answers(monkeypatch, {
        ('rev-parse', 'HEAD'): SHA + '\n',
        ('status', '--porcelain'): ' M backend/open_webui/asgi.py\n',
    })

    assert build_revision() == {'revision': SHA, 'dirty': True, 'source': FROM_GIT}


def test_an_unaskable_tree_is_unknown_and_never_clean(monkeypatch):
    """The whole point. `clean` here would claim a check that did not happen."""
    _answers(monkeypatch, {('rev-parse', 'HEAD'): SHA + '\n', ('status', '--porcelain'): None})

    answer = build_revision()

    assert answer == {'revision': SHA, 'dirty': None, 'source': FROM_GIT}
    assert answer['dirty'] is not False


def test_an_unknown_commit_does_not_get_a_tree_verdict(monkeypatch):
    """«Dirty relative to nothing» is not a finding, so the tree is not asked
    about and `status` is never run."""
    calls = _answers(monkeypatch, {('rev-parse', 'HEAD'): None})

    assert build_revision() == {'revision': None, 'dirty': None, 'source': FROM_GIT}
    assert ('status', '--porcelain') not in calls


def test_the_reading_is_taken_once(monkeypatch):
    calls = _answers(monkeypatch, {('rev-parse', 'HEAD'): SHA, ('status', '--porcelain'): ''})

    build_revision()
    build_revision()
    build_revision()

    assert calls.count(('rev-parse', 'HEAD')) == 1


# ------------------------------------------- the checkout it is pointed at


def test_the_path_comes_from_configuration_not_from_a_constant():
    """The operator has to be able to point this at the real location without
    a code change. gis_service cannot use a path at all — it has no `.git` —
    but this service runs from a checkout, and where that checkout is is a
    deployment fact, not a source fact."""
    assert checkout_path({CHECKOUT_VARIABLE: '/srv/open-webui-geo'}) == Path(
        '/srv/open-webui-geo'
    )


def test_an_unset_variable_falls_back_to_where_this_file_is():
    assert checkout_path({}) == DEFAULT_CHECKOUT


def test_a_cleared_variable_is_not_read_as_the_current_directory():
    """An empty string is a path — the current directory — and it is never what
    an operator means by clearing a variable. Honouring it would make the
    answer depend on where the process happened to be started."""
    assert checkout_path({CHECKOUT_VARIABLE: ''}) == DEFAULT_CHECKOUT
    assert checkout_path({CHECKOUT_VARIABLE: '   '}) == DEFAULT_CHECKOUT


def test_a_configured_path_that_does_not_exist_is_unknown_not_a_crash(monkeypatch):
    """The rule that has to survive every change here: a service that will not
    start because it cannot name its revision is worse than one that cannot
    name it."""
    monkeypatch.setenv(CHECKOUT_VARIABLE, '/nonexistent/checkout')
    build_revision.cache_clear()

    answer = build_revision()

    assert answer == {'revision': None, 'dirty': None, 'source': FROM_GIT}


# --------------------------------------------- git itself, ungoverned


def test_git_absent_from_the_path_is_an_answer_not_an_exception(monkeypatch):
    """A service that will not start because it cannot name its own revision is
    worse than one that cannot name it."""
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
    """Not a repository, for instance. `stdout` may still hold something."""
    class _Finished:
        returncode = 128
        stdout = 'fatal: not a git repository\n'

    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: _Finished())

    assert _git('rev-parse', 'HEAD') is None


def test_the_real_checkout_answers_both_fields():
    """No stub. This repository is a checkout, which is the premise
    gis_service's `run_variance` docstring denies for a deployment — and the
    reason that module reports `build_not_readable` where this one does not."""
    answer = build_revision()

    assert set(answer) == {'revision', 'dirty', 'source'}
    assert answer['source'] == FROM_GIT
    assert answer['dirty'] in {True, False, None}
    if answer['revision'] is not None:
        assert len(answer['revision']) == 40


# ------------------------------------- and it reaches the run the GIS server keeps


def test_the_run_log_carries_it():
    """Asserted on what `finalize` is sent, not on the reader.

    The reader answering correctly proves nothing about whether any run records
    it — that was the split `test_both_completeness_figures_reach_the_envelope`
    got wrong, and this is the same shape one round later.
    """
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
    """An absent key says the caller did not supply it. A key holding
    a null revision would say the caller looked and could not tell — which is
    the reader's answer, not the workflow's to invent."""
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
    """A checkout whose own config asks git to run a command.

    `checkout_path` is configuration, so the directory git is pointed at is not
    necessarily one this project wrote. A repository's `.git/config` can name a
    command in `core.fsmonitor` and `git status` runs it — this builds exactly
    that, with `touch` standing in for whatever a real one would do.
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
    """The reader must not execute a command the directory supplied.

    Pointing `GEOTEASER_WEBUI_CHECKOUT` somewhere is an operator's decision, but
    «somewhere» may be a tree somebody else can write into, and git's
    `safe.directory` check does not cover it — that refuses directories owned by
    another user, and the case that matters is a writable directory owned by
    this one.
    """
    repo, sentinel = _hostile_checkout(tmp_path)

    _git('status', '--porcelain', cwd=repo)

    assert not sentinel.exists()


def test_that_checkout_really_would_run_it(tmp_path):
    """A test that passes for a reason unrelated to its subject is not a test.
    If the fixture ever stops arming the hook, the check above passes while
    proving nothing — so this proves the hook is armed."""
    repo, sentinel = _hostile_checkout(tmp_path)

    subprocess.run(
        ('git', 'status', '--porcelain'), cwd=repo, check=False, capture_output=True
    )

    assert sentinel.exists()
