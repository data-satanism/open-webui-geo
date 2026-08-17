"""What the caller is handed back: the terminal envelope and its failures.

`implementation-steps.md` S1.6, second half. The terminal result is the tool's
return value -- Native Mode overwrites `message` and `chat:message:delta` with
completion snapshots, so a progress event cannot carry the outcome. Building
that value is a rendering decision, and rendering decisions belong in the core
rather than in the adapter.

`_emit_status` takes the emitter as an argument and never reaches for one, so
this module stays pure while the thing it writes to does not. The wording of
what it writes lives here too, in `PHRASE` and `StatusSettings`: choosing the
sentence a user reads is a rendering decision, and rendering decisions belong
in the core rather than at the five call sites in `workflow.py`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...geotizer.errors import GeotizerOrchestrationError
from .owner_envelope import xlsx_download_path


def carry_forward_summary(final: Mapping[str, Any]) -> dict[str, Any]:
    """What of this card came from an earlier run, from terminal state alone.

    GT-GIS-01. The mechanism was invisible: run `e4368779` reported 343/351
    filled and 339 of those were carried from a previous card. A completeness
    figure that does not say so is the coverage-as-accuracy failure this project
    exists to remove -- the number reads as "this run found 343 facts" and means
    "this run found four".
    """
    block = final.get('carry_forward')
    block = block if isinstance(block, Mapping) else {}
    parents = [str(run) for run in block.get('parent_run_ids') or () if str(run)]
    carried = int(block.get('carried_field_count') or len(block.get('carried_field_keys') or ()))
    # Whether GIS said anything at all about the mode, as opposed to this run
    # having reused nothing. The distinction is the whole of the P0: a container
    # built before GT-GIS-01 drops `run_mode` silently, carries forward
    # unconditionally, and returns a state with none of these keys -- so
    # `carried` is 0 because nothing was recorded, not because nothing was
    # carried, and defaulting the mode to `clean` printed "no previous values
    # were reused" over a card that had just reused them.
    #
    # `run_mode` present is the marker: GIS emits it on every summary once
    # GT-GIS-01 is in the image, including for a clean run, where the
    # `carry_forward` block is legitimately absent because the pass is skipped.
    declared = 'run_mode' in final
    # GIS reconstructs this from the field markers when a run predates GT-GIS-01
    # and recorded no provenance of its own. Passed through, because a card that
    # says "71 carried, reconstructed" is honest and one that says nothing is
    # the failure the count exists to prevent.
    derived_from = str(block.get('derived_from') or '')
    return {
        # `unknown`, never `clean`, when GIS did not say. The same word
        # `gis_service` uses for a state that predates the parameter, and for
        # the same reason: silence is not a declaration of cleanliness.
        'run_mode': str(final.get('run_mode') or 'unknown'),
        'carry_forward_mode': str(final.get('carry_forward_mode') or 'disabled'),
        'provenance_recorded': declared,
        'carried_field_count': carried,
        'parent_run_ids': parents,
        'refused_transitive_field_count': int(
            block.get('refused_transitive_field_count')
            or len(block.get('refused_transitive_field_keys') or ())
        ),
        'policy_version': block.get('policy_version'),
        'derived_from': derived_from,
    }


def _terminal_outcome(final: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the user-visible result only from terminal backend state."""

    audit = final.get('audit')
    audit = audit if isinstance(audit, Mapping) else {}
    summary = audit.get('summary')
    summary = summary if isinstance(summary, Mapping) else {}
    gates = audit.get('gates')
    gates = gates if isinstance(gates, Mapping) else {}
    checks = [item for item in audit.get('checks') or [] if isinstance(item, Mapping)]
    failed = max(
        int(summary.get('failed') or 0),
        sum(str(item.get('status') or '') == 'failed' for item in checks),
    )
    warnings = max(
        int(summary.get('warnings') or 0),
        sum(str(item.get('status') or '') == 'warning' for item in checks),
    )
    publication = str(gates.get('publication') or final.get('publication_status') or 'unknown')
    draft_rendering = str(gates.get('draft_xlsx_rendering') or final.get('render_status') or 'unknown')
    xlsx = final.get('xlsx')
    artifact_available = bool(
        isinstance(xlsx, Mapping) and str(xlsx.get('download_path') or '').startswith('/geotizer/files/')
    )
    audit_passed = failed == 0 and publication != 'blocked'
    if audit_passed and warnings:
        status = 'completed_with_warnings'
        headline = 'сформирован; финальный audit завершён с предупреждениями'
    elif audit_passed:
        status = 'completed'
        headline = 'заполнен и прошёл финальный audit'
    elif artifact_available and draft_rendering == 'allowed':
        status = 'draft_ready_publication_blocked'
        headline = 'сформирован как черновик; audit выявил ошибки, публикация заблокирована'
    else:
        status = 'blocked'
        headline = 'не завершён: terminal audit заблокировал результат'
    return {
        'status': status,
        'headline': headline,
        'audit_passed': audit_passed,
        'failed': failed,
        'warnings': warnings,
        'publication': publication,
        'draft_xlsx_rendering': draft_rendering,
        'artifact_available': artifact_available,
    }


