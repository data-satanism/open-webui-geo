"""Build the ontology induction Workspace Tool shim and its manifest from the built-in's signature.

The shim's method takes the built-in's positional parameters, its docstring keeps the built-in's
description and those parameters, and each keyword-only parameter becomes a valve named in upper
case with the built-in's default. Nothing else is written into the shim.

Usage:
    PYTHONPATH=backend python scripts/build_ontology_induction_tool.py [--output-dir dist] [--allow-missing-spec]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

BUILTIN_PATH = REPO_ROOT / 'backend/open_webui/tools/ontology_induction.py'
BUILTIN_MODULE = 'open_webui.tools.ontology_induction'
ENTRYPOINT = 'induce_ontology_vocabulary'
SOURCE_REPOSITORY = 'data-satanism/open-webui-geo'
TOOL_ID = 'ontology_induction'
TOOL_NAME = 'Ontology Induction'
TOOL_VERSION = '1.0.0'
REQUIRED_OPEN_WEBUI_VERSION = '0.10.0'
DEFAULT_OUTPUT_DIR = REPO_ROOT / 'dist'
ARTIFACT_NAME = 'ontology_induction_tool.py'
MANIFEST_NAME = 'ontology_induction_tool.manifest.json'
PASSED_THROUGH = ('__request__', '__user__', '__event_emitter__', '__files__')
_PARAM = re.compile(r':param (\w+):(.*)')


@dataclass(frozen=True)
class Parameter:
    """One non-dunder parameter of the built-in: name, annotation source, literal default and docstring text."""

    name: str
    annotation: str
    default: Any
    description: str


@dataclass(frozen=True)
class Signature:
    """The built-in's docstring summary, positional and keyword-only parameters, dunders and return text."""

    summary: str
    model_facing: tuple[Parameter, ...]
    valves: tuple[Parameter, ...]
    dunders: tuple[str, ...]
    returns: str


def _docstring_parts(docstring: str) -> tuple[str, dict[str, str], str]:
    summary: list[str] = []
    params: dict[str, list[str]] = {}
    returns: list[str] = []
    current: list[str] = summary
    for line in docstring.splitlines():
        stripped = line.strip()
        match = _PARAM.match(stripped)
        if match:
            current = params.setdefault(match.group(1), [])
            current.append(match.group(2).strip())
        elif stripped.startswith(':return:'):
            current = returns
            current.append(stripped[len(':return:') :].strip())
        elif current is summary:
            summary.append(line)
        elif stripped:
            current.append(stripped)
    return (
        '\n'.join(summary).strip(),
        {name: ' '.join(lines) for name, lines in params.items()},
        ' '.join(returns),
    )


def builtin_signature(source: str | None = None) -> Signature:
    """The built-in's parameters and docstring, read from its source without importing it."""
    tree = ast.parse(source if source is not None else BUILTIN_PATH.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == ENTRYPOINT)
    summary, described, returns = _docstring_parts(ast.get_docstring(function) or '')
    args = function.args
    positional_defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)

    def parameter(arg: ast.arg, default: ast.expr | None) -> Parameter:
        return Parameter(
            name=arg.arg,
            annotation=ast.unparse(arg.annotation) if arg.annotation else 'Any',
            default=ast.literal_eval(default) if default is not None else None,
            description=described.get(arg.arg, ''),
        )

    model_facing = tuple(
        parameter(arg, default) for arg, default in zip(args.args, positional_defaults) if not arg.arg.startswith('__')
    )
    keyword = list(zip(args.kwonlyargs, args.kw_defaults))
    valves = tuple(parameter(arg, default) for arg, default in keyword if not arg.arg.startswith('__'))
    dunders = tuple(arg.arg for arg, _ in keyword if arg.arg.startswith('__'))
    return Signature(summary, model_facing, valves, dunders, returns)


def _indent(text: str, prefix: str) -> str:
    return '\n'.join(prefix + line if line else line for line in text.splitlines())


def _method_docstring(signature: Signature) -> str:
    lines = [signature.summary, '']
    for parameter in signature.model_facing:
        lines.append(f':param {parameter.name}: {parameter.description}')
    lines.append(f':return: {signature.returns}')
    return '\n'.join(lines)


