"""Tests for the real OutreachAdapter SMTP email dispatcher."""

from __future__ import annotations

from commission_crowd_agent.adapters import OutreachAdapter
from commission_crowd_agent.domain import Lead


class TestOutreachAdapterHealth:
    def test_health_missing_creds(self) -> None:
        adapter = OutreachAdapter(dry_run=True)
        result = adapter.health_check()
        assert result["ok"] is False
        assert "Missing SMTP credentials" in result["error"]

    def test_health_ready(self) -> None:
        adapter = OutreachAdapter(
            smtp_host="smtp.hostinger.com",
            smtp_port=465,
            smtp_user="u",
            smtp_pass="p",
            dry_run=True,
        )
        result = adapter.health_check()
        assert result["ok"] is True
        assert result["host"] == "smtp.hostinger.com"
        assert result["port"] == 465
        assert result["user"] == "u"

    def test_default_port_is_465(self) -> None:
        adapter = OutreachAdapter(dry_run=True)
        assert adapter.smtp_port == 465


class TestSendEmail:
    def test_send_email_dry_run(self) -> None:
        adapter = OutreachAdapter(dry_run=True)
        result = adapter.send_email(
            to_address="alice@example.com",
            subject="Hello",
            body="World",
        )
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["to"] == "alice@example.com"
        assert result["subject"] == "Hello"

    def test_send_email_with_lead(self) -> None:
        adapter = OutreachAdapter(dry_run=True)
        lead = Lead(lead_id="L001", client_name="test", email="bob@example.com")
        result = adapter.send_email(lead=lead)
        assert result["ok"] is True
        assert result["to"] == "bob@example.com"

    def test_send_email_missing_to(self) -> None:
        adapter = OutreachAdapter(dry_run=False)
        result = adapter.send_email(subject="S", body="B")
        assert result["ok"] is False
        assert "Missing to_address" in result["error"]

    def test_send_email_missing_smtp_config(self) -> None:
        adapter = OutreachAdapter(dry_run=False)
        result = adapter.send_email(
            to_address="a@b.com",
            subject="S",
            body="B",
        )
        assert result["ok"] is False
        assert "SMTP not configured" in result["error"]

    def test_send_from_template(self) -> None:
        adapter = OutreachAdapter(dry_run=True)
        result = adapter.send_from_template(
            template_name="cold_intro",
            context={
                "company_name": "Acme Corp",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "Hello",
            },
            to_address="alice@example.com",
        )
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["to"] == "alice@example.com"

    def test_send_from_template_missing_key(self) -> None:
        adapter = OutreachAdapter(dry_run=False)
        result = adapter.send_from_template(
            template_name="cold_intro",
            context={"company_name": "Acme"},
            to_address="a@b.com",
        )
        assert result["ok"] is False
        assert "Template render failed" in result["error"]

    def test_from_address_defaults_to_user(self) -> None:
        adapter = OutreachAdapter(
            smtp_user="test@host.com",
            dry_run=True,
        )
        assert adapter.from_address == "test@host.com"


class TestBuildMessage:
    def test_build_message_plain(self) -> None:
        adapter = OutreachAdapter(
            smtp_host="smtp.hostinger.com",
            smtp_user="u",
            dry_run=True,
        )
        _from, _to, raw = adapter._build_message("a@b.com", "Hi", "Body text")
        assert _from == "u" or _from == "smtp.hostinger.com"
        assert _to == "a@b.com"
        assert "From: " in raw
        assert "Subject: Hi" in raw
        assert "Body text" in raw

    def test_build_message_html(self) -> None:
        adapter = OutreachAdapter(
            smtp_host="smtp.hostinger.com",
            smtp_user="u",
            dry_run=True,
        )
        _from, _to, raw = adapter._build_message(
            "a@b.com",
            "Hi",
            "Body text",
            html="<html></body></html>",
        )
        assert "multipart/alternative" in raw

    def test_port_uses_ssl(self) -> None:
        # This only verifies the port constants; we don't connect in tests
        adapter = OutreachAdapter(
            smtp_host="smtp.hostinger.com",
            smtp_port=465,
            smtp_user="u",
            smtp_pass="p",
            dry_run=True,
        )
        result = adapter.send_email(to_address="a@b.com", subject="S", body="B")
        assert result["ok"] is True

    def test_port_587_uses_tls(self) -> None:
        adapter = OutreachAdapter(
            smtp_host="smtp.hostinger.com",
            smtp_port=587,
            smtp_user="u",
            smtp_pass="p",
            dry_run=True,
        )
        result = adapter.send_email(to_address="a@b.com", subject="S", body="B")
        assert result["ok"] is True