def _error_result(
    code: str,
    message: str,
    *,
    run_id: str | None,
    details: Mapping[str, Any] | None = None,
) -> str:
    structured_details = dict(details or {})
    return json.dumps(
        {
            'status': 'geotizer_failed',
            'code': code,
            'message': message,
            'user_message': _gis_error_user_message(
                structured_details,
                fallback=message,
            ),
            'details': structured_details or None,
            'run_id': run_id or None,
            'resumable': bool(run_id),
        },
        ensure_ascii=False,
        indent=2,
    )


def _gis_error_user_message(
    details: Mapping[str, Any],
    *,
    fallback: str,
) -> str:
    resolution = details.get('project_resolution')
    if isinstance(resolution, Mapping):
        status = resolution.get('status')
        if status == 'not_found':
            return 'Связанный GIS-проект действительно не найден.'
        if status == 'ambiguous':
            return 'Найдено несколько подходящих GIS-проектов; нужен точный project_id.'

    for violation in details.get('violations') or []:
        if not isinstance(violation, Mapping):
            continue
        context = violation.get('context')
        if not isinstance(context, Mapping):
            continue
        project = context.get('gis_project')
        if isinstance(project, Mapping) and project.get('status') == 'resolved':
            project_id = project.get('project_id')
            return (
                f'Связанный GIS-проект {project_id!r} найден. '
                'Ошибка возникла на последующем этапе '
                f'{context.get("failure_stage") or "GIS processing"}.'
            )
    return fallback


# The progress lines a user reads, one entry per rendered sentence. The scheme
# is `multitask_orchestration`'s `PHRASE`, deliberately and not coincidentally:
# that tool narrates the specialist half of the same run, and a second scheme
# would mean one run answering to two switches and drifting apart at the seam.
# So the shapes match -- language at the top level, a key per sentence under it,
# `{}` fields for the only things that vary, an em dash before the diagnostic
# tail and no sentence assembled from fragments at the call site.
#
# Russian inflects, which is why the orchestration tool carries two label
# tables: «Обращаюсь к специалисту» wants the dative and «Специалист завершил»
# wants the nominative, and one string cannot be both. There is no second table
# here because nothing in these sentences is a label -- the only interpolated
# values are run ids, batch ids and integers. Anything added here that names a
# specialist must take the word from that tool's case tables; hand-inflecting it
# gives «Обращаюсь к специалист», which is the failure the two tables exist to
# prevent.
#
# Case is not the only agreement that bites, and a review of the first draft of
# this table found the other two. «запуск» appears three times in `parallel_key`
# and one of them is prepositional after «в», so the preposition needs a noun to
# govern -- «продолжаю в {run_id}» left «в» governing an opaque identifier that
# cannot inflect. And `ready` read «XLSX готов», a masculine short adjective
# agreeing with a head noun that was never written; its sibling `draft_ready`
# supplies «черновик», so the pair disagreed about whether the subject is stated
# at all. Both now name the noun.
#
# Person too: the narrator is first-person singular throughout, matching the
# tool's «Обращаюсь». The first draft said «продолжаем», which switches the run
# from «я» to «мы» in one line and reads as a different speaker.
#
# The two languages must state the same fact. A deployment switched to `en`
# is the same run reported to a different reader, not a different run, and a
# table where one side says "XLSX" and the other says «файлов» has already
# started describing two.
PHRASE: dict[str, dict[str, str]] = {
    'ru': {
        'parallel_key': (
            'Геотизер: этот ключ уже занят параллельным запуском; '
            'продолжаю в запуске {run_id}, запуск {abandoned_run_id} '
            'оставлен незавершённым'
        ),
        'profile': 'Геотизер: уточняю параметры объекта для поиска',
        'batch': 'Геотизер: пакет {n} из {total}',
        'batch_technical': 'Геотизер: пакет {n} из {total} — {batch_id} ({producer})',
        'batch_untotalled': 'Геотизер: пакет {n}',
        'batch_untotalled_technical': 'Геотизер: пакет {n} — {batch_id} ({producer})',
        'final': 'Геотизер: финальная проверка и формирование файлов',
        'draft_ready': 'Геотизер: черновик XLSX готов; публикация заблокирована',
        'ready': 'Геотизер: файл XLSX готов',
    },
    'en': {
        'parallel_key': (
            'GeoTeaser: this key is already held by a parallel run; '
            'continuing in run {run_id}, run {abandoned_run_id} left unfinished'
        ),
        'profile': 'GeoTeaser: profiling the object for the knowledge search',
        'batch': 'GeoTeaser: batch {n} of {total}',
        'batch_technical': 'GeoTeaser: batch {n} of {total} — {batch_id} ({producer})',
        'batch_untotalled': 'GeoTeaser: batch {n}',
        'batch_untotalled_technical': 'GeoTeaser: batch {n} — {batch_id} ({producer})',
        'final': 'GeoTeaser: final audit and file rendering',
        'draft_ready': 'GeoTeaser: XLSX draft is ready; publication is blocked',
        'ready': 'GeoTeaser: the XLSX file is ready',
    },
}


