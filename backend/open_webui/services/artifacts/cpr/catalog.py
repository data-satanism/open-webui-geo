"""Loading the CPR requirement catalog, and proving it is the right one.

GMM owns `contracts/cpr/cpr_requirement_catalog.v1.json`. The runtime carries a
byte-identical copy so requirement planning does not reach across repositories,
and the copy's digest is verified on every load.

That check is the point. Two copies of a controlled vocabulary that can drift
without anyone noticing are worse than one copy nobody can read: the CPR would
then be planned against one set of applicability rules and audited against
another, and both would look right. GMM's attention register carries the same
concern for the geotizer assets in `gis_service` as A-08.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import CprContractError

ASSETS = Path(__file__).resolve().parent / 'assets'
CATALOG_FILE = 'cpr_requirement_catalog.v1.json'
PROVENANCE_FILE = 'provenance.json'

# The catalog is a draft for domain review, not an approved contract. Planning
# against it is fine; presenting its output as approved is not, and the status
# travels with the plan so the artefact can say so.
DRAFT_STATUS = 'draft_for_domain_review'


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise CprContractError(f'CPR asset is missing: {path.name}') from exc
    except json.JSONDecodeError as exc:
        raise CprContractError(f'CPR asset does not parse: {path.name}: {exc}') from exc


def provenance(assets: Path | None = None) -> dict[str, Any]:
    """What this copy claims to be, and where it came from."""
    return _read_json((assets or ASSETS) / PROVENANCE_FILE)


@lru_cache(maxsize=4)
def _load(assets_key: str) -> dict[str, Any]:
    assets = Path(assets_key)
    recorded = provenance(assets).get('files', {}).get(CATALOG_FILE)
    if not recorded:
        raise CprContractError(f'{CATALOG_FILE} has no provenance record')

    path = assets / CATALOG_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise CprContractError(f'CPR asset is missing: {CATALOG_FILE}') from exc

    digest = hashlib.sha256(raw).hexdigest()
    if digest != recorded.get('sha256'):
        raise CprContractError(
            f'{CATALOG_FILE} does not match its recorded digest: '
            f'{digest} != {recorded.get("sha256")}. The copy has drifted from '
            f'{recorded.get("source_repository")} {recorded.get("source_path")}.'
        )

    catalog = json.loads(raw.decode('utf-8'))
    if len(catalog.get('requirements') or []) != recorded.get('requirements'):
        raise CprContractError(f'{CATALOG_FILE} requirement count disagrees with provenance')
    return catalog


def load_catalog(assets: Path | None = None) -> dict[str, Any]:
    """The catalog, verified against its digest. Cached per assets directory."""
    return _load(str(assets or ASSETS))


def catalog_version(assets: Path | None = None) -> str:
    return str(load_catalog(assets)['catalog_version'])


def is_draft(assets: Path | None = None) -> bool:
    """A draft plan may be produced; it may not be presented as approved."""
    return load_catalog(assets).get('status') == DRAFT_STATUS


def requirements_by_id(assets: Path | None = None) -> dict[str, dict[str, Any]]:
    return {entry['id']: entry for entry in load_catalog(assets)['requirements']}


def states(assets: Path | None = None) -> tuple[str, ...]:
    return tuple(load_catalog(assets)['states'])


def if_not_why_not_states(assets: Path | None = None) -> frozenset[str]:
    """The three states that oblige a recorded reason."""
    return frozenset(load_catalog(assets)['if_not_why_not_required_for'])


__all__ = [
    'ASSETS',
    'CATALOG_FILE',
    'catalog_version',
    'if_not_why_not_states',
    'is_draft',
    'load_catalog',
    'provenance',
    'requirements_by_id',
    'states',
]
