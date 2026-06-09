"""Tests for email_templates module."""

from __future__ import annotations

import pytest

from commission_crowd_agent.email_templates import TEMPLATES, render_template


class TestRenderTemplate:
    def test_cold_intro(self) -> None:
        subject, body = render_template(
            "cold_intro",
            {
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "We met at the SaaS summit.",
            },
        )
        assert "Acme Corp" in subject
        assert "Hello Alice" in body
        assert "We met at the SaaS summit." in body
        assert "Best regards," in body

    def test_follow_up(self) -> None:
        subject, body = render_template(
            "follow_up",
            {
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "last_contact_date": "2024-01-01",
                "context": "Just checking in.",
            },
        )
        assert "follow-up" in subject
        assert "2024-01-01" in body
        assert "Just checking in." in body

    def test_proposal(self) -> None:
        subject, body = render_template(
            "proposal",
            {
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "Based on our call.",
                "territory": "North America",
                "icp_summary": "Mid-market B2B SaaS",
                "commission_structure": "15% on net revenue",
                "next_step": "Sign the rep agreement",
            },
        )
        assert "Proposal" in subject
        assert "North America" in body
        assert "15% on net revenue" in body

    def test_rejection(self) -> None:
        subject, body = render_template(
            "rejection",
            {
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "We decided to pause outreach.",
            },
        )
        assert "Update on Acme Corp" in subject
        assert "pause outreach" in body

    def test_meeting_request(self) -> None:
        subject, body = render_template(
            "meeting_request",
            {
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "Would love to walk through the model.",
                "time_option_1": "2024-06-10T09:00",
                "time_option_2": "2024-06-10T10:00",
                "time_option_3": "2024-06-10T11:00",
            },
        )
        assert "15-min call" in subject
        assert "2024-06-10T09:00" in body
        assert "2024-06-10T11:00" in body

    def test_unknown_template(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            render_template("nonexistent", {})
        assert "Unknown template" in str(exc_info.value)

    def test_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            # missing contact_name, sender_name, context
            render_template("cold_intro", {"company_name": "Acme"})

    def test_all_templates_have_subject_and_body(self) -> None:
        for _name, tmpl in TEMPLATES.items():
            assert "subject" in tmpl
            assert "body" in tmpl
            assert tmpl["subject"]
            assert tmpl["body"]