@dataclass(frozen=True)
class StatusSettings:
    """Which language the run narrates in, and how much of itself it shows.

    Plain data with plain defaults, because `services/` reads no valve and no
    environment. The adapter reads the orchestration tool's stored valve row --
    the same row that configures the specialist half -- and hands the pair in,
    so one switch governs the whole run. Two reads of two settings is how a
    deployment ends up announcing its specialists in Russian and its batches in
    English on the same message.

    The defaults are the orchestration tool's own valve defaults, so a caller
    that says nothing gets what an unconfigured contour already shows for the
    other half rather than a second, quieter default.
    """

    language: str = 'ru'
    verbosity: str = 'user'

    @property
    def technical(self) -> bool:
        return str(self.verbosity or 'user').strip().lower() == 'technical'

    def _lang(self) -> str:
        language = str(self.language or 'ru').strip().lower()
        return language if language in PHRASE else 'ru'

    def say(self, key: str, **fields: Any) -> str:
        return PHRASE[self._lang()][key].format(**fields)

    def batch_line(
        self,
        *,
        n: int,
        total: Any,
        batch_id: Any,
        producer: Any,
    ) -> str:
        """`пакет 3 из 8`, and what to say when the service did not send the 8.

        `batches_total` is a response field, so a GIS service older than it
        simply has none and `.get` returns `None`. Printing «из None» is the
        version skew reaching the user; dropping the denominator loses how far
        along the run is and keeps the line true, which is the right way round.
        A non-positive or unparsable total is treated as absent for the same
        reason -- «пакет 3 из 0» is not a fact about anything.

        The batch id and the producer are diagnostics, not information. The id
        is a name from a hash-pinned policy asset and the producer stopped
        meaning anything outside this repository when the mapping layer that
        gave it meaning was deleted, so neither is something a reader can act
        on -- but they are what names the batch that stalled. `technical` keeps
        them for exactly the reason the orchestration tool keeps its per-round
        tool names behind the same valve.
        """
        count = _batch_total(total)
        key = 'batch' if count else 'batch_untotalled'
        if self.technical:
            key = f'{key}_technical'
        return self.say(
            key,
            n=n,
            total=count,
            batch_id='' if batch_id is None else batch_id,
            producer='' if producer is None else producer,
        )


def _batch_total(total: Any) -> int | None:
    """The denominator, or `None` when the service did not send a usable one."""
    try:
        count = int(total)
    except (TypeError, ValueError):
        return None
    return count if count > 0 else None


async def _emit_status(emitter, description: str, *, done: bool) -> None:
    if emitter:
        await emitter(
            {
                'type': 'status',
                'data': {
                    'description': description,
                    'done': done,
                },
            }
        )


def _proxy_download_path(final: Mapping[str, Any]) -> str:
    path = xlsx_download_path(final)
    return f'/api/v1{path}'


