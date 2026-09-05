#!/usr/bin/env python3
"""Who can read a knowledge collection, printed from the grant rows.

Runs `82365089` and `26aaf34a` returned 24 documents from another tenant's
corpus — the «БЮЛЕР» series, an extrusion lecture course, the «Протекс» sheets
— on 31 and 52 KB calls that named no collection. The unscoped arm is not the
leak shape it looked like: `Knowledges.search_knowledge_bases` applies
`AccessGrants.has_permission_filter` **inside the SQL**, before a file is read,
and that filter has no administrator bypass (the bypass lives in
`_has_read_access_to_knowledge`, used by the arms that name collections).

So the corpus was reachable through a real grant on that account. Which grant
decides what to do about it, and the two answers need different things:

    a `user:*` read grant   every user of the contour can read it, and the
                            fix is a permission change, not a code change
    specific grants         the account holds them, and the question is why

No run answers this and no code change closes it — the grant rows do. They live
in the contour's `webui.db`, which a development session cannot reach: the
checkout's own database holds zero knowledge rows.

    python3 scripts/report_knowledge_grants.py <ids...>
    python3 scripts/report_knowledge_grants.py --db /path/to/webui.db <ids...>
    python3 scripts/report_knowledge_grants.py --full <ids...>   # show principals

Read-only: it opens the database in immutable mode and issues SELECTs only.
Specific principal ids are abbreviated by default so the output can be pasted
into a report; `--full` prints them.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path('backend/data/webui.db')
PUBLIC = ('user', '*')


def _abbreviate(principal_id: str, *, full: bool) -> str:
    if full or principal_id == '*':
        return principal_id
    return f'{principal_id[:8]}…' if len(principal_id) > 8 else principal_id


def report(db_path: Path, identifiers: list[str], *, full: bool) -> int:
    if not db_path.is_file():
        print(f'no database at {db_path}', file=sys.stderr)
        return 2
    connection = sqlite3.connect(f'file:{db_path}?mode=ro&immutable=1', uri=True)
    public_anywhere = False
    missing: list[str] = []
    for identifier in identifiers:
        row = connection.execute(
            'select id, name, user_id from knowledge where id = ?', (identifier,)
        ).fetchone()
        print(f'--- {identifier}')
        if row is None:
            print('    not in this database')
            missing.append(identifier)
            continue
        print(f'    name  {row[1]}')
        print(f'    owner {_abbreviate(str(row[2] or ""), full=full)}')
        grants = connection.execute(
            'select principal_type, principal_id, permission from access_grant '
            "where resource_type = 'knowledge' and resource_id = ? "
            'order by principal_type, principal_id, permission',
            (identifier,),
        ).fetchall()
        if not grants:
            print('    no grants: readable by its owner only')
        for principal_type, principal_id, permission in grants:
            public = (principal_type, principal_id) == PUBLIC
            public_anywhere = public_anywhere or (public and permission == 'read')
            marker = '  <-- PUBLIC' if public else ''
            print(
                f'    {principal_type}:{_abbreviate(str(principal_id), full=full)} '
                f'{permission}{marker}'
            )
    print()
    if public_anywhere:
        print(
            'At least one collection carries a `user:* read` grant: every user of '
            'this contour can read it, and the remedy is a permission change.'
        )
        return 1
    if missing:
        # An absent row is not a finding. This is the wrong database, not an
        # answer about the right one, and saying otherwise would be the same
        # error as reading a zero as a measurement.
        print(
            f'{len(missing)} of {len(identifiers)} collections are not in this '
            'database, so nothing here is an answer about them. Run this against '
            'the contour that produced the runs.'
        )
        return 2
    print(
        'No `user:* read` grant among these: the account reaches them by ownership, '
        'a direct grant or a group grant, and the question is which and why.'
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('identifiers', nargs='+', help='knowledge collection ids')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument(
        '--full', action='store_true', help='print principal ids in full'
    )
    args = parser.parse_args(argv)
    return report(args.db, args.identifiers, full=args.full)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
