"""What the caller is handed back: the terminal envelope, its failures, and the status lines.

Everything here renders from values passed in; `_emit_status` takes the
emitter as an argument. The wording of every status line lives in `PHRASE`
and `StatusSettings`.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from ...geotizer.errors import GeotizerOrchestrationError
from .owner_envelope import xlsx_download_path


def carry_forward_summary(final: Mapping[str, Any]) -> dict[str, Any]:
    """What of this card came from an earlier run, from terminal state alone.

    `run_mode` is `unknown` when GIS did not send one, and `provenance_recorded`
    is whether `run_mode` is present at all. `derived_from` is passed through, and
    is `field_markers` when GIS reconstructed the carried count from field markers.
    """
    block = final.get('carry_forward')
    block = block if isinstance(block, Mapping) else {}
    parents = [str(run) for run in block.get('parent_run_ids') or () if str(run)]
    carried = int(block.get('carried_field_count') or len(block.get('carried_field_keys') or ()))
    declared = 'run_mode' in final
    derived_from = str(block.get('derived_from') or '')
    return {
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
    """The lines between the audit counts and the Run ID.

    `carried_mode_line` (from `carry_forward_mode_line`), then
    `retrieval_query_line`, then `template_section_line`.
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
    """The tail of the card: the Word link, the disagreements, the run notes, the run log link."""
    return (
        card_docx_link(report_paths)
        + conflict_section(final)
        + run_notes_section(final)
        + run_log_link(report_paths)
    )


def run_log_link(report_paths: Mapping[str, str] | None) -> str:
    """The run log (`run_log.json`) as a Markdown link, or '' when `report_paths` has none.

    Labelled «Журнал запуска».
    """
    path = (report_paths or {}).get('run_log')
    if not path:
        return ''
    return f'\n\n[Скачать журнал запуска JSON]({path})'


def recovered_run_id(
    started_run: Mapping[str, Any] | None,
    exc: BaseException,
    requested_run_id: str | None,
) -> str | None:
    """The run this failure belongs to, or None.

    Taken from `started_run['run_id']` first, then `exc.run_id`, then
    `requested_run_id`.
    """
    started = (started_run or {}).get('run_id')
    return str(started or getattr(exc, 'run_id', None) or requested_run_id or '') or None


MAX_TRACEBACK_LINES = 40