def _proxy_source_report_paths(
    final: Mapping[str, Any],
) -> dict[str, str]:
    report = final.get('source_report')
    if not isinstance(report, Mapping):
        return {}
    expected = {
        'markdown': 'source_report.md',
        'pdf': 'source_report.pdf',
        'state': 'state.json',
    }
    # `docx` is deliberately not in `expected`. A key missing from that loop
    # abandons the whole set and returns `{}`, so a WebUI deployed ahead of a GIS
    # service that does not render the card yet would lose every report link
    # rather than one -- and it would lose them silently, because the caller
    # cannot tell an empty result from a run with no source report. The optional
    # pass below adds the docx when it is there and changes nothing when it is
    # not. It still validates the path when present: absent is a version skew,
    # malformed is a defect.
    optional = {'docx': 'geotizer.docx'}
    result = {}
    for key, filename in {**expected, **optional}.items():
        artifact = report.get(key)
        if not isinstance(artifact, Mapping):
            if key in optional:
                continue
            return {}
        path = str(artifact.get('download_path') or '')
        if not path.startswith('/geotizer/files/') or not path.endswith(f'/{filename}'):
            raise GeotizerOrchestrationError(f'Final state has an invalid {key} artifact path')
        result[key] = f'/api/v1{path}'
    return result


# `chat:message:files` renders each record through `FileItem` with `url`, `name`,
# `type` and `size` (`src/lib/components/chat/Messages/ResponseMessage.svelte`),
# and the filter admits only `image` and `file`. A URL-referenced record needs no
# storage insert -- the front end links to it.
ATTACHMENT_KIND = 'file'
ATTACHMENT_CONTENT_TYPES = {
    'geotizer.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'geotizer.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'source_report.pdf': 'application/pdf',
    'source_report.md': 'text/markdown; charset=utf-8',
    'state.json': 'application/json',
}


def attachment_files(
    proxy_path: str,
    report_paths: Mapping[str, str] | None,
    *,
    object_name: str,
) -> list[dict[str, Any]]:
    """CORE-BOUNDARY-01 action 7: the artefacts as chat attachments.

    An addition to the download API, never a replacement. Every record points at
    the same durable, authenticated path the result text links to, so a chat that
    is deleted takes the convenience and leaves the access route.

    Deciding what to attach is a rendering decision and lives here. Emitting the
    event is an effect and lives in the adapter, which is why this returns a list
    rather than sending anything.
    """
    paths = [(proxy_path, 'geotizer.xlsx')]
    # The card first, in both formats, then the evidence behind it. `docx` is
    # absent on a run finalized by a GIS service that does not render one, and
    # the `if path` below is what makes that a missing attachment rather than a
    # missing set.
    for key, filename in (
        ('docx', 'geotizer.docx'),
        ('pdf', 'source_report.pdf'),
        ('markdown', 'source_report.md'),
        ('state', 'state.json'),
    ):
        path = (report_paths or {}).get(key)
        if path:
            paths.append((path, filename))

    files: list[dict[str, Any]] = []
    for path, filename in paths:
        # The proxied path, which is what the result text links to. A raw
        # `/geotizer/files/...` is the GIS service's own path and is not
        # reachable from a browser session.
        if not str(path).startswith('/api/v1/geotizer/files/'):
            continue
        files.append(
            {
                'type': ATTACHMENT_KIND,
                'url': path,
                'name': f'{object_name} — {filename}' if object_name else filename,
                'content_type': ATTACHMENT_CONTENT_TYPES[filename],
            }
        )
    return files


__all__ = [
    'ATTACHMENT_CONTENT_TYPES',
    'PHRASE',
    'StatusSettings',
    'attachment_files',
    '_emit_status',
    '_error_result',
    '_gis_error_user_message',
    '_proxy_download_path',
    '_proxy_source_report_paths',
    '_terminal_outcome',
]


def _filled_cells(count: int) -> str:
    """«заполненная ячейка» after a numeral, in the case that numeral governs.

    Russian numerals do not take a plural the way English does: 1 governs the
    nominative singular, 2-4 the genitive singular, 5+ the genitive plural, and
    11-14 take the 5+ form regardless of their last digit. The line read «из 1
    заполненных ячеек» before this -- a hardcoded plural that is correct for
    most counts and wrong for exactly the ones a reader notices, because a card
    carrying one field is the card someone is looking at closely.
    """
    last_two = abs(count) % 100
    last = abs(count) % 10
    if 11 <= last_two <= 14:
        return 'заполненных ячеек'
    if last == 1:
        return 'заполненной ячейки'
    if 2 <= last <= 4:
        return 'заполненных ячейки'
    return 'заполненных ячеек'


