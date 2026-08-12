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


__all__ = [
    '_emit_status',
    '_error_result',
    '_gis_error_user_message',
    '_proxy_download_path',
    '_proxy_source_report_paths',
    '_terminal_outcome',
]