def failure_details(exc: BaseException) -> dict[str, Any] | None:
    """What `details` should carry for a failure, from the exception alone.

    The exception's own `details` mapping when it has one; None for any other
    `GeotizerOrchestrationError`; otherwise a crash report with `escaped: True`,
    `exception_type`, the last `MAX_TRACEBACK_LINES` traceback lines and
    `traceback_lines_dropped`.
    """
    own = getattr(exc, 'details', None)
    if isinstance(own, Mapping):
        return dict(own)
    if isinstance(exc, GeotizerOrchestrationError):
        return None
    lines = [
        line.rstrip()
        for chunk in traceback.format_exception(type(exc), exc, exc.__traceback__)
        for line in chunk.splitlines()
        if line.strip()
    ]
    return {
        'escaped': True,
        'exception_type': type(exc).__name__,
        'traceback': lines[-MAX_TRACEBACK_LINES:],
        'traceback_lines_dropped': max(0, len(lines) - MAX_TRACEBACK_LINES),
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

    if isinstance(details.get('licence_scope'), Mapping):
        relayed = str(details.get('message') or '').strip()
        if relayed:
            return relayed

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

    if details.get('identity_field') or details.get('layer_id'):
        searched = details.get('identity_field')
        return (
            f'Лицензия {details.get("requested_licence_id") or "(не указана)"} '
            + (
                f'не найдена в поле {searched} слоя {details.get("layer_id")}.'
                if searched
                else f'не найдена: слой {details.get("layer_id")} не объявляет '
                'поля с номером лицензии.'
            )
            + ' Проверьте номер или укажите licence_layer_id; повторный '
            'запуск с тем же номером даст тот же результат.'
        )

    if _looks_like_serialised(fallback):
        code = str(details.get('code') or '').strip()
        return (
            'GIS-этап заполнения не удался'
            + (f' ({code})' if code else '')
            + '. Подробности — в поле details; это не сбой доступности, '
            'и повторный запуск без изменения запроса даст тот же результат.'
        )
    return fallback


def _looks_like_serialised(text: str) -> bool:
    """Whether this string looks like a serialised JSON object or array rather than a sentence."""
    stripped = (text or '').strip()
    return stripped.startswith(('{', '[')) and stripped.endswith(('}', ']'))


PHRASE: dict[str, dict[str, str]] = {
    'ru': {
        'parallel_key': (
            '{subject}: этот ключ уже занят параллельным запуском; '
            'продолжаю в запуске {run_id}, запуск {abandoned_run_id} '
            'оставлен незавершённым'
        ),
        'run_started': '{subject}: запуск {run_id} — {object_name}',
        'run_started_named': '{subject}: запуск {run_id}',
        'profile': '{subject}: уточняю параметры объекта для поиска',
        'batch': '{subject}: пакет {n} из {total}{label}',
        'batch_technical': '{subject}: пакет {n} из {total}{label} — {batch_id} ({producer})',
        'batch_untotalled': '{subject}: пакет {n}{label}',
        'batch_untotalled_technical': '{subject}: пакет {n}{label} — {batch_id} ({producer})',
        'final': '{subject}: финальная проверка и формирование файлов',
        'draft_ready': '{subject}: черновик XLSX готов; публикация заблокирована',
        'ready': '{subject}: файл XLSX готов',
        'area_progress': (
            'Площадь: {total} {members} · заполняется {running} · '
            'готово {filled} · ожидают {waiting}'
        ),
        'area_progress_failed': 'не удалось {failed}',
        'area_progress_not_attempted': 'не начинались {missed}',
    },
    'en': {
        'parallel_key': (
            '{subject}: this key is already held by a parallel run; '
            'continuing in run {run_id}, run {abandoned_run_id} left unfinished'
        ),
        'run_started': '{subject}: run {run_id} started — {object_name}',
        'run_started_named': '{subject}: run {run_id} started',
        'profile': '{subject}: profiling the object for the knowledge search',
        'batch': '{subject}: batch {n} of {total}{label}',
        'batch_technical': '{subject}: batch {n} of {total}{label} — {batch_id} ({producer})',
        'batch_untotalled': '{subject}: batch {n}{label}',
        'batch_untotalled_technical': '{subject}: batch {n}{label} — {batch_id} ({producer})',
        'final': '{subject}: final audit and file rendering',
        'draft_ready': '{subject}: XLSX draft is ready; publication is blocked',
        'ready': '{subject}: the XLSX file is ready',
        'area_progress': (
            'Area: {total} {members} · filling {running} · '
            'done {filled} · waiting {waiting}'
        ),
        'area_progress_failed': 'failed {failed}',
        'area_progress_not_attempted': 'not started {missed}',
    },
}


SUBJECT_DEFAULT = {'ru': 'Геотизер', 'en': 'GeoTeaser'}


def member_subject(*, object_name: Any = None, licence_id: Any = None) -> str:
    """What an area member's own status lines are addressed from.

    `name (licence)` when both are known and differ, otherwise whichever is
    present. Neither part is translated.
    """
    name = str(object_name or '').strip()
    licence = str(licence_id or '').strip()
    if name and licence and name != licence:
        return f'{name} ({licence})'
    return licence or name


@dataclass(frozen=True)
class StatusSettings:
    """Which language the run narrates in, how much of itself it shows, and about whom.

    The adapter builds it from the orchestration tool's stored valve row. The
    defaults, `ru` and `user`, match that tool's valve defaults.
    """

    language: str = 'ru'
    verbosity: str = 'user'
    subject: str = ''

    @property
    def technical(self) -> bool:
        return str(self.verbosity or 'user').strip().lower() == 'technical'

    def _lang(self) -> str:
        language = str(self.language or 'ru').strip().lower()
        return language if language in PHRASE else 'ru'

    @property
    def subject_name(self) -> str:
        """The member this line is about, or the product itself."""
        return str(self.subject or '').strip() or SUBJECT_DEFAULT[self._lang()]

    def say(self, key: str, **fields: Any) -> str:
        return PHRASE[self._lang()][key].format(subject=self.subject_name, **fields)

    def about(self, subject: str) -> 'StatusSettings':
        """A copy of these settings with `subject` replaced; the original is not changed."""
        return replace(self, subject=str(subject or '').strip())

    def members_word(self, count: int) -> str:
        """«участник», «участника», «участников» by count; `member` or `members` in English.

        Russian counts ending in 11-14 take the many form.
        """
        if self._lang() != 'ru':
            return 'member' if count == 1 else 'members'
        tail_two, tail = count % 100, count % 10
        if 11 <= tail_two <= 14:
            return 'участников'
        if tail == 1:
            return 'участник'
        if tail in (2, 3, 4):
            return 'участника'
        return 'участников'

    def batch_line(
        self,
        *,
        n: int,
        total: Any,
        batch_id: Any,
        producer: Any,
        label: Any = None,
    ) -> str:
        """The batch progress line, `пакет 3 из 8` or its English form.

        A missing, non-positive or unparsable `total` drops the denominator. `label`
        is appended after an em dash when present and is never translated.
        Verbosity `technical` appends `batch_id` and `producer`.
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
    run_log = final.get('run_log')
    if isinstance(run_log, Mapping):
        path = str(run_log.get('download_path') or '')
        if not path.startswith('/geotizer/files/') or not path.endswith('/run_log.json'):
            raise GeotizerOrchestrationError('Final state has an invalid run_log artifact path')
        result['run_log'] = f'/api/v1{path}'
    return result


ATTACHMENT_KIND = 'file'
ATTACHMENT_CONTENT_TYPES = {
    'geotizer.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'geotizer.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'source_report.pdf': 'application/pdf',
    'source_report.md': 'text/markdown; charset=utf-8',
    'state.json': 'application/json',
    'run_log.json': 'application/json',
    'summary.md': 'text/markdown; charset=utf-8',
}


def attachment_files(
    proxy_path: str,
    report_paths: Mapping[str, str] | None,
    *,
    object_name: str,
) -> list[dict[str, Any]]:
    """The artefacts as `chat:message:files` records.

    The XLSX first, then `docx`, `pdf`, `markdown`, `state` and `run_log` from
    `report_paths` when present. Only paths under `/api/v1/geotizer/files/` are
    included; each record points at the same authenticated path the result text
    links to. Returns the records; emitting the event is the caller's.
    """
    paths = [(proxy_path, 'geotizer.xlsx')]
    for key, filename in (
        ('docx', 'geotizer.docx'),
        ('pdf', 'source_report.pdf'),
        ('markdown', 'source_report.md'),
        ('state', 'state.json'),
        ('run_log', 'run_log.json'),
    ):
        path = (report_paths or {}).get(key)
        if path:
            paths.append((path, filename))

    files: list[dict[str, Any]] = []
    for path, filename in paths:
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
    'run_log_link',
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
    """«заполненная ячейка» in the case and number a preceding numeral governs."""
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
    """The `Режим:` line, in one of three states.

    Carried values: how many, from which runs, and a note when the count was
    reconstructed from field markers. No carried values with a recorded `clean` or
    `carry_forward` mode: nothing was reused. Anything else: the mode was not
    recorded.
    """
    if carried['carried_field_count']:
        donors = ', '.join(carried['parent_run_ids']) or 'неизвестного запуска'
        mode_line = (
            f'- Режим: {carried["run_mode"]} — перенесено '
            f'{carried["carried_field_count"]} из {filled} {_filled_cells(filled)}\n'
            f'  из запуска {donors}\n'
        )
        if carried['derived_from'] == 'field_markers':
            mode_line += '  (счёт восстановлен по меткам полей: запуск не записал провенанс)\n'
    elif carried['provenance_recorded'] and carried['run_mode'] in ('clean', 'carry_forward'):
        mode_line = (
            f'- Режим: {carried["run_mode"]} '
            f'(значения предыдущих запусков не переносились)\n'
        )
    else:
        mode_line = (
            '- Режим: не записан — этот запуск не сообщил, переносились ли '
            'значения\n'
            '  (сборка GIS старше GT-GIS-01; счёт перенесённых ячеек здесь '
            'не измерен, а отсутствует)\n'
        )
    return mode_line


def reused_run_note(run_id: str, *, finalized_at: str | None) -> str:
    """The note for a request the run registry resolved to an earlier run."""
    when = f' от {finalized_at}' if finalized_at else ''
    return (
        f'Этот прогон уже выполнялся: возвращена карточка прогона {run_id}{when}. '
        f'Новый прогон не запускался, потому что запрос совпал с предыдущим.'
    )


def already_finalized_note(run_id: str) -> str:
    """The note for a `run_id` that names an already finalized run.

    Names the two alternatives: omit `run_id` to fill from scratch, or pass
    `run_mode="carry_forward"` to reuse its values.
    """
    return (
        f'Прогон {run_id} уже завершён; его карточка возвращена без изменений. '
        f'Чтобы заполнить объект заново с нуля, не передавайте run_id. '
        f'Чтобы переиспользовать его значения, укажите run_mode="carry_forward".'
    )


def preamble_note(final: Mapping[str, Any], *, fallback_run_id: str) -> str:
    """The sentence a card needs above its numbers, or ''.

    `reused_run_note` when `reused_run_from_registry` is set, otherwise
    `already_finalized_note` when `resumed_run_was_already_finalized` is set.
    """
    if final.get('reused_run_from_registry'):
        return reused_run_note(
            str(final['reused_run_from_registry']),
            finalized_at=str(final.get('finalized_at') or '') or None,
        )
    if final.get('resumed_run_was_already_finalized'):
        return already_finalized_note(str(final.get('run_id') or fallback_run_id))
    return ''


FILL_TARGET_LABEL = 'Заполненность'

TARGET_ON_BASIC = 'basic'


def fill_percent(final: Mapping[str, Any], which: str, filled: Any, of: Any) -> float | None:
    """The service's `fill_quality[which]`, or `filled / of * 100` rounded to one decimal, or None.

    `which` is `strict_fill_percent` or `basic_fill_percent`. None when neither
    the service's figure nor both counts are available.
    """
    percent = (final.get('fill_quality') or {}).get(which)
    if percent is not None:
        return percent
    return round(filled / of * 100, 1) if filled is not None and of else None


def target_line(final: Mapping[str, Any]) -> str:
    """One line: the basic fill percentage against the target the record reports.

    The target and the verdict come from `fill_quality` (`target_fill_rate`,
    `target_met`). The verdict is withheld when no target was reported, when
    `target_measured_on` is not `basic`, or when `target_met` is absent.
    """
    quality = final.get('fill_quality') or {}
    measured_on = quality.get('target_measured_on')
    rate = quality.get('target_fill_rate')
    target = f'{rate * 100:g}%' if isinstance(rate, (int, float)) else None
    completeness = (final.get('audit') or {}).get('completeness') or {}
    percent = fill_percent(
        final,
        'basic_fill_percent',
        (completeness.get('basic') or {}).get('filled'),
        (completeness.get('basic') or {}).get('of'),
    )
    if percent is None:
        return (
            f'- {FILL_TARGET_LABEL}: не определена — прогон не сообщил ни одной '
            f'из двух цифр\n'
        )
    if target is None:
        return f'- {FILL_TARGET_LABEL}: {percent}% (цель не сообщена)\n'
    if measured_on != TARGET_ON_BASIC:
        return (
            f'- {FILL_TARGET_LABEL}: {percent}% '
            f'(цель {target}: сборка этого прогона считала цель по строгой '
            f'цифре, поэтому её вердикт к этому числу не относится)\n'
        )
    met = quality.get('target_met')
    if met is None:
        return f'- {FILL_TARGET_LABEL}: {percent}% (цель {target}: не определено)\n'
    verdict = 'достигнута' if met else 'не достигнута'
    return f'- {FILL_TARGET_LABEL}: {percent}% (цель {target}: {verdict})\n'


def completeness_lines(final: Mapping[str, Any]) -> str:
    """The fill line, the stage and run-variance lines, and the four other status counts.

    The fill line states the strict and basic figures (from `audit.completeness`)
    with their percentages when both are present, a single `filled` count
    otherwise, and «не определено» when the card has no cells. Then
    `_stage_scope_lines`, `_run_variance_lines`, and the counts for `conflicted`,
    `agent_contract_failed`, `requires_expert_review` and `not_found`.
    """
    counts = final.get('counts') or (final.get('audit') or {}).get('completeness') or {}
    filled = int(counts.get('filled') or 0)
    completeness = (final.get('audit') or {}).get('completeness') or {}
    strict = (completeness.get('strict') or {}).get('filled')
    basic = (completeness.get('basic') or {}).get('filled')
    total = (completeness.get('strict') or {}).get('of')
    suffix = _origin_suffix(final, filled=filled)
    if total == 0:
        lines = ['- Заполнено: не определено — карточка не содержит ни одной ячейки\n']
    elif strict is not None and basic is not None and total is not None:
        strict_percent = fill_percent(final, 'strict_fill_percent', strict, total)
        basic_percent = fill_percent(final, 'basic_fill_percent', basic, total)
        if strict_percent is None or basic_percent is None:
            lines = [
                f'- Заполнено: {strict} из {total} (строго) · '
                f'{basic} из {total} (с учётом расхождений){suffix}\n'
            ]
        else:
            lines = [
                f'- Заполнено: {strict} из {total} ({strict_percent}%, строго) · '
                f'{basic} из {total} ({basic_percent}%, с учётом расхождений){suffix}\n'
            ]
    else:
        lines = [f'- Заполнено: {filled}{suffix}\n']
    lines.extend(_stage_scope_lines(final))
    lines.extend(_run_variance_lines(final))
    for label, key in (
        ('Расхождения между источниками', 'conflicted'),
        ('Сбой агента — данные не собраны', 'agent_contract_failed'),
        ('Требует экспертной проверки', 'requires_expert_review'),
        ('Не найдено', 'not_found'),
    ):
        lines.append(f'- {label}: {int(counts.get(key) or 0)}\n')
    return ''.join(lines)


def _stage_scope_lines(final: Mapping[str, Any]) -> list[str]:
    """The in-stage fill line and the out-of-stage count, or nothing.

    Both lines or none: omitted when the service sent no `stage_scope`.
    """
    scope = final.get('stage_scope') or (
        final.get('counts') or (final.get('audit') or {}).get('completeness') or {}
    ).get('stage_scope')
    if not isinstance(scope, Mapping):
        return []
    inside = scope.get('in_stage')
    outside = scope.get('out_of_stage')
    if not isinstance(inside, Mapping) or not isinstance(outside, Mapping):
        return []
    sections = ', '.join(str(number) for number in (scope.get('out_of_stage_sections') or ()))
    excluded = f'- Вне стадии: {int(outside.get("required") or 0)} ячеек'
    if sections:
        excluded += f' (разделы {sections} — не требуются для отчёта о поисках)'
    return [
        f'- Заполнено на этой стадии: {int(inside.get("filled") or 0)} '
        f'из {int(inside.get("required") or 0)} применимых\n',
        excluded + '\n',
    ]


def _run_variance_figures(band: Mapping[str, Any]) -> str:
    low, high = (list(band.get('filled_range') or []) + [None, None])[:2]
    cells = band.get('cells') or {}
    return (
        f'{low}\u2013{high} заполнено; '
        f'стабильно {int(cells.get("stable_filled") or 0)}, '
        f'нестабильно {int(cells.get("unstable") or 0)}, '
        f'недостижимо {int(cells.get("never_filled") or 0)}'
    )


def _run_variance_lines(final: Mapping[str, Any]) -> list[str]:
    """The run-variance line for this build, or nothing.

    One of four states from `run_variance.state`: `measured` (the band and its
    record), `stale` (the band from another build and the repositories this build
    differs in), `unattributable` (this build could not be read), or `unmeasured`.
    Nothing when the service sent no `run_variance`.
    """
    band = final.get('run_variance') or (final.get('audit') or {}).get('run_variance')
    if not isinstance(band, Mapping):
        return []
    state = str(band.get('state') or ('measured' if band.get('measured') else 'unmeasured'))
    if state == 'measured':
        runs = len(band.get('reference_runs') or ())
        line = f'- По {runs} прогонам этой сборки: {_run_variance_figures(band)}\n'
        record = band.get('record')
        if record:
            line += f'- Запись измерения: {record}\n'
        return [line]
    if state == 'stale':
        runs = len(band.get('reference_runs') or ())
        differs = ', '.join(
            str(item.get('repository')) for item in band.get('differs_in') or ()
        )
        line = (
            f'- Полоса измерена на другой сборке: по {runs} прогонам той сборки '
            f'{_run_variance_figures(band)}\n'
        )
        if differs:
            line += f'- Эта сборка отличается: {differs}\n'
        record = band.get('record')
        if record:
            line += f'- Запись измерения: {record}\n'
        return [line]
    if state == 'unattributable':
        return [
            '- Сборку этого прогона прочитать не удалось: полоса ни подтверждена, '
            'ни опровергнута, число выше — одна выборка\n'
        ]
    return [
        '- Диапазон заполнения для этой сборки не измерен: число выше — '
        'одна выборка, а не измерение\n'
    ]


def _origin_suffix(final: Mapping[str, Any], *, filled: int) -> str:
    """«(из них расчётных: N, по аналогу: M)», or '' when `value_origins` is absent or zero.

    Analogue values are counted separately from calculated values.
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


MAX_PRINTED_CONFLICTS = 10


def conflict_section(final: Mapping[str, Any]) -> str:
    """The «Расхождения между источниками» list, or '' when nothing is conflicted.

    States the conflicted total, then at most `MAX_PRINTED_CONFLICTS`
    disagreements with each side's value and source, pointing to `state.json` for
    the rest or when the service sent no detail.
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
    """A candidate value with its unit and the source that gave it."""
    value = candidate.get('value')
    unit = str(candidate.get('unit') or '').strip()
    shown = '—' if value in (None, '') else str(value)
    if unit:
        shown = f'{shown} {unit}'
    source = str(candidate.get('source_ref') or '').strip()
    return f'«{shown}» [{source}]' if source else f'«{shown}»'


def card_docx_link(report_paths: Mapping[str, str] | None) -> str:
    """The Word rendering of the card, as a Markdown link, or '' when `report_paths` has no `docx`.

    Labelled as a draft CPR report. The label contains no parentheses.
    """
    path = (report_paths or {}).get('docx')
    if not path:
        return ''
    return f'\n\n[Скачать черновик CPR-отчёта DOCX]({path})'


def run_notes_section(final: Mapping[str, Any]) -> str:
    """«Ограничения этого запуска»: the run's `run_notes`, or '' when there are none."""
    notes = [str(note) for note in (final.get('run_notes') or ()) if str(note).strip()]
    if not notes:
        return ''
    lines = ['\n\n**Ограничения этого запуска**\n']
    lines.extend(f'- {note}\n' for note in notes)
    return ''.join(lines)


def template_section_line(final: Mapping[str, Any]) -> str:
    """How many CPR template sections have no card mapping, or ''.

    '' when the service sent no `template_sections`, reported it unreadable, or
    reported no unmapped section.
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
    """How many retrieval queries this run recorded, or '' when it recorded none.

    Truncated entries are not counted and mark the line as incomplete.
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
