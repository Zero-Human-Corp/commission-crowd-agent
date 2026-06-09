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
    "outreach": {
        "subject": "{sender_name} — Commission-only representation for {company_name}",
        "body": (
            "Hi {contact_name},\n\n"
            "I hope this message finds you well. My name is {sender_name} and I'm "
            "reaching out because I believe {company_name} could benefit from "
            "experienced commission-only sales representation.\n\n"
            "{context}\n\n"
            "I specialise in helping companies like yours expand their reach without "
            "the overhead of a full-time sales team. I'd love to discuss how we "
            "might work together.\n\n"
            "Are you open to a brief 10-minute conversation this week?\n\n"
            "Best regards,\n"
            "{sender_name}"
        ),
    },
    "follow_up_gentle": {
        "subject": "Checking in — {company_name} commission-only sales",
        "body": (
            "Hi {contact_name},\n\n"
            "I hope you're doing well. I wanted to gently follow up on my previous "
            "message about commission-only sales representation for {company_name}.\n\n"
            "{context}\n\n"
            "I know inboxes are busy, so I'll keep this short. If the timing isn't "
            "right, just say the word and I'll circle back in a few weeks.\n\n"
            "Kind regards,\n"
            "{sender_name}"
        ),
    },
    "follow_up_urgent": {
        "subject": "Last follow-up — {company_name} commission-only sales",
        "body": (
            "Hi {contact_name},\n\n"
            "I wanted to reach out one last time regarding commission-only sales "
            "representation for {company_name}.\n\n"
            "{context}\n\n"
            "If there's no interest at this time, I completely understand and will "
            "close the loop on my end. If circumstances change in the future, feel "
            "free to reach out.\n\n"
            "All the best,\n"
            "{sender_name}"
        ),
    },
    "application_submission": {
        "subject": "Application for commission-only sales representation — {company_name}",
        "body": (
            "Dear {contact_name},\n\n"
            "I am writing to formally submit my application for a commission-only "
            "sales representation role with {company_name}. Having reviewed your "
            "offering and market position, I am confident I can drive meaningful "
            "revenue growth in {territory}.\n\n"
            "{context}\n\n"
            "About my approach:\n"
            "- Specialised focus on {industry_focus}\n"
            "- Proven track record with {years_experience} years in commission-only sales\n"
            "- Target ICP: {icp_summary}\n"
            "- Commission structure: {commission_structure}\n\n"
            "I have attached my profile and any relevant references. I would welcome "
            "the opportunity to discuss how we can build a successful partnership.\n\n"
            "Please let me know if you require any additional information.\n\n"
            "Yours sincerely,\n"
            "{sender_name}\n"
            "{sender_email}\n"
            "{sender_phone}"
        ),
    },
    "application_follow_up": {
        "subject": "Follow-up: Application for commission-only sales rep — {company_name}",
        "body": (
            "Dear {contact_name},\n\n"
            "I hope this message finds you well. I am following up on my application "
            "for a commission-only sales representation role with {company_name}, "
            "submitted on {submitted_date}.\n\n"
            "{context}\n\n"
            "I remain very interested in exploring this opportunity and would be "
            "grateful for any update you might be able to share. If there is any "
            "additional information you need from me, please don't hesitate to ask.\n\n"
            "Thank you for your time and consideration.\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{sender_email}"
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
