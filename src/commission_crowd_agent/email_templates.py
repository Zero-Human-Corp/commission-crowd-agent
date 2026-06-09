"""Email templates module.

Provides categorized templates for outbound / inbound sales communication.
No live sending — templates only.

All templates use Python ``str.format`` for safe, LLM-friendly rendering.
"""

from __future__ import annotations

from typing import Any

TEMPLATES: dict[str, dict[str, str]] = {
    "cold_intro": {
        "subject": "Exploring a commission-only sales partnership with {company_name}",
        "body": (
            "Hello {contact_name},\n\n"
            "I came across {company_name} and wanted to reach out regarding a "
            "commission-only sales representation opportunity.\n\n"
            "{context}\n\n"
            "I'd love to learn more about what you're building and explore whether "
            "there might be a fit.\n\n"
            "Best regards,\n"
            "{sender_name}"
        ),
    },
    "follow_up": {
        "subject": "Quick follow-up — {company_name} + commission-only sales rep",
        "body": (
            "Hi {contact_name},\n\n"
            "I wanted to follow up on my note from {last_contact_date} about "
            "representing {company_name} on a commission-only basis.\n\n"
            "{context}\n\n"
            "If now isn't the right time, no worries — just let me know and I'll "
            "circle back when it makes sense.\n\n"
            "Best,\n"
            "{sender_name}"
        ),
    },
    "proposal": {
        "subject": "Proposal — commission-only representation for {company_name}",
        "body": (
            "Hi {contact_name},\n\n"
            "Following our conversation, here's a short proposal for representing "
            "{company_name} as a commission-only sales partner.\n\n"
            "{context}\n\n"
            "Key points:\n"
            "- Territory: {territory}\n"
            "- Ideal customer profile: {icp_summary}\n"
            "- Commission structure: {commission_structure}\n"
            "- Next step: {next_step}\n\n"
            "Let me know if you'd like to discuss anything or adjust the terms.\n\n"
            "Best,\n"
            "{sender_name}"
        ),
    },
    "rejection": {
        "subject": "Update on {company_name} — commission-only rep opportunity",
        "body": (
            "Hi {contact_name},\n\n"
            "Thank you for taking the time to consider the commission-only sales "
            "representation opportunity with {company_name}.\n\n"
            "{context}\n\n"
            "I appreciate the clarity, and I'm happy to reconnect in the future if "
            "circumstances change.\n\n"
            "Best wishes,\n"
            "{sender_name}"
        ),
    },
    "meeting_request": {
        "subject": "15-min call — {company_name} commission-only partnership?",
        "body": (
            "Hi {contact_name},\n\n"
            "I'd love to set up a quick 15-minute call to discuss a potential "
            "commission-only sales partnership with {company_name}.\n\n"
            "{context}\n\n"
            "Proposed times (UTC):\n"
            "- {time_option_1}\n"
            "- {time_option_2}\n"
            "- {time_option_3}\n\n"
            "If none of those work, feel free to suggest another time.\n\n"
            "Best,\n"
            "{sender_name}"
        ),
    },
}


def render_template(template_name: str, context: dict[str, Any]) -> tuple[str, str]:
    """Render an email template by name with the given context dict.

    Returns (subject, body).  Uses ``str.format``; missing keys surface a
    ``KeyError`` so callers can fix context before sending.
    """
    if template_name not in TEMPLATES:
        raise ValueError(f"Unknown template: {template_name!r}. Available: {', '.join(TEMPLATES)}")
    template = TEMPLATES[template_name]
    subject = template["subject"].format(**context)
    body = template["body"].format(**context)
    return subject, body
