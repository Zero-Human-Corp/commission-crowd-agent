import hashlib
import json
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Verified operator profile data (from commissioncrowd-profile.html)
# ---------------------------------------------------------------------------
OPERATOR = {
    "company": "Syntaxis Labs",
    "business_unit": "Syntaxis Commission Partners",
    "experience": "10 years B2B commission-based sales",
    "buyer_type": "B2B",
    "organization": "Commission-only sales agency",
    "coverage": "Global — remote-first, timezone-flexible",
    "industries": [
        "B2B SaaS", "Artificial Intelligence", "Data Analytics", "Automation",
        "Cybersecurity", "Business Services", "Cloud Computing", "FinTech", "MarTech"
    ],
    "territories": [
        "Global", "North America", "United States", "Canada", "Africa",
        "European Union", "Middle East", "United Kingdom", "Asia-Pacific"
    ],
    "selling_methods": [
        "Appointment Setting", "Online Demos", "Affiliate Link", "Email Outreach",
        "LinkedIn Outreach", "Webinar / Event Lead Gen", "Referral Programs",
        "Channel Partner Development", "Social Selling"
    ],
    "preferred_features": [
        "Recurring Commission", "Residual Commission", "Clear Sales Process",
        "Training Provided", "Sales Materials Provided", "CRM Access Provided",
        "Transparent Reporting", "Demo Environment Provided"
    ],
    "linkedin": "https://www.linkedin.com/in/syntaxis-labs-30829b401/",
    "note": (
        "Syntaxis Labs is an independent commission-based sales representative. "
        "We are not employees of the principal."
    )
}

# ---------------------------------------------------------------------------
# Candidate data (from cca_net_new_candidate_ranking.json)
# ---------------------------------------------------------------------------
CANDIDATES = [
    {
        "opportunity_id": "39292",
        "title": "$1920+/Year Per Enterprise Deal | GDPR-Compliant AI Chatbots | Fast Sales Cycle | Earn 20% Recurring",
        "route": "featured_matching",
        "overall_score": 8.11,
        "scores": {
            "b2b_fit": 9,
            "commission_clarity": 8,
            "residual_terms": 9,
            "territory_scope": 4,
            "sales_enablement": 8,
            "product_credibility": 8,
            "sales_cycle_fit": 9
        },
        "verified_facts": [
            "Commission rates mentioned: [20, 20]%",
            "Residual/recurring commission terms mentioned.",
            "Sales enablement support mentioned (leads, demos, fast cycle, etc.).",
            "Product credibility signals found (patented, enterprise, compliant).",
            "Fast sales cycle explicitly mentioned."
        ],
        "unknowns": [
            "Territory scope not clearly stated."
        ],
        "risks": [],
        "flags": []
    },
    {
        "opportunity_id": "39452",
        "title": "20% LIFETIME Residuals! Managed IT & Cybersecurity Services for SMBs | 100% Retention | Fast Sales Cycle",
        "route": "featured_matching",
        "overall_score": 8.0,
        "scores": {
            "b2b_fit": 9,
            "commission_clarity": 8,
            "residual_terms": 10,
            "territory_scope": 4,
            "sales_enablement": 8,
            "product_credibility": 5,
            "sales_cycle_fit": 9
        },
        "verified_facts": [
            "Commission rates mentioned: [20, 100, 20, 100, 40, 93]%",
            "Residual/recurring commission terms mentioned.",
            "Sales enablement support mentioned (leads, demos, fast cycle, etc.).",
            "Fast sales cycle explicitly mentioned."
        ],
        "unknowns": [
            "Territory scope not clearly stated."
        ],
        "risks": [],
        "flags": []
    }
]

# CommissionCrowd listing URLs (generic, since exact profile URL not in data)
CC_BASE_URL = "https://www.commissioncrowd.com"

