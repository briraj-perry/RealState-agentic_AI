"""Company identity persisted across restarts and shared by workers and web requests."""

from estate_ai.db import WorkspaceSettings


def company_name(session, settings):
    saved = session.get(WorkspaceSettings, "identity")
    return saved.business_name if saved else settings.business_name
