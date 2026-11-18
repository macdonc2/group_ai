"""The settings this app was created with, as a FastAPI dependency.

`create_app(settings)` keeps its settings on `app.state`. A route or dependency that
needs configuration declares `settings: SettingsDep` and gets those, instead of calling
the process-wide `get_settings()`. In production the two are the same object; the
difference shows when an app is built with settings of its own, as tests do.

This lives in its own module because both `auth.py` and `dependencies.py` need it and
they already import each other.
"""

from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from agent_system.composition_root.config import Settings, get_settings


def get_app_settings(connection: HTTPConnection) -> Settings:
    """The app's settings; an app that was not built by `create_app` gets the process-wide ones."""
    settings = getattr(connection.app.state, "settings", None)
    return settings if settings is not None else get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