def build_body_text(candidate):
    """Build the canonical application body text used for hashing."""
    lines = []
    lines.append("=" * 60)
    lines.append("SYNTAXIS LABS — APPLICATION PACK")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Opportunity ID:        {candidate['opportunity_id']}")
    lines.append(f"Title:                 {candidate['title']}")
    lines.append(f"Source (CommissionCrowd): {CC_BASE_URL}")
    lines.append(f"Route:                 {candidate['route']}")
    lines.append(f"Overall Fit Score:     {candidate['overall_score']}")
    lines.append("")
    lines.append("-" * 40)
    lines.append("WHY THIS FITS SYNTAXIS LABS")
    lines.append("-" * 40)
    lines.append("")
    lines.append("Syntaxis Labs is an independent commission-based sales representative")
    lines.append("operating as Syntaxis Commission Partners. We bring 10 years of B2B")
    lines.append("commission-only sales experience across SaaS, AI, automation, data")
    lines.append("analytics, cybersecurity, and business services.")
    lines.append("")
    if candidate["opportunity_id"] == "39292":
        lines.append("This opportunity aligns well because:")
        lines.append("• The product is a GDPR-compliant AI chatbot — directly within our")
        lines.append("  stated AI and B2B SaaS focus areas.")
        lines.append("• It targets enterprise buyers, matching our B2B sales specialization.")
        lines.append("• Verified commission terms cite 20% recurring/residual commissions,")
        lines.append("  aligning with our preference for residual income models.")
        lines.append("• Sales enablement and a fast sales cycle are explicitly mentioned,")
        lines.append("  supporting rapid pipeline build.")
        lines.append("• Product credibility signals (enterprise-grade, compliant) reduce")
        lines.append("  the trust gap typical in early-stage pitches.")
    elif candidate["opportunity_id"] == "39452":
        lines.append("This opportunity aligns well because:")
        lines.append("• The product covers managed IT and cybersecurity services for SMBs —")
        lines.append("  cybersecurity and business services are core categories for us.")
        lines.append("• Verified commission terms include lifetime residuals, matching our")
        lines.append("  strong preference for long-term recurring commission structures.")
        lines.append("• The fast sales cycle is explicitly stated, enabling quick proof-of")
        lines.append("  concept and early revenue validation.")
        lines.append("• Sales enablement support is mentioned, indicating the principal")
        lines.append("  provides materials or process guidance.")
    lines.append("")
    lines.append("We are independent agents, not employees of the principal.")
    lines.append("")
    lines.append("-" * 40)
    lines.append("PROPOSED SALES MOTION")
    lines.append("-" * 40)
    lines.append("")
    if candidate["opportunity_id"] == "39292":
        lines.append("1. Prospecting: Identify mid-market and enterprise prospects in")
        lines.append("   regulated industries (finance, healthcare, legal) where GDPR")
        lines.append("   compliance is a procurement gate.")
        lines.append("2. Outreach: Use LinkedIn and email sequences to target VP/Director")
        lines.append("   of Customer Experience, Operations, or IT Security.")
        lines.append("3. Demo & Pilot: Schedule online demos; leverage any provided sandbox")
        lines.append("   or pilot environment to demonstrate conversational AI value.")
        lines.append("4. Close: Position ROI around deflected tickets, reduced support")
        lines.append("   headcount, and compliance audit readiness.")
        lines.append("5. Expand: Post-close, introduce add-on modules or additional business")
        lines.append("   units within the same enterprise.")
    elif candidate["opportunity_id"] == "39452":
        lines.append("1. Prospecting: Build lists of SMBs (50–500 employees) without a")
        lines.append("   dedicated internal IT security function — high outsourcing propensity.")
        lines.append("2. Outreach: Run email + LinkedIn campaigns to Owners, CFOs, and")
        lines.append("   Operations Managers citing breach-cost statistics and compliance gaps.")
        lines.append("3. Assessment: Offer a free security posture assessment (if available)")
        lines.append("   or leverage principal-provided audit tools to surface risks.")
        lines.append("4. Close: Package as a monthly retainer with clear SLAs; emphasize")
        lines.append("   the 100% retention claim and rapid onboarding.")
        lines.append("5. Expand: Upsell additional services (backup, compliance training,")
        lines.append("   vCISO) once initial trust is established.")
    lines.append("")
    lines.append("-" * 40)
    lines.append("LIKELY TARGET MARKET")
    lines.append("-" * 40)
    lines.append("")
    if candidate["opportunity_id"] == "39292":
        lines.append("• Enterprise and mid-market companies in GDPR-affected jurisdictions")
        lines.append("  (EU, UK, and global firms handling EU citizen data).")
        lines.append("• Customer support and operations leaders seeking AI-driven")
        lines.append("  automation with audit-ready compliance documentation.")
        lines.append("• SaaS vendors and professional services firms needing white-label")
        lines.append("  or embedded chatbot capabilities.")
    elif candidate["opportunity_id"] == "39452":
        lines.append("• SMBs across North America and the UK lacking in-house cybersecurity")
        lines.append("  expertise or managed IT capacity.")
        lines.append("• Regulated sectors (finance, healthcare, legal) requiring continuous")
        lines.append("  compliance monitoring and incident response.")
        lines.append("• Fast-growing companies scaling operations faster than their internal")
        lines.append("  IT can support.")
    lines.append("")
    lines.append("-" * 40)
    lines.append("FIRST-30-DAY PLAN")
    lines.append("-" * 40)
    lines.append("")
    lines.append("Week 1–2: Onboarding & Intelligence")
    lines.append("• Complete principal-provided training and certification (if required).")
    lines.append("• Review all sales collateral, case studies, pricing sheets, and")
    lines.append("  demo scripts.")
    lines.append("• Set up CRM tracking and reporting workflows.")
    lines.append("• Build an initial prospect list of 150–200 qualified companies")
    lines.append("  matching the target profile.")
    lines.append("")
    lines.append("Week 3: Outreach Launch")
    lines.append("• Begin LinkedIn and email outreach campaigns.")
    lines.append("• A/B test subject lines and value propositions.")
    lines.append("• Aim for 15–20 first conversations.")
    lines.append("")
    lines.append("Week 4: Demo & Pipeline")
    lines.append("• Schedule 5–8 discovery calls or demos.")
    lines.append("• Document objections and feed insights back to the principal.")
    lines.append("• Submit weekly activity and pipeline report.")
    lines.append("")
    lines.append("-" * 40)
    lines.append("RISKS AND UNKNOWNS")
    lines.append("-" * 40)
    lines.append("")
    for u in candidate["unknowns"]:
        lines.append(f"• {u}")
    if candidate["risks"]:
        for r in candidate["risks"]:
            lines.append(f"• {r}")
    else:
        lines.append("• No explicit risks flagged in the scraped listing, but all")
        lines.append("  headline claims (deal size, retention) should be verified")
        lines.append("  during principal onboarding.")
    lines.append("• Product credibility for this listing is rated lower than the")
    lines.append("  top candidate; additional due diligence on case studies and")
    lines.append("  references is advisable before heavy prospecting investment.")
    if candidate["opportunity_id"] == "39292":
        lines.append("• Territory scope is unclear — we must confirm whether our global")
        lines.append("  coverage is acceptable or if the principal restricts regions.")
    elif candidate["opportunity_id"] == "39452":
        lines.append("• Territory scope is unclear — confirm whether SMBs in our covered")
        lines.append("  territories (Global / North America / EU / UK / APAC) are open.")
        lines.append("• Product credibility score (5/10) suggests limited public validation;")
        lines.append("  request reference customers and independent reviews.")
    lines.append("")
    lines.append("-" * 40)
    lines.append("CLARIFICATION QUESTIONS FOR THE PRINCIPAL")
    lines.append("-" * 40)
    lines.append("")
    lines.append("1. What territories are currently open for new reps?")
    lines.append("2. Are there any vertical or account-type exclusions (e.g., no")
    lines.append("   existing customers, no competitors)?")
    lines.append("3. What sales enablement materials are provided (one-pagers, demo")
    lines.append("   accounts, proposal templates, competitive battlecards)?")
    lines.append("4. What is the average time from first contact to signed contract")
    lines.append("   for deals in your current rep base?")
    lines.append("5. How and when are commissions tracked and paid?")
    lines.append("6. Are there minimum activity or quota requirements?")
    lines.append("7. Can you share 2–3 anonymized case studies or reference customers")
    lines.append("   we can cite during prospect conversations?")
    lines.append("")
    lines.append("=" * 60)
    lines.append("END OF APPLICATION BODY")
    lines.append("=" * 60)
    return "\n".join(lines)


