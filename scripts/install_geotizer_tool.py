"""S1.7: install the built adapter, and refuse to overwrite what you did not build.

The Workspace Tool lives in `webui.db`, which is mutable and outside Git. That is
the whole reason this script exists: the only safe install is one that first
proves the thing it is about to replace is a build, and not somebody's edit.

The rule, in order:

  the tool is absent                     -> install
  its digest is the manifest's           -> already installed, nothing to do
  its digest is a build we recorded      -> upgrade, and say which version
  its digest is anything else            -> **refuse**, and print the digest

The last line is the point. An unrecognised digest means the instance is running
something no build produced, and overwriting it destroys the only copy of
whatever that was. §8's "report drift, do not absorb it": an unexpected Tool SHA
means someone changed production, and that is information.

`--force` exists and is deliberately awkward to justify: it still prints the
digest it is about to destroy, and it will not run without `--i-have-a-copy`.

No credential appears here or in anything it writes. The API key is read from
the file named by `--token-file`, never from a command-line argument, because
arguments are visible in the process table and land in shell history.

Usage:
    python scripts/install_geotizer_tool.py \\
        --manifest dist/geoteaser_tool.manifest.json \\
        --url http://localhost:8080 --token-file ~/.geomas/token
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Digests of builds this repository has produced. A tool carrying one of these
# is safe to replace; anything else is not ours to destroy. Add a line when a
# release is cut, never to make an install go through.
KNOWN_BUILD_DIGESTS: dict[str, str] = {}

ABSENT = 'absent'
CURRENT = 'current'
KNOWN_BUILD = 'known_build'
UNRECOGNISED = 'unrecognised'


def digest(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def classify(installed: str | None, manifest: dict[str, Any]) -> tuple[str, str | None]:
    """What is on the instance, relative to what we built."""
    if installed is None:
        return ABSENT, None
    found = digest(installed)
    if found == manifest['sha256']:
        return CURRENT, found
    if found in KNOWN_BUILD_DIGESTS:
        return KNOWN_BUILD, found
    return UNRECOGNISED, found


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect while carrying the admin credential.

    `urlopen` follows 3xx by default and its redirect handler copies the
    request headers onto the follow-up -- so a redirect from the
    operator-supplied `--url` sends a live `Authorization: Bearer <admin key>`
    to whatever host the `Location` names. There is no legitimate reason for a
    tool-install API to redirect, so this refuses instead of choosing which
    redirects are safe.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            (
                f'refusing to follow a {code} redirect to {newurl}: the admin '
                f'credential would travel with it'
            ),
            headers,
            fp,
        )


# A hung install must fail rather than wait forever holding the credential.
REQUEST_TIMEOUT_SECONDS = 30

_OPENER = urllib.request.build_opener(_RefuseRedirects)


def _request(url: str, token: str, method: str = 'GET', payload: dict | None = None) -> Any:
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header('Authorization', f'Bearer {token}')
    request.add_header('Content-Type', 'application/json')
    with _OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
        return json.loads(response.read().decode('utf-8'))


def fetch_installed(base_url: str, token: str, tool_id: str) -> str | None:
    try:
        record = _request(f'{base_url.rstrip("/")}/api/v1/tools/id/{tool_id}', token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return record.get('content')


def _payload(manifest: dict[str, Any], content: str) -> dict[str, Any]:
    return {
        'id': manifest['tool_id'],
        'name': manifest['name'],
        'content': content,
        'meta': {
            'description': f'{manifest["name"]} {manifest["version"]}',
            'manifest': {
                'version': manifest['version'],
                'sha256': manifest['sha256'],
                'source_repository': manifest['source_repository'],
                'source_commit': manifest['source_commit'],
            },
        },
    }


def install(base_url: str, token: str, manifest: dict[str, Any], content: str) -> Any:
    return _request(
        f'{base_url.rstrip("/")}/api/v1/tools/create',
        token,
        method='POST',
        payload=_payload(manifest, content),
    )


def replace(base_url: str, token: str, manifest: dict[str, Any], content: str) -> Any:
    """Overwrite an existing tool's content.

    `/tools/create` refuses an id that exists -- `routers/tools.py` raises
    `ID_TAKEN` -- so the create path installs a first copy and nothing else.
    Every interesting case here is a replacement of `geoteaser`, which exists,
    so the whole install would have failed on a 400 that says nothing about
    what went wrong.

    `/id/{id}/update` takes a `ToolForm`, and `ToolForm` has no `valves` field,
    so `update_tool_by_id` writes `content`, `name`, `meta` and `specs` and
    never touches the `valves` column. The stored valve values survive the
    replacement -- see `record_valves` for why surviving is not the same as
    still being read.
    """
    return _request(
        f'{base_url.rstrip("/")}/api/v1/tools/id/{manifest["tool_id"]}/update',
        token,
        method='POST',
        payload=_payload(manifest, content),
    )


def record_valves(base_url: str, token: str, tool_id: str) -> dict | None:
    """The stored valves, fetched before anything is overwritten.

    They survive the update, but the shim declares no `Valves` class, so after
    the swap nothing reads them: the row keeps its values and the running code
    stops seeing them. That is the hydration outage from the other direction and
    the symptom is identical -- a card that fills at a few per cent because the
    settings it ran on are still in the database and no longer on the path.

    Whatever comes back may contain a credential. It is printed as key names and
    value *shapes*, never values, and the operator is told to save the full body
    themselves, outside Git.
    """
    try:
        return _request(
            f'{base_url.rstrip("/")}/api/v1/tools/id/{tool_id}/valves', token
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def describe_valves(valves: dict | None) -> str:
    if valves is None:
        return 'no valves are stored for this tool'
    if not valves:
        return 'the valve record is present and empty'
    shapes = ', '.join(f'{key}: {type(value).__name__}' for key, value in sorted(valves.items()))
    return f'{len(valves)} stored valve(s) -- {shapes}'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--url', required=True, help='Open WebUI base URL')
    parser.add_argument(
        '--token-file',
        type=Path,
        required=True,
        help='file holding the admin API key. Never passed as an argument: arguments are visible in the process table.',
    )
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true', help='overwrite an unrecognised tool')
    parser.add_argument(
        '--i-have-a-copy',
        action='store_true',
        help='required alongside --force: confirms the unrecognised content is saved elsewhere',
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    content = (args.manifest.parent / manifest['artifact']).read_text(encoding='utf-8')
    if digest(content) != manifest['sha256']:
        print('ERROR: the artefact does not match its own manifest; rebuild before installing')
        return 1

    token = args.token_file.read_text(encoding='utf-8').strip()
    installed = fetch_installed(args.url, token, manifest['tool_id'])
    state, found = classify(installed, manifest)

    if state == CURRENT:
        print(f'{manifest["tool_id"]}: already at {manifest["version"]} ({found[:12]}); nothing to do')
        return 0

    if state == UNRECOGNISED:
        print(f'REFUSING to overwrite {manifest["tool_id"]}: installed digest {found} is not a build we made.')
        print('  Someone changed the Workspace copy. Save it, find out what changed, then decide.')
        if not (args.force and args.i_have_a_copy):
            return 1
        print(f'  --force --i-have-a-copy given; destroying {found[:12]} and installing {manifest["sha256"][:12]}')

    if state == ABSENT:
        print(f'{manifest["tool_id"]}: absent; installing {manifest["version"]} ({manifest["sha256"][:12]})')
    elif state == KNOWN_BUILD:
        print(
            f'{manifest["tool_id"]}: upgrading from {KNOWN_BUILD_DIGESTS[found]} '
            f'({found[:12]}) to {manifest["version"]} ({manifest["sha256"][:12]})'
        )

    # Before anything is written, and printed either way: an operator who is
    # about to replace a tool needs to know what configuration is riding on it.
    valves = record_valves(args.url, token, manifest['tool_id'])
    print(f'  valves: {describe_valves(valves)}')
    if valves:
        print(
            f'  SAVE THEM FIRST: GET {args.url.rstrip("/")}/api/v1/tools/'
            f'id/{manifest["tool_id"]}/valves -- the update preserves the row, '
            f'but the shim declares no Valves class, so nothing will read it.'
        )

    if args.dry_run:
        print('  --dry-run: nothing was written')
        return 0

    if state == ABSENT:
        install(args.url, token, manifest, content)
    else:
        replace(args.url, token, manifest, content)
    print(f'  installed {manifest["name"]} {manifest["version"]} from {manifest["source_commit"][:8]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
