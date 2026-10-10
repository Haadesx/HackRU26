"""MedCheck VLM service (owner: PI-3 Juno).

Public API::

    from services.vlm import client_from_env, should_use_vlm, reconcile_fields

Never launches a model: the adapter talks to the existing shared vLLM service.
"""
from services.vlm.client import Qwen3VLClient, VlmConfig, VlmResult, client_from_env
from services.vlm.reconcile import (
    reconcile_fields,
    should_use_vlm,
    to_contract_medication,
    uncertainty_from_fields,
)

__all__ = [
    "Qwen3VLClient",
    "VlmConfig",
    "VlmResult",
    "client_from_env",
    "reconcile_fields",
    "should_use_vlm",
    "to_contract_medication",
    "uncertainty_from_fields",
]
