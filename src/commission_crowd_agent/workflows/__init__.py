"""Domain-driven workflow modules replacing n8n nodes.

Each module is a pure-Python, testable workflow stage.
External systems are injected via adapter interfaces.
"""

from __future__ import annotations

from .outreach import send_approved_outreach
from .research_cycle import run_research_cycle

__all__ = ["run_research_cycle", "send_approved_outreach"]