def build_markdown(candidate, body_text, payload_hash, timestamp):
    md = f"""# Syntaxis Labs — Application Pack

**Opportunity ID:** {candidate['opportunity_id']}  
**Title:** {candidate['title']}  
**Source:** [CommissionCrowd]({CC_BASE_URL})  
**Route:** {candidate['route']}  
**Generated:** {timestamp}  
**Overall Fit Score:** {candidate['overall_score']}

---

## Operator Profile

| Field | Value |
|-------|-------|
| **Company** | {OPERATOR['company']} |
| **Business Unit** | {OPERATOR['business_unit']} |
| **Experience** | {OPERATOR['experience']} |
| **Buyer Type** | {OPERATOR['buyer_type']} |
| **Organization** | {OPERATOR['organization']} |
| **Coverage** | {OPERATOR['coverage']} |
| **LinkedIn** | [{OPERATOR['linkedin']}]({OPERATOR['linkedin']}) |

> **Note:** {OPERATOR['note']}

---

## Fit Summary

**Why this fits Syntaxis Labs:**

"""
    if candidate["opportunity_id"] == "39292":
        md += """- The product is a GDPR-compliant AI chatbot — directly within our stated AI and B2B SaaS focus areas.
- It targets enterprise buyers, matching our B2B sales specialization.
- Verified commission terms cite **20% recurring/residual commissions**, aligning with our preference for residual income models.
- Sales enablement and a **fast sales cycle** are explicitly mentioned, supporting rapid pipeline build.
- Product credibility signals (enterprise-grade, compliant) reduce the trust gap typical in early-stage pitches.
"""
    elif candidate["opportunity_id"] == "39452":
        md += """- The product covers **managed IT and cybersecurity services for SMBs** — cybersecurity and business services are core categories for us.
- Verified commission terms include **lifetime residuals**, matching our strong preference for long-term recurring commission structures.
- The **fast sales cycle** is explicitly stated, enabling quick proof-of-concept and early revenue validation.
- Sales enablement support is mentioned, indicating the principal provides materials or process guidance.
"""

    md += f"""
---

## Proposed Sales Motion

"""
    if candidate["opportunity_id"] == "39292":
        md += """1. **Prospecting:** Identify mid-market and enterprise prospects in regulated industries (finance, healthcare, legal) where GDPR compliance is a procurement gate.
2. **Outreach:** Use LinkedIn and email sequences to target VP/Director of Customer Experience, Operations, or IT Security.
3. **Demo & Pilot:** Schedule online demos; leverage any provided sandbox or pilot environment to demonstrate conversational AI value.
4. **Close:** Position ROI around deflected tickets, reduced support headcount, and compliance audit readiness.
5. **Expand:** Post-close, introduce add-on modules or additional business units within the same enterprise.
"""
    elif candidate["opportunity_id"] == "39452":
        md += """1. **Prospecting:** Build lists of SMBs (50–500 employees) without a dedicated internal IT security function — high outsourcing propensity.
2. **Outreach:** Run email + LinkedIn campaigns to Owners, CFOs, and Operations Managers citing breach-cost statistics and compliance gaps.
3. **Assessment:** Offer a free security posture assessment (if available) or leverage principal-provided audit tools to surface risks.
4. **Close:** Package as a monthly retainer with clear SLAs; emphasize the 100% retention claim and rapid onboarding.
5. **Expand:** Upsell additional services (backup, compliance training, vCISO) once initial trust is established.
"""

    md += f"""
---

## Likely Target Market

"""
    if candidate["opportunity_id"] == "39292":
        md += """- Enterprise and mid-market companies in GDPR-affected jurisdictions (EU, UK, and global firms handling EU citizen data).
- Customer support and operations leaders seeking AI-driven automation with audit-ready compliance documentation.
- SaaS vendors and professional services firms needing white-label or embedded chatbot capabilities.
"""
    elif candidate["opportunity_id"] == "39452":
        md += """- SMBs across North America and the UK lacking in-house cybersecurity expertise or managed IT capacity.
- Regulated sectors (finance, healthcare, legal) requiring continuous compliance monitoring and incident response.
- Fast-growing companies scaling operations faster than their internal IT can support.
"""

    md += f"""
---

## First-30-Day Plan

### Week 1–2: Onboarding & Intelligence
- Complete principal-provided training and certification (if required).
- Review all sales collateral, case studies, pricing sheets, and demo scripts.
- Set up CRM tracking and reporting workflows.
- Build an initial prospect list of 150–200 qualified companies matching the target profile.

### Week 3: Outreach Launch
- Begin LinkedIn and email outreach campaigns.
- A/B test subject lines and value propositions.
- Aim for 15–20 first conversations.

### Week 4: Demo & Pipeline
- Schedule 5–8 discovery calls or demos.
- Document objections and feed insights back to the principal.
- Submit weekly activity and pipeline report.

---

## Risks and Unknowns

"""
    for u in candidate["unknowns"]:
        md += f"- {u}\n"
    if candidate["risks"]:
        for r in candidate["risks"]:
            md += f"- {r}\n"
    else:
        md += "- No explicit risks flagged in the scraped listing, but all headline claims (deal size, retention) should be verified during principal onboarding.\n"

    if candidate["opportunity_id"] == "39292":
        md += "- Territory scope is unclear — we must confirm whether our global coverage is acceptable or if the principal restricts regions.\n"
    elif candidate["opportunity_id"] == "39452":
        md += "- Territory scope is unclear — confirm whether SMBs in our covered territories (Global / North America / EU / UK / APAC) are open.\n"
        md += "- Product credibility score (5/10) suggests limited public validation; request reference customers and independent reviews.\n"

    md += f"""
---

## Clarification Questions for the Principal

1. What territories are currently open for new reps?
2. Are there any vertical or account-type exclusions (e.g., no existing customers, no competitors)?
3. What sales enablement materials are provided (one-pagers, demo accounts, proposal templates, competitive battlecards)?
4. What is the average time from first contact to signed contract for deals in your current rep base?
5. How and when are commissions tracked and paid?
6. Are there minimum activity or quota requirements?
7. Can you share 2–3 anonymized case studies or reference customers we can cite during prospect conversations?

---

## Integrity Metadata

| Field | Value |
|-------|-------|
| **Payload Hash (SHA-256)** | `{payload_hash}` |
| **Opportunity ID** | {candidate['opportunity_id']} |
| **Action Type** | `apply_to_principal` |
| **Timestamp** | {timestamp} |

> The SHA-256 hash above is computed over the exact canonical application body text combined with the action metadata (`opportunity_id`, `action_type`, `timestamp`). This ensures content integrity and non-repudiation for downstream approval workflows.
"""
    return md


