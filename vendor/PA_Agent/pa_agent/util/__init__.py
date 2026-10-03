"""PA Agent utility package."""

from pa_agent.util.threading import CancelToken, OrchestratorEvent
from pa_agent.util.logging import configure_logging, update_api_key

__all__ = ["CancelToken", "OrchestratorEvent", "EventBus", "configure_logging", "update_api_key"]

# Integration modification: load desktop EventBus only when requested.
# Headless market features do not require Qt or start a GUI.
def __getattr__(name):
    if name == "EventBus":
        from pa_agent.util.event_bus import EventBus
        return EventBus
    raise AttributeError(name)
