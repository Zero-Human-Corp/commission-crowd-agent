"""CommissionCrowd browser adapter — authenticated page inspection.

Provides safe navigation of account-specific pages without application
submission, message sending, or any consequential platform action.

All credentials come from the shared secrets mechanism only.
Session cookies are stored in a restricted runtime path outside Git.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # type: ignore[assignment]

console = Console()


@dataclass
class BrowserSession:
    """Lightweight session state for CommissionCrowd browser inspection."""

    cookies: list[dict[str, Any]] = field(default_factory=list)
    logged_in: bool = False
    username: str = ""
    last_activity: str = ""
    session_path: Path | None = None

    def save(self, path: Path) -> None:
        """Persist cookies and state to disk securely."""
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        payload = {
            "logged_in": self.logged_in,
            "username": self.username,
            "last_activity": self.last_activity,
            "cookies": self.cookies,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)

    @classmethod
    def load(cls, path: Path) -> BrowserSession | None:
        """Restore a session if the file exists and is not stale."""
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            session = cls(
                cookies=data.get("cookies", []),
                logged_in=data.get("logged_in", False),
                username=data.get("username", ""),
                last_activity=data.get("last_activity", ""),
                session_path=path,
            )
            if session.last_activity:
                try:
                    last = datetime.fromisoformat(session.last_activity)
                    if (datetime.now(UTC) - last).total_seconds() > 4 * 3600:
                        console.print("[yellow]Browser session stale (>4h), will re-auth.[/yellow]")
                        return None
                except ValueError:
                    return None
            return session
        except (json.JSONDecodeError, OSError):
            return None


@dataclass
class CommissionCrowdBrowserAdapter:
    """Adapter for navigating CommissionCrowd account pages via Playwright.

    Non-negotiable constraints:
    - No application submission.
    - No message sending.
    - No email sending.
    - No automatic approval.
    - Credentials never logged or stored in source.
    - Session cookies stored only in the configured runtime path.
    """

    base_url: str = "https://www.commissioncrowd.com"
    session_runtime_dir: Path = field(
        default_factory=lambda: Path.home() / ".local" / "share" / "cca" / "browser_sessions"
    )
    _browser: Any = None
    _page: Any = None
    _session: BrowserSession | None = None

    def _session_path(self, username: str) -> Path:
        safe = "".join(c for c in username if c.isalnum() or c in "._-")
        return self.session_runtime_dir / f"session_{safe}.json"

    # ── Session management ───────────────────────────────────────────────

    def start(self, headless: bool = True) -> CommissionCrowdBrowserAdapter:
        """Launch the browser.  Safe to call multiple times."""
        if sync_playwright is None:
            raise RuntimeError("Playwright is not installed.")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._page = self._browser.new_page(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        return self

    def close(self) -> None:
        """Close browser and optionally persist session cookies."""
        if self._session and self._session.session_path:
            try:
                if self._page:
                    self._session.cookies = self._page.context.cookies()
                    self._session.save(self._session.session_path)
            except Exception:
                pass
        if self._browser:
            self._browser.close()
            self._browser = None
        if hasattr(self, "_pw") and self._pw:
            self._pw.stop()
            delattr(self, "_pw")
        self._page = None

    def login_or_restore_session(
        self,
        username: str,
        password: str,
        *,
        force_new: bool = False,
    ) -> BrowserSession:
        """Authenticate or restore an existing session.

        Raises RuntimeError on CAPTCHA / MFA / unexpected interstitial.
        """
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")

        path = self._session_path(username)
        if not force_new:
            restored = BrowserSession.load(path)
            if restored and restored.logged_in and restored.cookies:
                self._page.context.add_cookies(restored.cookies)
                self._page.goto(f"{self.base_url}/app", wait_until="networkidle", timeout=30000)
                if self._detect_dashboard():
                    self._session = restored
                    restored.last_activity = datetime.now(UTC).isoformat()
                    console.print("[green]Browser session restored.[/green]")
                    return restored
                # Cookies didn't stick – fall through to fresh login

        # Fresh login via login form
        self._page.goto(f"{self.base_url}/login", wait_until="domcontentloaded", timeout=30000)
        html = self._page.content().lower()
        if "captcha" in html or "recaptcha" in html:
            raise RuntimeError("CAPTCHA detected – operator intervention required.")

        self._page.fill('input[type="email"]', username)
        self._page.fill('input[type="password"]', password)
        self._page.click('button[type="submit"]')
        # SPA navigation: poll for dashboard text rather than strict networkidle
        # which may never fire on SPAs with continuous polling
        self._page.wait_for_timeout(3000)
        for _ in range(15):
            if self._detect_dashboard():
                break
            self._page.wait_for_timeout(1000)
        else:
            # If dashboard never detected, still check URL/content
            pass

        # Post-login checks
        url = self._page.url
        html = self._page.content().lower()

        # Check for actual verification code INPUT (not just the word "code" in body text)
        code_input_present = (
            self._page.locator('input[placeholder*="code" i]').count() > 0
            or self._page.locator('input[placeholder*="verification" i]').count() > 0
            or self._page.locator('input[name*="code" i]').count() > 0
            or self._page.locator('input[id*="otp" i]').count() > 0
        )
        twofa_text_present = "two-factor" in html or "two step" in html or "authenticator" in html
        if code_input_present and twofa_text_present:
            raise RuntimeError("MFA/2FA detected – operator intervention required.")

        if "invalid" in html and self._page.locator("text=Invalid").count() > 0:
            raise RuntimeError("Login failed – invalid credentials.")
        if not self._detect_dashboard():
            raise RuntimeError(f"Login succeeded but dashboard not detected. Current URL: {url}")

        self._session = BrowserSession(
            cookies=self._page.context.cookies(),
            logged_in=True,
            username=username,
            last_activity=datetime.now(UTC).isoformat(),
            session_path=path,
        )
        self._session.save(path)
        console.print("[green]Browser session authenticated and saved.[/green]")
        return self._session

    def _detect_dashboard(self) -> bool:
        """Return True if the current page shows authenticated dashboard chrome."""
        if self._page is None:
            return False
        return bool(
            self._page.locator("text=Dashboard").count() > 0
            or self._page.locator("text=My Opportunities").count() > 0
            or self._page.locator("text=Find opportunities").count() > 0
            or self._page.locator("text=Applications").count() > 0
        )

    def _require_auth(self) -> None:
        if self._session is None or not self._session.logged_in:
            raise RuntimeError("No active browser session. Call login_or_restore_session first.")

    # ── Navigation helpers (SPA-aware) ───────────────────────────────────

    def _goto_tool(self, tool_name: str, wait_selector: str = "", timeout: int = 15000) -> None:
        """Navigate to a tool by direct URL hash, falling back to sidebar click."""
        self._require_auth()
        # Direct URL mapping for SPA routes
        route_map = {
            "my opportunities": "/app/#/agent/my-opportunities",
            "my_opportunities": "/app/#/agent/my-opportunities",
            "opportunities": "/app/#/agent/my-opportunities",
            "conversations": "/app/#/agent/conversations",
            "messages": "/app/#/agent/conversations",
            "favourite opportunities": "/app/#/agent/favourites",
            "favourite_opportunities": "/app/#/agent/favourites",
            "find opportunities": "/app/#/opportunities/search",
            "find_opportunities": "/app/#/opportunities/search",
            "applications": "/app/#/agent/applications",
        }
        lower_tool = tool_name.lower()
        if lower_tool in route_map:
            self._page.goto(
                f"{self.base_url}{route_map[lower_tool]}",
                wait_until="networkidle",
                timeout=30000,
            )
            self._page.wait_for_timeout(3000)
            return

        # Fallback: click sidebar
        selectors = [
            f"text={tool_name}",
            f'[title="{tool_name}"]',
        ]
        for sel in selectors:
            if self._page.locator(sel).count() > 0:
                self._page.click(sel)
                break
        else:
            raise RuntimeError(f"Sidebar tool '{tool_name}' not found.")
        if wait_selector:
            self._page.wait_for_selector(wait_selector, timeout=timeout)
        else:
            self._page.wait_for_timeout(3000)

    # ── Discovery methods ───────────────────────────────────────────────

    def list_my_opportunities(self) -> list[dict[str, Any]]:
        """Return active opportunities under My Opportunities."""
        self._require_auth()
        try:
            self._goto_tool("My Opportunities")
        except RuntimeError:
            # Fallback – click Opportunities in sidebar
            self._page.click("text=Opportunities")
            self._page.wait_for_timeout(3000)

        items: list[dict[str, Any]] = []
        body = self._page.locator("body")
        text = body.inner_text()

        # If empty
        if "not working on any opportunities" in text.lower():
            return items

        # Try to extract from table or card grid
        rows = self._extract_opportunity_cards()
        for row in rows:
            opp_id = self._infer_opportunity_id(row.get("source_url", ""))
            items.append(
                {
                    "opportunity_id": opp_id,
                    "title": row.get("title", ""),
                    "principal_name": row.get("principal_name", ""),
                    "status": row.get("status", "active"),
                    "commission_summary": row.get("commission_text", ""),
                    "relationship_stage": "active",
                    "source_url": row.get("source_url", ""),
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "route": "my_opportunities",
                }
            )
        return items

    def list_messages(self) -> list[dict[str, Any]]:
        """Return inbox messages."""
        self._require_auth()
        self._goto_tool("Conversations")
        body = self._page.locator("body")
        text = body.inner_text()
        if "no unread" in text.lower() and "no conversations" in text.lower():
            return []

        messages: list[dict[str, Any]] = []
        # Heuristic: rows in a conversation list have Date / From / Subject headers
        table_rows = self._page.locator(
            "table tbody tr, .conversation-list-item, .message-row"
        ).all()
        for row in table_rows[:50]:  # bounded
            cells = row.locator("td").all_inner_texts()
            if len(cells) >= 3:
                messages.append(
                    {
                        "message_id": f"msg-{hash(cells[0] + cells[1]) % 100000}",
                        "sender": cells[1][:100],
                        "timestamp": cells[0][:50],
                        "subject": cells[2][:200],
                        "classification": "uncertain",
                        "retrieved_at": datetime.now(UTC).isoformat(),
                        "route": "conversations",
                    }
                )
        return messages

    def extract_invitation_messages(
        self, messages: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """Classify messages and return invitation-like records."""
        if messages is None:
            messages = self.list_messages()
        invitations: list[dict[str, Any]] = []
        invite_keywords = {
            "explicit_invitation": [
                "invite",
                "invitation",
                "apply now",
                "represent",
                "would love you to",
                "accept",
                "join us",
            ],
            "likely_invitation": [
                "opportunity",
                "interested",
                "connect",
                "discuss",
            ],
        }
        for msg in messages:
            subj_lower = msg.get("subject", "").lower()
            body_lower = msg.get("body", "").lower()
            combined = f"{subj_lower} {body_lower}"

            classification = "uncertain"
            for level, keywords in invite_keywords.items():
                if any(kw in combined for kw in keywords):
                    classification = level
                    break

            # Cross-reference with existing opportunities
            linked_opp_id = self._extract_opp_id_from_text(combined)
            msg["classification"] = classification
            msg["linked_opportunity_id"] = linked_opp_id
            msg["invitation_confidence"] = classification

            if classification in ("explicit_invitation", "likely_invitation"):
                invitations.append(msg)
        return invitations

    def list_favourite_opportunities(self) -> list[dict[str, Any]]:
        """Return all opportunities under Favourite Opportunities."""
        self._require_auth()
        self._goto_tool("Favourite opportunities")
        return self._extract_opportunity_cards(route="favourite_opportunities")

    def search_find_opportunities(
        self,
        query: str = "",
        *,
        page_limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search Find Opportunities with bounded pagination."""
        self._require_auth()
        # Navigate to search
        try:
            self._goto_tool("Find opportunities")
        except RuntimeError:
            # Direct navigation
            self._page.goto(
                f"{self.base_url}/app/opportunities/search",
                wait_until="networkidle",
                timeout=30000,
            )

        # Fill search if query provided
        if query:
            search_input = self._page.locator(
                'input[placeholder*="search" i], input[type="search"]'
            )
            if search_input.count() > 0:
                search_input.first.fill(query)
                self._page.keyboard.press("Enter")
                self._page.wait_for_timeout(3000)

        all_results: list[dict[str, Any]] = []
        for _page_num in range(page_limit):
            results = self._extract_opportunity_cards(route="find_opportunities")
            all_results.extend(results)
            # Try next page
            next_btn = self._page.locator(
                'text=Next, button:has-text("Next"), [aria-label="Next"]'
            ).first
            if next_btn.count() == 0 or not next_btn.is_visible():
                break
            next_btn.click()
            self._page.wait_for_timeout(3000)
        return all_results

    def read_opportunity_detail(self, reference: str) -> dict[str, Any]:
        """Open an opportunity detail page and extract structured data."""
        self._require_auth()
        url = reference
        if not url.startswith("http"):
            url = f"{self.base_url}/app/opportunities/{reference}"
        self._page.goto(url, wait_until="networkidle", timeout=30000)
        self._page.wait_for_timeout(2000)
        return self._extract_opportunity_detail()

    def logout_or_secure_session(self) -> None:
        """Clear the in-memory session and save cookies if valid."""
        if self._session and self._session.session_path:
            try:
                if self._page:
                    self._session.cookies = self._page.context.cookies()
                    self._session.save(self._session.session_path)
            except Exception:
                pass
        self._session = None

    # ── Extraction internals ────────────────────────────────────────────

    def _extract_opportunity_cards(
        self,
        route: str = "",
    ) -> list[dict[str, Any]]:
        """Extract opportunity cards/cells from the current page."""
        items: list[dict[str, Any]] = []
        # Strategy 1: table rows
        rows = self._page.locator("table tbody tr").all()
        for row in rows:
            cells = row.locator("td").all_inner_texts()
            if len(cells) >= 2:
                title = cells[0][:200]
                opp_id = self._extract_opp_id_from_text(
                    title + " " + (cells[1] if len(cells) > 1 else "")
                )
                items.append(
                    {
                        "opportunity_id": opp_id,
                        "title": title,
                        "commission_text": cells[1][:300] if len(cells) > 1 else "",
                        "status": cells[2] if len(cells) > 2 else "",
                        "source_url": "",
                        "retrieved_at": datetime.now(UTC).isoformat(),
                        "route": route,
                    }
                )

        # Strategy 2: card-style divs with opportunity text
        if not items:
            # Try to find divs with dollar signs / percentages (commission clues)
            card_texts = self._page.locator(
                '.opportunity-card, .opportunity-item, [class*="opportunity"]'
            ).all_inner_texts()
            for txt in card_texts[:100]:
                lines = [line.strip() for line in txt.split("\n") if line.strip()]
                if len(lines) >= 2:
                    title = lines[0][:200]
                    commission = lines[1][:300]
                    opp_id = self._extract_opp_id_from_text(txt)
                    items.append(
                        {
                            "opportunity_id": opp_id,
                            "title": title,
                            "commission_text": commission,
                            "status": "",
                            "source_url": "",
                            "retrieved_at": datetime.now(UTC).isoformat(),
                            "route": route,
                        }
                    )

        # Strategy 3: any links containing /opportunity/
        if not items:
            links = self._page.locator('a[href*="/opportunity/"]').all()
            for link in links[:100]:
                href = link.get_attribute("href") or ""
                text = link.inner_text()[:200]
                opp_id = self._infer_opportunity_id(href)
                if opp_id and text:
                    items.append(
                        {
                            "opportunity_id": opp_id,
                            "title": text,
                            "commission_text": "",
                            "status": "",
                            "source_url": f"{self.base_url}{href}",
                            "retrieved_at": datetime.now(UTC).isoformat(),
                            "route": route,
                        }
                    )

        return items

    def _extract_opportunity_detail(self) -> dict[str, Any]:
        """Extract structured fields from an opportunity detail page."""
        body = self._page.locator("body")
        text = body.inner_text()
        return {
            "opportunity_id": self._infer_opportunity_id(self._page.url),
            "title": self._page.title(),
            "description_snippet": text[:1000],
            "source_url": self._page.url,
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _infer_opportunity_id(url_or_text: str) -> str:
        """Try to extract a numeric opportunity ID from URL or text."""
        import re

        m = re.search(r"/opportunity[s/]+(\d+)", url_or_text)
        if m:
            return m.group(1)
        # Fallback: first standalone 5-digit number
        m = re.search(r"\b(\d{5,})\b", url_or_text)
        if m:
            return m.group(1)
        return ""

    @staticmethod
    def _extract_opp_id_from_text(text: str) -> str:
        """Look for opportunity references in message text."""
        import re

        m = re.search(r"\b(\d{5,})\b", text)
        if m:
            return m.group(1)
        return ""

    @staticmethod
    def sanitize_inventory(items: list[dict[str, Any]]) -> dict[str, Any]:
        """Create a sanitized inventory report with no personal data."""
        return {
            "retrieved_at": datetime.now(UTC).isoformat(),
            "count": len(items),
            "items": [
                {
                    "opportunity_id": item.get("opportunity_id", ""),
                    "title": item.get("title", "")[:80],
                    "status": item.get("status", ""),
                    "classification": item.get("classification", ""),
                }
                for item in items
            ],
        }
