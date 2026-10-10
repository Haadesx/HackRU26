"""/hub: the React dashboard's API contract (frontend/docs/api-contract.md), mapped onto the core backend.

Enabled only with HUB_ENABLED=true. No login: every request acts as HUB_PATIENT_EMAIL.
"""

from app.hub.routes import hub_bp

__all__ = ["hub_bp"]
