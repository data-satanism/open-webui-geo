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
from collections.abc import Mapping, Sequence
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


def run_detail_lines(final: Mapping[str, Any], *, carried_mode_line: str) -> str:
    """The middle of the card: the lines between the audit counts and the Run ID.

    Four renderers, each of which used to cost the adapter a call, an import
    and a comment explaining itself. Composed here because the order is a
    rendering decision -- the carry-forward mode belongs beside the counts it
    changes the meaning of, the query count and the template gap are facts
    about the run rather than about the card -- and because the boundary
    contract exists to stop the adapter accumulating exactly this.

    `carried_mode_line` is passed in rather than built here: it needs
    `carry_forward_summary` and the filled count, which the adapter already has
    in hand for the completeness lines.
    """
    return (
        carried_mode_line
        + retrieval_query_line(final)
        + template_section_line(final)
    )


def card_evidence_sections(
    final: Mapping[str, Any],
    report_paths: Mapping[str, str] | None,
) -> str:
    """The tail of the card: the Word link, the disagreements, the limitations.

    The card in both formats, then the evidence behind it -- the same order
    `attachment_files` puts the five artefacts in. `GT-4` puts the
    disagreements ahead of the completeness figure and `GT-3a` requires every
    status reported separately; neither was reachable while the card never
    carried `conflicted` at all.
    """
    return (
        card_docx_link(report_paths)
        + conflict_section(final)
        + run_notes_section(final)
    )


