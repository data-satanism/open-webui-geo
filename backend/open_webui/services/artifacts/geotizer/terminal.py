"""What the caller is handed back: the terminal envelope and its failures.

`implementation-steps.md` S1.6, second half. The terminal result is the tool's
return value -- Native Mode overwrites `message` and `chat:message:delta` with
completion snapshots, so a progress event cannot carry the outcome. Building
that value is a rendering decision, and rendering decisions belong in the core
rather than in the adapter.

`_emit_status` takes the emitter as an argument and never reaches for one, so
this module stays pure while the thing it writes to does not.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
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
    result = {}
    for key, filename in expected.items():
        artifact = report.get(key)
        if not isinstance(artifact, Mapping):
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
    for key, filename in (('pdf', 'source_report.pdf'), ('markdown', 'source_report.md'), ('state', 'state.json')):
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
    'attachment_files',
    '_emit_status',
    '_error_result',
    '_gis_error_user_message',
    '_proxy_download_path',
    '_proxy_source_report_paths',
    '_terminal_outcome',
]


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
            f'{carried["carried_field_count"]} из {filled} заполненных ячеек\n'
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
