from flask_smorest import Api


def register_blueprints(api: Api) -> None:
    from app.api import (
        adherence,
        auth,
        caregivers,
        doses,
        health,
        inventory,
        medications,
        notifications,
        prescriptions,
    )

    for module in (health, auth, caregivers, medications, prescriptions, doses, inventory, notifications, adherence):
        api.register_blueprint(module.blp, url_prefix="/api/v1")
