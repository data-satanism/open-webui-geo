"""Named errors of the ontology induction core."""

from __future__ import annotations


class OntologyInductionError(Exception):
    """Base error. `code` is the name a refusal reports."""

    code = 'ontology_induction_error'


class PinnedAssetMismatch(OntologyInductionError):
    """A pinned GMM asset is missing or differs from its provenance record."""

    code = 'pinned_asset_mismatch'


class EvidenceOutsideDocuments(OntologyInductionError):
    """An evidence entry names a file that is not in the proposal's `documents[]`."""

    code = 'evidence_file_not_in_documents'