def render(commit: str, signature: Signature | None = None) -> str:
    """The shim source for one source commit."""
    signature = signature or builtin_signature()
    if '"""' in _method_docstring(signature) or '\\' in _method_docstring(signature):
        raise ValueError(f'the {ENTRYPOINT} docstring holds a triple quote or a backslash')
    if tuple(signature.dunders) != PASSED_THROUGH:
        raise ValueError(f'{ENTRYPOINT} passes {signature.dunders}, expected {PASSED_THROUGH}')
    valve_lines = [
        f'        {p.name.upper()}: {p.annotation} = Field(default={p.default!r}, description={p.description!r})'
        for p in signature.valves
    ]
    method_params = [f'        {p.name}: {p.annotation} = {p.default!r},' for p in signature.model_facing]
    method_params += [
        '        __request__: Any = None,',
        '        __user__: dict = None,',
        '        __event_emitter__: Any = None,',
        '        __files__: list = None,',
    ]
    call_args = [f'            {p.name}={p.annotation}({p.name} or {p.default!r}),' for p in signature.model_facing]
    call_args += [f'            {p.name}={p.annotation}(self.valves.{p.name.upper()}),' for p in signature.valves]
    call_args += [f'            {name}={name},' for name in PASSED_THROUGH]
    docstring = _indent(_method_docstring(signature), '        ')
    return '\n'.join(
        [
            '"""',
            f'title: {TOOL_NAME}',
            'author: GeoMAS',
            f'version: {TOOL_VERSION}',
            f'required_open_webui_version: {REQUIRED_OPEN_WEBUI_VERSION}',
            f'description: Generated by scripts/build_ontology_induction_tool.py from {SOURCE_REPOSITORY}@{commit}. '
            'Do not edit in the Workspace; edit the built-in in Git and rebuild.',
            '"""',
            '',
            'from typing import Any',
            '',
            'from pydantic import BaseModel, Field',
            '',
            f'from {BUILTIN_MODULE} import {ENTRYPOINT}',
            '',
            '',
            'class Tools:',
            '    class Valves(BaseModel):',
            *valve_lines,
            '',
            '    def __init__(self):',
            '        self.valves = self.Valves()',
            '',
            f'    async def {ENTRYPOINT}(',
            '        self,',
            *method_params,
            '    ) -> str:',
            '        """' + docstring.lstrip(),
            '        """',
            f'        return await {ENTRYPOINT}(',
            *call_args,
            '        )',
            '',
        ]
    )


def source_commit() -> str:
    """The commit the repository is at."""
    return subprocess.run(
        ['git', '-C', str(REPO_ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True
    ).stdout.strip()


class SpecUnavailable(RuntimeError):
    """Open WebUI's tool spec generator cannot be imported here."""


def tool_spec(content: str) -> list[dict]:
    """The schema the model sees, generated by Open WebUI's `get_tool_specs` from the shim."""
    try:
        from open_webui.utils.tools import get_tool_specs
    except ImportError as exc:  # pragma: no cover
        raise SpecUnavailable(str(exc)) from exc
    namespace: dict = {}
    exec(compile(content, ARTIFACT_NAME, 'exec'), namespace)
    return get_tool_specs(namespace['Tools']())


def build(output_dir: Path, commit: str | None = None, *, allow_missing_spec: bool = False) -> dict:
    """Write the shim and its manifest into `output_dir` and return the manifest."""
    commit = commit or source_commit()
    signature = builtin_signature()
    content = render(commit, signature)
    raw = content.encode('utf-8')
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / ARTIFACT_NAME).write_bytes(raw)
    manifest: dict[str, Any] = {
        'schema_version': 1,
        'tool_id': TOOL_ID,
        'name': TOOL_NAME,
        'version': TOOL_VERSION,
        'artifact': ARTIFACT_NAME,
        'sha256': hashlib.sha256(raw).hexdigest(),
        'bytes': len(raw),
        'source_repository': SOURCE_REPOSITORY,
        'source_commit': commit,
        'entrypoint': ENTRYPOINT,
        'required_open_webui_version': REQUIRED_OPEN_WEBUI_VERSION,
        'valves': {p.name.upper(): p.default for p in signature.valves},
    }
    try:
        manifest['spec'] = tool_spec(content)
        manifest['spec_unavailable_because'] = None
    except SpecUnavailable as exc:
        if not allow_missing_spec:
            raise
        manifest['spec'] = None
        manifest['spec_unavailable_because'] = f'{exc}; install backend/requirements.txt to record it'
    (output_dir / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return manifest


def main() -> int:
    """Build into `--output-dir` and print the shim's digest and size."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('--allow-missing-spec', action='store_true', help='developer machines only')
    args = parser.parse_args()
    manifest = build(args.output_dir, allow_missing_spec=args.allow_missing_spec)
    print(
        f'{args.output_dir / ARTIFACT_NAME}: {manifest["name"]} {manifest["version"]}, '
        f'sha256 {manifest["sha256"]}, {manifest["bytes"]} bytes, from {manifest["source_commit"][:8]}'
    )
    if manifest['spec'] is None:
        print(f'  WARNING: {manifest["spec_unavailable_because"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