def carry_forward_mode_line(carried: Mapping[str, Any], *, filled: int) -> str:
    """The `Режим:` line, in three states that must stay three.

    Rendered here rather than in the adapter, which is held to argument
    coercion, one call and the envelope: three branches of Russian prose
    about provenance is exactly the logic CORE-BOUNDARY-01 keeps out of the
    Workspace copy, and the line budget in the boundary contract is what
    noticed it drifting back in.
    """
    # The mode line is not optional and not conditional. A reader cannot tell a
    # real 40% from a padded 60% unless every card says which it is -- and it was
    # the absence of exactly this line that let a user believe a fresh `run_id`
    # meant a fresh card.
    if carried['carried_field_count']:
        donors = ', '.join(carried['parent_run_ids']) or 'неизвестного запуска'
        mode_line = (
            f'- Режим: {carried["run_mode"]} — перенесено '
            f'{carried["carried_field_count"]} из {filled} {_filled_cells(filled)}\n'
            f'  из запуска {donors}\n'
        )
        if carried['derived_from'] == 'field_markers':
            # The run recorded no provenance of its own -- it predates GT-GIS-01
            # -- so the count was rebuilt from the markers on its fields. Said
            # plainly, because a reconstructed number and a recorded one are not
            # equally trustworthy.
            mode_line += '  (счёт восстановлен по меткам полей: запуск не записал провенанс)\n'
    elif carried['provenance_recorded'] and carried['run_mode'] in ('clean', 'carry_forward'):
        mode_line = (
            f'- Режим: {carried["run_mode"]} '
            f'(значения предыдущих запусков не переносились)\n'
        )
    else:
        # The run said nothing about its mode, so neither may the card. A GIS
        # image built before GT-GIS-01 drops `run_mode` on the way in, carries
        # forward unconditionally, and returns a state with no provenance at
        # all -- the carried count is then zero because nothing was recorded,
        # not because nothing was carried. Printing the clean sentence here is
        # the one failure worse than a wrong completeness figure: a wrong number
        # can be recomputed, and a card that lies about its own provenance
        # cannot be told apart from one that does not.
        mode_line = (
            '- Режим: не записан — этот запуск не сообщил, переносились ли '
            'значения\n'
            '  (сборка GIS старше GT-GIS-01; счёт перенесённых ячеек здесь '
            'не измерен, а отсутствует)\n'
        )
    return mode_line


def reused_run_note(run_id: str, *, finalized_at: str | None) -> str:
    """What to say when the idempotency key resolved to an earlier run.

    The silence is what made this look like a limitation of the system rather
    than a property of the request: a user asked for a fresh card, got yesterday's
    id, yesterday's coverage and yesterday's link, and concluded the object could
    not be filled twice. They were describing the behaviour accurately.

    Derived from the registry having resolved to a prior run -- never from an
    inspection of what the request looked like. The same rule as the mode line:
    a card may report what happened, not what someone intended.
    """
    when = f' от {finalized_at}' if finalized_at else ''
    return (
        f'Этот прогон уже выполнялся: возвращена карточка прогона {run_id}{when}. '
        f'Новый прогон не запускался, потому что запрос совпал с предыдущим.'
    )


def already_finalized_note(run_id: str) -> str:
    """What to say when the run someone asked to resume is already done.

    `finalize()` replays a completed run's artefacts, so a `run_id` that names a
    finished run returns that card unchanged -- same id, same coverage, same
    cells. That is correct for what `run_id` is for, and it is indistinguishable
    from a re-fill that found exactly the same facts. A user who asked to build
    on the previous run sees their own card handed back and has nothing to go
    on. So the note names the two operations that are not this one, because
    "already finalized" on its own tells them what happened and not what to do.
    """
    return (
        f'Прогон {run_id} уже завершён; его карточка возвращена без изменений. '
        f'Чтобы заполнить объект заново с нуля, не передавайте run_id. '
        f'Чтобы переиспользовать его значения, укажите run_mode="carry_forward".'
    )


def preamble_note(final: Mapping[str, Any], *, fallback_run_id: str) -> str:
    """The sentence a card needs above its numbers, or nothing.

    Two ways a card can be one the reader has already seen, and they are
    different events with different recoveries: the registry resolved this
    request to an earlier run, or the caller named a `run_id` that had already
    finished. Both are derived from what happened -- a resolution and a state --
    never from an inspection of the request.

    Selected here rather than in the adapter for the reason the boundary
    contract's line budget keeps catching: choosing between two pieces of
    user-facing prose is rendering, and rendering belongs in the core.
    """
    if final.get('reused_run_from_registry'):
        return reused_run_note(
            str(final['reused_run_from_registry']),
            # GIS's own stamp, so the date is when the run finished rather than
            # when it was asked for again.
            finalized_at=str(final.get('finalized_at') or '') or None,
        )
    if final.get('resumed_run_was_already_finalized'):
        return already_finalized_note(str(final.get('run_id') or fallback_run_id))
    return ''
