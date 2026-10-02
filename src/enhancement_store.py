# Based on NeuraXmy/nightreign-overlay-helper v0.10.5.
# Added/modified 2026-10-02; see NOTICE.md and LICENSE (GNU AGPL v3).
from dataclasses import asdict
from src.automation import AutomationOptions
from src.common import get_appdata_path, load_yaml, save_yaml
from pathlib import Path


def load_options():
    path = get_appdata_path("automation.yaml")
    values = load_yaml(path) if Path(path).exists() else {}
    options = AutomationOptions.from_dict(values)
    if values and values.get("preferences_revision") != 3:
        save_options(options)
    return options


def save_options(options):
    save_yaml(get_appdata_path("automation.yaml"), asdict(options))
