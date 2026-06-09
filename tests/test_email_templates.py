"""Tests for email_templates module.

Includes original templates and new sales-ops templates:
outreach, follow_up_gentle, follow_up_urgent,
application_submission, application_follow_up.
"""

from __future__ import annotations

import pytest

from commission_crowd_agent.email_templates import TEMPLATES, render_template


class TestRenderTemplate:
    # --- Original templates ---

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

    # --- New templates ---

    def test_outreach(self) -> None:
        subject, body = render_template(
            "outreach",
            {
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "I noticed you recently expanded into EMEA.",
            },
        )
        assert "Commission-only representation for Acme Corp" in subject
        assert "Bob" in body
        assert "EMEA" in body

    def test_follow_up_gentle(self) -> None:
        subject, body = render_template(
            "follow_up_gentle",
            {
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "I know you're busy.",
            },
        )
        assert "Checking in" in subject
        assert "gently follow up" in body
        assert "I know you're busy." in body

    def test_follow_up_urgent(self) -> None:
        subject, body = render_template(
            "follow_up_urgent",
            {
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "I wanted to confirm one way or the other.",
            },
        )
        assert "Last follow-up" in subject
        assert "one last time" in body
        assert "close the loop" in body

    def test_application_submission(self) -> None:
        subject, body = render_template(
            "application_submission",
            {
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "I have 10 years of SaaS sales experience.",
                "territory": "North America",
                "industry_focus": "B2B SaaS",
                "years_experience": "10",
                "icp_summary": "Mid-market SaaS companies",
                "commission_structure": "15% on net revenue",
                "sender_email": "bob@example.com",
                "sender_phone": "+1 555 1234",
            },
        )
        assert "Application for commission-only sales representation" in subject
        assert "Acme Corp" in body
        assert "B2B SaaS" in body
        assert "15% on net revenue" in body
        assert "bob@example.com" in body
        assert "+1 555 1234" in body

    def test_application_follow_up(self) -> None:
        subject, body = render_template(
            "application_follow_up",
            {
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "I wanted to see if you needed any more info.",
                "submitted_date": "2024-01-15",
                "sender_email": "bob@example.com",
            },
        )
        assert "Follow-up: Application for commission-only sales rep" in subject
        assert "2024-01-15" in body
        assert "bob@example.com" in body

    # --- Error cases ---

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