def build_json(candidate, body_text, payload_hash, timestamp):
    return {
        "operator_profile": {
            "company": OPERATOR["company"],
            "business_unit": OPERATOR["business_unit"],
            "experience": OPERATOR["experience"],
            "buyer_type": OPERATOR["buyer_type"],
            "organization_type": OPERATOR["organization"],
            "coverage": OPERATOR["coverage"],
            "industries": OPERATOR["industries"],
            "territories": OPERATOR["territories"],
            "selling_methods": OPERATOR["selling_methods"],
            "preferred_features": OPERATOR["preferred_features"],
            "linkedin": OPERATOR["linkedin"],
            "disclaimer": OPERATOR["note"]
        },
        "opportunity": {
            "opportunity_id": candidate["opportunity_id"],
            "title": candidate["title"],
            "source_url": CC_BASE_URL,
            "route": candidate["route"],
            "overall_score": candidate["overall_score"],
            "scores": candidate["scores"],
            "verified_facts": candidate["verified_facts"],
            "unknowns": candidate["unknowns"],
            "risks": candidate["risks"],
            "flags": candidate["flags"]
        },
        "application_body": body_text,
        "fit_summary": {
            "b2b_alignment": "High — product category matches operator industries (AI/SaaS or Cybersecurity/Business Services).",
            "commission_alignment": "Verified residual/recurring terms present.",
            "sales_cycle_alignment": "Fast sales cycle explicitly mentioned." if candidate["opportunity_id"] in ("39292", "39452") else "Not specified."
        },
        "proposed_sales_motion": {
            "39292": [
                "Prospecting: Identify mid-market and enterprise prospects in regulated industries (finance, healthcare, legal) where GDPR compliance is a procurement gate.",
                "Outreach: Use LinkedIn and email sequences to target VP/Director of Customer Experience, Operations, or IT Security.",
                "Demo & Pilot: Schedule online demos; leverage any provided sandbox or pilot environment to demonstrate conversational AI value.",
                "Close: Position ROI around deflected tickets, reduced support headcount, and compliance audit readiness.",
                "Expand: Post-close, introduce add-on modules or additional business units within the same enterprise."
            ],
            "39452": [
                "Prospecting: Build lists of SMBs (50–500 employees) without a dedicated internal IT security function — high outsourcing propensity.",
                "Outreach: Run email + LinkedIn campaigns to Owners, CFOs, and Operations Managers citing breach-cost statistics and compliance gaps.",
                "Assessment: Offer a free security posture assessment (if available) or leverage principal-provided audit tools to surface risks.",
                "Close: Package as a monthly retainer with clear SLAs; emphasize the 100% retention claim and rapid onboarding.",
                "Expand: Upsell additional services (backup, compliance training, vCISO) once initial trust is established."
            ]
        }[candidate["opportunity_id"]],
        "likely_target_market": {
            "39292": [
                "Enterprise and mid-market companies in GDPR-affected jurisdictions (EU, UK, and global firms handling EU citizen data).",
                "Customer support and operations leaders seeking AI-driven automation with audit-ready compliance documentation.",
                "SaaS vendors and professional services firms needing white-label or embedded chatbot capabilities."
            ],
            "39452": [
                "SMBs across North America and the UK lacking in-house cybersecurity expertise or managed IT capacity.",
                "Regulated sectors (finance, healthcare, legal) requiring continuous compliance monitoring and incident response.",
                "Fast-growing companies scaling operations faster than their internal IT can support."
            ]
        }[candidate["opportunity_id"]],
        "first_30_day_plan": {
            "week_1_2": [
                "Complete principal-provided training and certification (if required).",
                "Review all sales collateral, case studies, pricing sheets, and demo scripts.",
                "Set up CRM tracking and reporting workflows.",
                "Build an initial prospect list of 150–200 qualified companies matching the target profile."
            ],
            "week_3": [
                "Begin LinkedIn and email outreach campaigns.",
                "A/B test subject lines and value propositions.",
                "Aim for 15–20 first conversations."
            ],
            "week_4": [
                "Schedule 5–8 discovery calls or demos.",
                "Document objections and feed insights back to the principal.",
                "Submit weekly activity and pipeline report."
            ]
        },
        "risks_and_unknowns": candidate["unknowns"] + (candidate["risks"] if candidate["risks"] else ["No explicit risks flagged in the scraped listing, but all headline claims (deal size, retention) should be verified during principal onboarding."]),
        "clarification_questions": [
            "What territories are currently open for new reps?",
            "Are there any vertical or account-type exclusions (e.g., no existing customers, no competitors)?",
            "What sales enablement materials are provided (one-pagers, demo accounts, proposal templates, competitive battlecards)?",
            "What is the average time from first contact to signed contract for deals in your current rep base?",
            "How and when are commissions tracked and paid?",
            "Are there minimum activity or quota requirements?",
            "Can you share 2–3 anonymized case studies or reference customers we can cite during prospect conversations?"
        ],
        "integrity": {
            "payload_hash_sha256": payload_hash,
            "opportunity_id": candidate["opportunity_id"],
            "action_type": "apply_to_principal",
            "timestamp": timestamp,
            "hash_computation_note": "SHA-256 computed over canonical application body text concatenated with action metadata (opportunity_id + action_type + timestamp)."
        }
    }


def main():
    out_dir = "/home/ubuntu/hermes-control/reports/cca_application_packs"
    os.makedirs(out_dir, exist_ok=True)

    for cand in CANDIDATES:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = build_body_text(cand)
        # Compute hash over body + action metadata
        hash_input = body + cand["opportunity_id"] + "apply_to_principal" + ts
        payload_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

        md_path = os.path.join(out_dir, f"cca_app_pack_{cand['opportunity_id']}.md")
        json_path = os.path.join(out_dir, f"cca_app_pack_{cand['opportunity_id']}.json")

        md_content = build_markdown(cand, body, payload_hash, ts)
        json_content = build_json(cand, body, payload_hash, ts)

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_content, f, indent=2, ensure_ascii=False)

        print(f"Written: {md_path}")
        print(f"Written: {json_path}")
        print(f"  Hash: {payload_hash}")
        print(f"  Timestamp: {ts}")
        print()


if __name__ == "__main__":
    main()
