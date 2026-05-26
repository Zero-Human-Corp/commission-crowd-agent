"""Domain models for lead, opportunity, task, and workflow lifecycle.

All models are Pydantic BaseModels for validation and serialisation.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LeadStatus(StrEnum):
    """Finite state machine for a lead."""

    NEW = "New"
    RESEARCHING = "Researching"
    DRAFT_READY = "Draft Ready"
    APPROVED = "Approved"
    SENT = "Sent"
    SEND_FAILED = "Send Failed"


class TaskType(StrEnum):
    RESEARCH = "research"
    WRITE = "write"
    SCORE = "score"
    SEND = "send"


class Lead(BaseModel):
    """A single B2B lead with research and outreach state."""

    lead_id: str = Field(..., description="Unique identifier")
    client_name: str = Field(..., description="Client / campaign grouping")
    full_name: str = ""
    company: str = ""
    email: str = ""
    research_notes: str = ""
    email_subject: str = ""
    email_body: str = ""
    personalization_score: int | None = Field(default=None, ge=1, le=10)
    status: LeadStatus = LeadStatus.NEW
    approved: bool = False
    sent_timestamp: datetime | None = None
    error_log: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower().strip()

    def to_sheet_row(self) -> dict[str, Any]:
        """Serialise for Google Sheets."""
        return {
            "Lead ID": self.lead_id,
            "Client Name": self.client_name,
            "Full Name": self.full_name,
            "Company": self.company,
            "Email": self.email,
            "Research Notes": self.research_notes,
            "Email Subject": self.email_subject,
            "Email Body": self.email_body,
            "Personalization Score": self.personalization_score,
            "Status": self.status.value,
            "Approved": self.approved,
            "Sent Timestamp": self.sent_timestamp.isoformat() if self.sent_timestamp else "",
            "Error Log": self.error_log,
        }


class Task(BaseModel):
    """A unit of work inside a workflow run."""

    task_id: str
    task_type: TaskType
    lead_id: str
    status: str = "pending"  # pending | running | done | failed
    output: str = ""
    error: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def mark_started(self) -> None:
        self.status = "running"
        self.started_at = datetime.utcnow()

    def mark_done(self, output: str = "") -> None:
        self.status = "done"
        self.output = output
        self.finished_at = datetime.utcnow()

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error = error
        self.finished_at = datetime.utcnow()


class WorkflowRun(BaseModel):
    """A single execution of a campaign workflow."""

    run_id: str
    client_name: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    tasks: list[Task] = Field(default_factory=list)
    status: str = "running"  # running | completed | failed

    @property
    def is_complete(self) -> bool:
        return all(t.status in {"done", "failed"} for t in self.tasks)

    def summary(self) -> dict[str, Any]:
        total = len(self.tasks)
        done = sum(1 for t in self.tasks if t.status == "done")
        failed = sum(1 for t in self.tasks if t.status == "failed")
        return {
            "run_id": self.run_id,
            "client_name": self.client_name,
            "status": self.status,
            "total": total,
            "done": done,
            "failed": failed,
        }
