"""Deep Research pipeline: three lanes, synthesis, figures, writer, narration."""

from agent_system.adapters.outbound.research.runner import (
    ResearchRunner,
    get_runner,
    set_runner,
)

__all__ = ["ResearchRunner", "get_runner", "set_runner"]