def recovered_run_id(
    started_run: Mapping[str, Any] | None,
    exc: BaseException,
    requested_run_id: str | None,
) -> str | None:
    """The run this failure belongs to, from the three places it can be.

    A run that has reached the GIS store is resumable, and the envelope decides
    that from whether it has an id. An `AttributeError` on batch 2 produced
    `run_id: null, resumable: false` on a run whose first batch had already
    been applied -- so the crash cost a recoverable run as well as a fill, and
    the second loss is the worse one.

    Order matters. `started_run` is written by the workflow the moment the run
    exists, so it is the only source that knows about a run *this call* started
    and then lost. `exc.run_id` is what the orchestration errors carry
    themselves. `requested_run_id` is what a resume was asked to continue, and
    is last because a resume that then started a different run would be
    misreported by it.
    """
    started = (started_run or {}).get('run_id')
    return str(started or getattr(exc, 'run_id', None) or requested_run_id or '') or None


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
        'batch': 'Геотизер: пакет {n} из {total}{label}',
        'batch_technical': 'Геотизер: пакет {n} из {total}{label} — {batch_id} ({producer})',
        'batch_untotalled': 'Геотизер: пакет {n}{label}',
        'batch_untotalled_technical': 'Геотизер: пакет {n}{label} — {batch_id} ({producer})',
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
        'batch': 'GeoTeaser: batch {n} of {total}{label}',
        'batch_technical': 'GeoTeaser: batch {n} of {total}{label} — {batch_id} ({producer})',
        'batch_untotalled': 'GeoTeaser: batch {n}{label}',
        'batch_untotalled_technical': 'GeoTeaser: batch {n}{label} — {batch_id} ({producer})',
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
        label: Any = None,
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

        `label` is the opposite: it is the one part of the plan a reader can
        act on, and the line used to throw it away. It arrives on `next_batch`
        from `assignment_policy.v3`, so a service older than that sends none
        and the line is the ordinal it always was -- absent, not «— None».

        The label is the asset's own text and is not translated for the `en`
        table. It names a section of a Russian CPR template; rendering it in
        English would name a section that does not exist.
        """
        count = _batch_total(total)
        key = 'batch' if count else 'batch_untotalled'
        if self.technical:
            key = f'{key}_technical'
        described = str(label or '').strip()
        return self.say(
            key,
            n=n,
            total=count,
            label=f' — {described}' if described else '',
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
    'card_docx_link',
    'conflict_section',
    'run_notes_section',
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


def completeness_lines(final: Mapping[str, Any]) -> str:
    """The five status lines, and what `filled` is made of.

    Every cell of a run is in exactly one of five states, and the card printed
    three of them. On run `6976094d` that is 197 filled and 94 not_found
    stated, 25 conflicted and 35 review cells left to `state.json`, and a
    reader who added the printed numbers got 291 of 351 with no indication
    that 60 cells were missing from the arithmetic.

    Two of the five are new here rather than merely unprinted.

      - `agent_contract_failed` is split out of `requires_expert_review`. All
        35 of that run's review cells were failed agent calls, not geological
        questions, and «Требует экспертной проверки: 35» named the wrong
        person for every one of them. A deployment that has not yet learned
        the status reports 0 for it and the old total under review, which is
        the previous card exactly -- so the skew degrades to the old reading
        rather than to a wrong one.

      - `filled` never appears alone. 197 filled is 161 observations and 36
        derived values, and the workbook already says so in every derived
        cell. If the service did not send `value_origins` the parenthetical is
        omitted rather than guessed -- the same version-skew rule
        `card_docx_link` follows, for the same reason.
    """
    counts = final.get('counts') or (final.get('audit') or {}).get('completeness') or {}
    filled = int(counts.get('filled') or 0)
    lines = [f'- Заполнено: {filled}{_origin_suffix(final, filled=filled)}\n']
    for label, key in (
        ('Расхождения между источниками', 'conflicted'),
        ('Сбой агента — данные не собраны', 'agent_contract_failed'),
        ('Требует экспертной проверки', 'requires_expert_review'),
        ('Не найдено', 'not_found'),
    ):
        lines.append(f'- {label}: {int(counts.get(key) or 0)}\n')
    return ''.join(lines)


def _origin_suffix(final: Mapping[str, Any], *, filled: int) -> str:
    """«(из них расчётных: 29, по аналогу: 7)», or nothing at all.

    Analogue is named beside calculated instead of added to it. The renderer
    gives them different prefixes -- «РАСЧЕТНОЕ ЗНАЧЕНИЕ» and «РАСЧЕТНОЕ
    ЗНАЧЕНИЕ (ПО АНАЛОГУ)» -- and seven cells carried by an analogy with
    another deposit are not the same claim as twenty-nine carried by a
    formula. Collapsing them here would make the card disagree with the
    workbook it links to.
    """
    origins = final.get('value_origins')
    if not isinstance(origins, Mapping):
        return ''
    calculated = int(origins.get('calculated') or 0)
    analogue = int(origins.get('analogue') or 0)
    if not calculated and not analogue:
        return ''
    parts = []
    if calculated:
        parts.append(f'расчётных: {calculated}')
    if analogue:
        parts.append(f'по аналогу: {analogue}')
    return f' (из них {", ".join(parts)})'


#: How many disagreements the card prints before it defers to `state.json`.
#: `geoteaser-fill` already tells the reader the printed list is capped and the
#: count above it is the real total, so the cap is the documented behaviour and
#: the total must always be stated with it.
MAX_PRINTED_CONFLICTS = 10


def conflict_section(final: Mapping[str, Any]) -> str:
    """The «Расхождения между источниками» list, or nothing.

    Three documents told the reader to look at this section and nothing
    produced it. `GT-4` puts it first, ahead of the completeness figure;
    `GT-3a` requires all four statuses reported separately; `geoteaser-fill`
    says a card with 183 filled, 25 conflicted and 35 under review has evidence
    for 243 cells. The result markdown printed filled, not_found and
    requires_expert_review -- on run `6056e157` that is 326 of 351 cells, with
    the 25 conflicted ones absent from the only artefact the user reads.

    An orchestrator cannot follow `GT-3a` from a card that never carries the
    number, and it cannot follow `INV-6` -- report both values with both
    sources, never pick one -- from a list of field names. So the count is
    stated whether or not the service sent the detail, and each printed
    disagreement carries both sides when it did.
    """
    counts = final.get('counts') or (final.get('audit') or {}).get('completeness') or {}
    total = int(counts.get('conflicted') or 0)
    if not total:
        return ''
    lines = [f'\n\n**Расхождения между источниками: {total}**\n']
    conflicts = [item for item in (final.get('conflicts') or []) if isinstance(item, Mapping)]
    for item in conflicts[:MAX_PRINTED_CONFLICTS]:
        lines.append(f'- {_conflict_line(item)}\n')
    if not conflicts:
        # The service is older than the detail, or sent none. Say which cells
        # rather than implying the card has no way to show them.
        lines.append('- Значения сторон — в `state.json` (`source_locator.candidates`).\n')
    elif total > len(conflicts[:MAX_PRINTED_CONFLICTS]):
        shown = len(conflicts[:MAX_PRINTED_CONFLICTS])
        lines.append(f'- Показаны {shown} из {total}; остальные — в `state.json`.\n')
    return ''.join(lines)


def _conflict_line(item: Mapping[str, Any]) -> str:
    """One disagreement: what it is about, and what each side said."""
    label = ' / '.join(
        part
        for part in (str(item.get('element') or ''), str(item.get('attribute_name') or ''))
        if part
    ) or str(item.get('field_key') or '')
    sides = [
        candidate
        for candidate in (item.get('candidates') or [])
        if isinstance(candidate, Mapping)
    ]
    if not sides:
        return f'{label} (`{item.get("field_key")}`)'
    rendered = ' ↔ '.join(_conflict_side(side) for side in sides)
    return f'{label} (`{item.get("field_key")}`): {rendered}'


def _conflict_side(candidate: Mapping[str, Any]) -> str:
    """A value with the source that gave it. Never one without the other --
    two values and two sources in separate lists cannot be paired up by a
    reader, and pairing them is the whole point of `OUT-3`."""
    value = candidate.get('value')
    unit = str(candidate.get('unit') or '').strip()
    shown = '—' if value in (None, '') else str(value)
    if unit:
        shown = f'{shown} {unit}'
    source = str(candidate.get('source_ref') or '').strip()
    return f'«{shown}» [{source}]' if source else f'«{shown}»'


def card_docx_link(report_paths: Mapping[str, str] | None) -> str:
    """The Word rendering of the card, as a Markdown link, or nothing.

    **Why `.get` and not `[...]`.** `_proxy_source_report_paths` keeps `docx`
    out of its required set on purpose: a key missing from that loop abandons
    the whole set, so a WebUI deployed ahead of a GIS service that renders no
    card would lose every report link rather than one. Reading it back with a
    subscript here would reintroduce exactly that, one layer up — a version
    skew becomes a `KeyError` and the run's result is lost after the card was
    built. Absent is a version skew; malformed was already refused upstream.

    **Why this label, and why it changed.** It read «Скачать карту GeoTeaser
    DOCX», and the reason given was that the document said three times over
    that it was a card — its title, its filename, and a second paragraph
    reading «Это не Отчёт Компетентного лица (CPR)». Two of those three have
    since changed. The template now defines the structure and the DOCX is the
    deliverable built against it; there is no other CPR artefact, since
    `cpr_readiness.docx` has no runtime caller; and the denial is gone from the
    document because it was the one sentence in it that was false. It had a
    cost: the orchestration agent read the file as a card and told a user no
    CPR report had been produced when one had.

    So the link now names it, and names it a draft. `черновик` is carried here
    rather than left to the watermark — unlike before — because «Скачать отчёт
    CPR» without it is the one label that could be forwarded as a
    certification, and a link is what gets forwarded.

    A-44 is still open and still not settled here: `CPR Readiness` versus
    `Draft CPR` is the *readiness* document's title, and this is not that
    document. `Отчёт о готовности к CPR` appears nowhere in this label.

    **Why it lives here.** Choosing between two pieces of user-facing prose is
    rendering, and rendering belongs in the core — the same reason
    `preamble_note` and `carry_forward_mode_line` are here rather than in the
    adapter, and the reason the adapter's line budget keeps catching the
    alternative.
    """
    path = (report_paths or {}).get('docx')
    if not path:
        return ''
    # No parentheses in the label. `[… (CPR) DOCX](path)` is legal Markdown and
    # a naive `split('(')` on it returns `CPR) DOCX]` instead of the URL --
    # which is what one of this file's own tests did, and what any consumer
    # that parses links by hand will do. The label costs nothing to keep
    # bracket-free.
    return f'\n\n[Скачать черновик CPR-отчёта DOCX]({path})'


def run_notes_section(final: Mapping[str, Any]) -> str:
    """«Ограничения этого запуска» — what this code repaired or refused.

    Every repair the pipeline makes to an owner envelope was already being
    recorded: `normalize_source_inventory` rebuilding source metadata the owner
    wrote under the wrong schema, and `coerce_contradictory_patch_fields`
    overriding a status that contradicted its own value. Both appended to a
    list nothing read, while both docstrings said the notes "are surfaced as
    run degradations".

    That is the condition those repairs were granted on. A card built on source
    metadata this code reconstructed, or carrying a `not_found` the owner sent
    as `filled`, is not the same card as one the owner produced -- and a reader
    comparing two runs has no way to infer it. A silent repair is how a card
    comes to rest on a value nobody chose.

    `geoteaser-fill` already tells the reader to look for this section and to
    surface it rather than bury it, because these reduce recall across the
    whole card.
    """
    notes = [str(note) for note in (final.get('run_notes') or ()) if str(note).strip()]
    if not notes:
        return ''
    lines = ['\n\n**Ограничения этого запуска**\n']
    lines.extend(f'- {note}\n' for note in notes)
    return ''.join(lines)


def template_section_line(final: Mapping[str, Any]) -> str:
    """How much of the CPR template the card cannot reach, or nothing.

    On run `dbda3535` 25 of the template's 33 sections had no card block, and
    the only way to learn that was to open the DOCX -- where it was stated
    twenty-five times, once under each of them. It is a fact about the run and
    belongs beside the statuses.

    It is not a coverage gap in the batch plan: all 107 spreadsheet rows are
    owned by a batch. It is the section-to-field mapping, which stands at 51 of
    351 fields, and extending it is a Domain Reviewer decision rather than an
    engineering one -- so the line says what is missing and does not imply that
    running something again would fix it.

    Silent when the service sends nothing, and silent when it says it could not
    read the template: `readable: false` means unknown, and «0 разделов» would
    turn "we could not tell" into "there is no gap".
    """
    sections = final.get('template_sections')
    if not isinstance(sections, Mapping) or not sections.get('readable'):
        return ''
    count = sections.get('unmapped_count')
    if not isinstance(count, int) or count <= 0:
        return ''
    return (
        f'- Разделов шаблона без сопоставления с картой: {count} '
        '(расширение сопоставления — решение Domain Reviewer)\n'
    )


def retrieval_query_line(final: Mapping[str, Any]) -> str:
    """How many searches this run recorded, and nothing when it recorded none.

    `record_retrieval_queries` exists so two runs can be compared by what they
    searched for. The log is built and attached to the terminal payload, and
    the terminal payload is not persisted -- `state.json` is written by the GIS
    service from the patches, so the log cannot appear there by construction.
    Asked of run `6976094d` whether the queries were written or missing, the
    honest answer was that `state.json` cannot distinguish a run that planned
    no searches from a run whose log was never kept. Neither could the card.

    One number settles it. It is not the log -- 400 queries do not belong in a
    chat message -- it is the count, which is what tells a later reader whether
    there is a log to go looking for.
    """
    queries = final.get('retrieval_queries')
    if not isinstance(queries, Sequence) or isinstance(queries, (str, bytes)):
        return ''
    recorded = [item for item in queries if isinstance(item, Mapping)]
    truncated = any(item.get('truncated') for item in recorded)
    total = len([item for item in recorded if not item.get('truncated')])
    if not total:
        return ''
    suffix = ' (записаны не все — см. `truncated`)' if truncated else ''
    return f'- Поисковых запросов записано: {total}{suffix}\n'
