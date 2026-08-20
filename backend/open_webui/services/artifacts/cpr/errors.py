"""Failures raised by the CPR artefact modules."""

from __future__ import annotations


class CprContractError(ValueError):
    """Raised when a CPR contract is violated or an asset does not match its
    recorded digest."""


__all__ = ['CprContractError']
