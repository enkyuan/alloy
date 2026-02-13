"""Canonical service name mappings for integrations."""

DB_TO_CLIENT_SERVICE_NAME: dict[str, str] = {
    "google_calendar": "googleCalendar",
    "spotify": "spotify",
    "gmail": "gmail",
    "uber": "uber",
    "discord": "discord",
    "todoist": "todoist",
    "calendly": "calendly",
}

PATH_TO_DB_SERVICE_NAME: dict[str, str] = {
    "google-calendar": "google_calendar",
    "gmail": "gmail",
    "spotify": "spotify",
    "uber": "uber",
    "discord": "discord",
    "todoist": "todoist",
    "calendly": "calendly",
}


def to_client_service_name(db_service_name: str) -> str:
    """Map database service name to client-facing service name."""
    return DB_TO_CLIENT_SERVICE_NAME.get(db_service_name, db_service_name)


def to_db_service_name(path_service_name: str) -> str:
    """Map path service name to database service name."""
    return PATH_TO_DB_SERVICE_NAME.get(path_service_name, path_service_name)
