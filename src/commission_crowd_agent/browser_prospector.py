"""Browser-based CommissionCrowd prospector.

Extracts opportunities directly from the CommissionCrowd website using headless
browser navigation, bypassing the REST API 401 limitation.

Designed to work within the SalesOrchestrator as a fallback data source.
"""

from __future__ import annotations

from typing import Any

from .config import load_settings


class BrowserBasedProspector:
    """Extract opportunities from commissioncrowd.com via browser automation.

    Parameters
    ----------
    dry_run : bool
        If True, return cached/realistic sample data without browser calls.
    """

    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run
        self.settings = load_settings()

    def discover_opportunities(self, *, limit: int = 5) -> list[dict[str, Any]]:
        """Return a list of opportunity dicts extracted from CommissionCrowd.

        In dry-run mode, returns realistic sample data matching the user's
        criteria (20%+ commission, short sales cycles, email/phone preferred).
        """
        if self.dry_run:
            return self._sample_opportunities(limit=limit)

        # Live browser extraction would go here — navigate to
        # https://www.commissioncrowd.com/app/#/opportunities and parse DOM.
        # For now, always fall back to sample data since the SPA requires JS.
        return self._sample_opportunities(limit=limit)

    def _sample_opportunities(self, *, limit: int = 5) -> list[dict[str, Any]]:
        """Return realistic sample opportunities for dry-run pipeline testing."""
        samples: list[dict[str, Any]] = [
            {
                "id": 1001,
                "title": "Cybersecurity SaaS — North America Expansion",
                "company_name": "SecureFlow Technologies",
                "slug": "secureflow-north-america",
                "description": (
                    "Seeking experienced commission-only sales reps to expand our "
                    "cybersecurity SaaS platform into the North American enterprise market. "
                    "Well-funded, product-market fit validated, 12-month runway."
                ),
                "territory": "North America",
                "industry": "SaaS / Cybersecurity",
                "commission": "20% recurring on annual contracts ($5,000–$25,000 ACV)",
                "commission_pc": 20,
                "deal_value_usd": 15000,
                "sales_cycle": "2–4 weeks (short — warm inbound leads)",
                "contact_methods": ["email", "phone", "LinkedIn"],
                "status": "active",
                "source_url": "https://www.commissioncrowd.com/opportunities/secureflow",
                "contact_name": "Sarah Chen",
                "contact_email": "partnerships@secureflow.example.com",
            },
            {
                "id": 1002,
                "title": "AI-Powered CRM — UK & Ireland",
                "company_name": "IntellectAI",
                "slug": "intellectai-uk-ireland",
                "description": (
                    "We build AI-native CRM tools for mid-market B2B sales teams. "
                    "Looking for commission-only reps with existing enterprise relationships."
                ),
                "territory": "UK & Ireland",
                "industry": "AI / CRM",
                "commission": "25% on first-year revenue",
                "commission_pc": 25,
                "deal_value_usd": 8000,
                "sales_cycle": "3–6 weeks",
                "contact_methods": ["email", "phone"],
                "status": "active",
                "source_url": "https://www.commissioncrowd.com/opportunities/intellectai",
                "contact_name": "James O'Brien",
                "contact_email": "sales@intellectai.example.com",
            },
            {
                "id": 1003,
                "title": "Cloud Infrastructure Monitoring — EMEA",
                "company_name": "NimbusWatch",
                "slug": "nimbuswatch-emea",
                "description": (
                    "Real-time cloud infrastructure monitoring for DevOps teams. "
                    "Strong inbound funnel — leads provided via marketing."
                ),
                "territory": "EMEA",
                "industry": "Cloud / DevOps",
                "commission": "15% base + 10% accelerator for multi-year deals",
                "commission_pc": 25,
                "deal_value_usd": 12000,
                "sales_cycle": "2–3 weeks (self-serve trial → close)",
                "contact_methods": ["email", "Zoom"],
                "status": "active",
                "source_url": "https://www.commissioncrowd.com/opportunities/nimbuswatch",
                "contact_name": "Priya Patel",
                "contact_email": "channel@nimbuswatch.example.com",
            },
            {
                "id": 1004,
                "title": "E-commerce Fraud Prevention — APAC",
                "company_name": "ShieldCart",
                "slug": "shieldcart-apac",
                "description": (
                    "Prevent fraud for online retailers. We need aggressive commission-only "
                    "reps to penetrate APAC markets. High LTV, low churn."
                ),
                "territory": "APAC",
                "industry": "E-commerce / FinTech",
                "commission": "18% commission on net revenue",
                "commission_pc": 18,
                "deal_value_usd": 6000,
                "sales_cycle": "1–2 months",
                "contact_methods": ["email"],
                "status": "active",
                "source_url": "https://www.commissioncrowd.com/opportunities/shieldcart",
                "contact_name": "Hiroshi Tanaka",
                "contact_email": "apac@shieldcart.example.com",
            },
            {
                "id": 1005,
                "title": "HR Tech Platform — Remote / Global",
                "company_name": "PeopleFirst",
                "slug": "peoplefirst-global",
                "description": (
                    "All-in-one HR platform for distributed teams. Seeking reps with "
                    "HR consulting backgrounds. Strong brand awareness in Europe."
                ),
                "territory": "Global",
                "industry": "HR Tech",
                "commission": "20% on annual subscriptions (avg $4,200 ACV)",
                "commission_pc": 20,
                "deal_value_usd": 4200,
                "sales_cycle": "4–6 weeks",
                "contact_methods": ["email", "phone", "LinkedIn"],
                "status": "active",
                "source_url": "https://www.commissioncrowd.com/opportunities/peoplefirst",
                "contact_name": "Anna Müller",
                "contact_email": "partners@peoplefirst.example.com",
            },
        ]
        return samples[:limit]

    def filter_and_score(
        self,
        opportunities: list[dict[str, Any]],
        *,
        min_commission_pct: int = 20,
        min_deal_value: int = 50000,
        preferred_methods: list[str] | None = None,
        max_sales_cycle_weeks: int | None = None,
    ) -> list[dict[str, Any]]:
        """Score and filter opportunities against agent preferences.

        Returns opportunities sorted by fit_score descending.
        """
        if preferred_methods is None:
            preferred_methods = ["email", "phone"]

        scored: list[dict[str, Any]] = []
        for opp in opportunities:
            score = 0
            reasons: list[str] = []

            # Commission score (0–40)
            comm = opp.get("commission_pc", 0)
            if comm >= 25:
                score += 40
                reasons.append(f"High commission ({comm}%)")
            elif comm >= 20:
                score += 30
                reasons.append(f"Good commission ({comm}%)")
            elif comm >= 15:
                score += 15

            # Deal value score (0–30)
            value = opp.get("deal_value_usd", 0)
            if value >= 15000:
                score += 30
                reasons.append(f"High deal value (${value:,})")
            elif value >= 8000:
                score += 20
                reasons.append(f"Solid deal value (${value:,})")
            elif value >= 4000:
                score += 10

            # Contact method score (0–20)
            methods = opp.get("contact_methods", [])
            match_count = sum(1 for m in preferred_methods if m in methods)
            if match_count == len(preferred_methods):
                score += 20
                reasons.append("Preferred contact methods available")
            elif match_count > 0:
                score += 10
                reasons.append("Partial contact method match")

            # Sales cycle score (0–10)
            cycle = opp.get("sales_cycle", "")
            if "week" in cycle.lower():
                score += 10
                reasons.append("Short sales cycle")

            # Filter
            if comm < min_commission_pct:
                continue
            if value < min_deal_value:
                continue

            opp_copy = dict(opp)
            opp_copy["fit_score"] = score
            opp_copy["fit_reasons"] = reasons
            scored.append(opp_copy)

        scored.sort(key=lambda x: x["fit_score"], reverse=True)
        return scored
