# Graph Report - commission-crowd-agent  (2026-06-09)

## Corpus Check
- 86 files · ~100,238 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1004 nodes · 1826 edges · 80 communities (61 shown, 19 thin omitted)
- Extraction: 68% EXTRACTED · 32% INFERRED · 0% AMBIGUOUS · INFERRED: 585 edges (avg confidence: 0.75)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `14940652`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]

## God Nodes (most connected - your core abstractions)
1. `GoogleSheetsAdapter` - 68 edges
2. `SupervisorRelay` - 58 edges
3. `ApprovalGate` - 55 edges
4. `NotifierAdapter` - 46 edges
5. `OperatorSource` - 45 edges
6. `OperatorSourceIngester` - 38 edges
7. `LeadScorer` - 38 edges
8. `_make_settings()` - 34 edges
9. `LeadIngester` - 32 edges
10. `Lead` - 30 edges

## Surprising Connections (you probably didn't know these)
- `test_lead_defaults()` --calls--> `Lead`  [INFERRED]
  tests/test_domain.py → src/commission_crowd_agent/domain.py
- `test_lead_email_lowercased()` --calls--> `Lead`  [INFERRED]
  tests/test_domain.py → src/commission_crowd_agent/domain.py
- `test_lead_to_sheet_row()` --calls--> `Lead`  [INFERRED]
  tests/test_domain.py → src/commission_crowd_agent/domain.py
- `test_load_settings_from_env()` --calls--> `load_settings()`  [INFERRED]
  tests/test_config.py → src/commission_crowd_agent/config.py
- `test_env_var_precedence_over_shared_env()` --calls--> `load_settings()`  [INFERRED]
  tests/test_config.py → src/commission_crowd_agent/config.py

## Communities (80 total, 19 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (39): _error_result(), GoogleSheetsAdapter, _index_to_column_letter(), Google Sheets adapter for reading/writing pipeline state.      Uses the Google S, Return Authorization header with current access token., Generate an access token from service-account credentials if needed.          On, Verify the spreadsheet is reachable.          Returns a structured result dict w, Read all rows from a tab (including header).          Returns structured result (+31 more)

### Community 1 - "Community 1"
Cohesion: 0.09
Nodes (55): Local-only supervisor relay with task-type routing and hard action blocks., Return a secret-free summary of relay configuration., SupervisorRelay, MagicMock, _make_settings(), _mock_response(), _patch_available(), Tests for the Supervisor Relay — local model routing, schema validation, and hum (+47 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (46): from_lead_row(), Lead scoring service — deterministic, no LLM.  Produces: - ScoreOutput with fit_, Score multiple lead rows (skips header)., Structured output of lead scoring., ScoreOutput, is_placeholder(), parse_single_url(), Operator-source ingestion for public URL lists.  Provides: - OperatorSource Pyda (+38 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (47): approval_check(), approval_stub_smoke(), _build_notifier(), _build_sheets_adapter(), daily_summary(), downstream_stub_smoke(), draft_outreach(), ingest_leads_readonly() (+39 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (18): _clean_slug(), _extract_affiverse(), extract_candidates(), _extract_commissioncrowd(), _extract_rewardful(), Bounded read-only directory/list extraction from public HTML pages.  Provides: -, Extract affiliate partners from Affiverse directory page.      Pattern: each par, Extract public opportunity cards from CommissionCrowd industry listing pages. (+10 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (16): NotifierAdapter, Telegram Bot notifier adapter with httpx, retries, and dry-run safety., Build a real Telegram Bot API URL.  Never log or print this value., POST to Telegram API with exponential backoff on transient errors.          Rais, Send a plain-text message via Telegram Bot API.          Returns a structured re, Send a formatted pipeline summary., Return whether a token is configured (safe for status checks)., Send a Telegram acknowledgement using the project notifier if configured. (+8 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (32): CandidateLead, LeadIngester, Discover candidates via public web search.          Currently a stub that return, Create pending approval requests for each candidate.          Approval asks the, A discovered candidate lead before it enters the pipeline., Discover, normalise, and persist candidate leads with full provenance., Load candidates from a local JSON file.          Expected JSON shape: list[dict], Tests for the LeadIngester service.  Covers: - JSON discovery loads candidates w (+24 more)

### Community 7 - "Community 7"
Cohesion: 0.08
Nodes (33): LeadScorer, Return whether a non-terminal approval already exists for the entity.          U, Create pending approvals for leads scoring above threshold, skipping duplicates., Score existing leads using deterministic rules., Tests for lead scoring service.  Covers: - Deterministic scoring on discovered l, Opportunity row must match SCHEMA['opportunities'] (14 columns)., write_opportunities in dry-run must not call append_row., write_opportunities with dry_run=False must call append_row. (+25 more)

### Community 8 - "Community 8"
Cohesion: 0.11
Nodes (24): Lead, Serialise to ordered list[str] aligned with adapter SCHEMA['opportunities']., Serialise to ordered list[str] aligned with adapter SCHEMA['leads']., A single B2B lead with research and outreach state., Serialise for Google Sheets., Orchestrate a batch of leads through research → draft → score., Send workflow failure notification if notifier is wired.          Message text i, WorkflowRunner (+16 more)

### Community 9 - "Community 9"
Cohesion: 0.11
Nodes (13): ExtractedCandidate, A candidate company extracted from a directory page., Non-secret serialisable representation., Tests for per-source extraction limits and related reporting.  Covers: - One sou, per_source_limit=0 means source can consume up to the global limit., Same URL across sources is deduplicated., Placeholder/stub candidates are blocked at ingestion time., ingest_sources never triggers outreach or email. (+5 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (23): Tests for the ApprovalGate service.  Covers creation, Sheet writes, read-backs,, Reading a non-existent approval_id must return 'missing'., Missing approval must be treated as not approved., A simulated downstream action must execute when approval is approved., validate_header must fail when live header differs from SCHEMA., Without a sheets_adapter, create_and_write_approval must refuse., If append_row fails, create_and_write_approval must raise., Dry-run must not call append_row on the sheets adapter. (+15 more)

### Community 11 - "Community 11"
Cohesion: 0.17
Nodes (5): OperatorSourceIngester, Load, validate, and ingest from operator-provided public source lists., TestIngestSourcesDryRun, When extraction yields zero, fallback lead is reported., TestSourceReports

### Community 12 - "Community 12"
Cohesion: 0.1
Nodes (5): Tests for shared secrets loader.  Never reads the real /home/ubuntu/hermes-contr, TestGetSecret, TestLoadSharedEnv, TestParseEnvFile, TestResolvePath

### Community 13 - "Community 13"
Cohesion: 0.12
Nodes (14): A unit of work inside a workflow run., A single execution of a campaign workflow., Serialise to ordered list[str] aligned with adapter SCHEMA['runs']., Task, WorkflowRun, Tests for domain models., test_lead_defaults(), test_lead_email_lowercased() (+6 more)

### Community 14 - "Community 14"
Cohesion: 0.12
Nodes (3): EmptyState(), NextPhaseButton(), Collapsible()

### Community 15 - "Community 15"
Cohesion: 0.11
Nodes (14): Real adapter backed by DeeperResearchService and LeadScorer.      Uses local det, Run bounded public read-only research for a lead., Generate a subject and body for outreach to this lead., Score a lead using deterministic rules from LeadScorer.          Returns fit_sco, ScoringAdapter, DeeperResearchService, Create a pending approval for outreach-draft creation only.          Skips if th, Perform bounded public research on one approved lead. (+6 more)

### Community 16 - "Community 16"
Cohesion: 0.15
Nodes (18): Tests for the approval decision roundtrip (read record, check status, gate actio, Rejected approval must block downstream action., Expired approval must block downstream action., Approved approval must allow downstream action., Approval record must not contain secrets even if Sheet had them., read_approval_record must return a full dict when the row exists., read_approval_record must return empty dict when the ID is not found., read_approval_record must return empty dict when no adapter is wired. (+10 more)

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (18): _make_mock_adapter(), Build a mock adapter that returns different tab data per tab name.      tab_rows, If lead_id already present in opportunities, don't append again., If lead_id not found, append_row is called., Dry-run should detect duplicates and report skipped without any append_row., If a pending/approved approval exists for the same entity, skip creation., Rejected approvals don't block new creation (they are terminal)., Dry-run must report below-threshold leads without writing. (+10 more)

### Community 18 - "Community 18"
Cohesion: 0.15
Nodes (17): _make_mock_gate_and_adapter(), _MockAdapter, Tests for deeper research service.  Covers: - Approved lead proceeds with resear, write_research_result with dry_run=False appends to outcomes tab., dry_run must not create a real approval., With dry_run=False, an approval is created for outreach-draft., Deeper research module must not import or call any outreach mechanism., A mock adapter that validates_tab_header always passes and append_row tracks. (+9 more)

### Community 19 - "Community 19"
Cohesion: 0.15
Nodes (15): _check_model_available(), from_text(), Supervisor Relay — routes AI supervision tasks to local/Hermes-routed models.  N, Query Ollama /api/tags to see if a model name is available.      ``base_url`` ma, Return the model to use plus an optional fallback_reason string.      Resolution, Canonical task types that route to distinct local models., Raised when the model output suggests a blocked action., Raised when the model JSON does not match the expected schema. (+7 more)

### Community 20 - "Community 20"
Cohesion: 0.12
Nodes (13): ApprovalGate, Read a full approval record from Sheets by approval_id.          Returns a dict, Check whether the live Sheet approvals header matches SCHEMA.          Returns a, Send Telegram approval notification if notifier is wired.          Message text, Service for creating and checking approval requests.      All writes are gated b, Missing approval must block downstream action., create_approval must produce a row matching canonical schema., test_create_approval_writes_correct_row() (+5 more)

### Community 21 - "Community 21"
Cohesion: 0.21
Nodes (10): usePhaseStatuses(), hasDataShape(), loadDataShape(), parseDataShape(), getExportZipUrl(), hasExportZip(), loadProductData(), parseProductOverview() (+2 more)

### Community 22 - "Community 22"
Cohesion: 0.12
Nodes (8): _apply_self_review_guard(), Detect when the supervisor reviewer is the same model family as the active Herme, Route a supervision prompt to the correct local model.          Args:, Convenience wrapper for PRIMARY_SUPERVISOR., Convenience wrapper for CODE_REVIEW., Convenience wrapper for REASONING_FALLBACK., Convenience wrapper for DRAFT_REVIEW., Convenience wrapper for LONG_CONTEXT_REVIEW (Nemotron, etc.).

### Community 23 - "Community 23"
Cohesion: 0.15
Nodes (14): BaseSettings, CcaSettings, Return a settings summary with no secret values exposed., Commission Crowd Agent runtime settings., Tests for config module with shared secrets integration.  Never reads the real /, Local Ollama should report ready when only base_url is set., test_env_var_precedence_over_shared_env(), test_load_settings_defaults() (+6 more)

### Community 24 - "Community 24"
Cohesion: 0.22
Nodes (4): OperatorSource, A single operator-provided source entry., TestOperatorSourcePlaceholder, TestOperatorSourceValidation

### Community 25 - "Community 25"
Cohesion: 0.28
Nodes (13): getSectionProgress(), extractScreenDesignName(), extractScreenshotName(), extractSectionIdFromProduct(), extractSectionIdFromSrc(), getAllSectionIds(), getSectionScreenDesigns(), getSectionScreenshots() (+5 more)

### Community 26 - "Community 26"
Cohesion: 0.23
Nodes (10): applyTheme(), handleStorageChange(), ShellWrapper(), loadScreenDesignComponent(), hasShell(), hasShellComponents(), hasShellSpec(), loadAppShell() (+2 more)

### Community 28 - "Community 28"
Cohesion: 0.16
Nodes (10): ApprovalRequest, Create a pending approval write it to the Google Sheet CRM, and verify., Create a pending approval request and optionally (dry-run) write to Sheets., A human approval request aligned with the live approvals tab schema.      Canoni, Set created_at_utc if not provided., Serialise to ordered list[str] aligned with adapter SCHEMA['approvals']., Without a notifier, notify_operator must return sent=False., When a notifier is wired, the message must contain no secrets. (+2 more)

### Community 29 - "Community 29"
Cohesion: 0.19
Nodes (10): BaseModel, DeeperResearchResult, Deeper research service for approved leads.  Design principles: - Only runs when, Bounded read-only research for a single lead., Structured finding from deeper research., Complete result of a deeper research pass., ResearchFinding, _try_fetch() (+2 more)

### Community 31 - "Community 31"
Cohesion: 0.2
Nodes (9): Tests for schema validation guards during writes.  Covers: - Header mismatch blo, write_candidates must abort if live header does not match SCHEMA., write_candidates must proceed if live header matches SCHEMA., append_row result must include updated_range field., ApprovalGate.create_approval must raise if header mismatch., test_append_row_returns_updated_range(), test_approval_gate_blocks_on_header_mismatch(), test_write_candidates_blocked_on_header_mismatch() (+1 more)

### Community 32 - "Community 32"
Cohesion: 0.2
Nodes (3): Tests for operator_source ingestion workflow.  Covers: - OperatorSource validati, TestLoadSourceFile, TestParseSingleUrl

### Community 33 - "Community 33"
Cohesion: 0.2
Nodes (7): Domain-driven workflow modules replacing n8n nodes.  Each module is a pure-Pytho, Outreach dispatch workflow stage.  Sends approved emails and updates lead status, Send emails for approved leads and mark sent., send_approved_outreach(), Research-to-draft workflow stage.  Fetches new leads, runs research agent, write, Fetch new leads, research, draft, score, and update status., run_research_cycle()

### Community 34 - "Community 34"
Cohesion: 0.24
Nodes (7): LeadStatus, OpportunityStage, Domain models for lead, opportunity, task, and workflow lifecycle.  All models a, Finite state machine for a lead., Pipeline stage for a vendor/principal opportunity in the rep-application model., TaskType, StrEnum

### Community 35 - "Community 35"
Cohesion: 0.2
Nodes (10): _build_preflight_table(), _build_settings_table(), preflight(), Fetch new leads, research, draft, score, and queue operator approvals.      In l, Return a preflight readiness table with shared-env checks.      Never prints sec, Show configuration readiness., Show preflight checks including shared secrets readiness., run_research_cycle() (+2 more)

### Community 36 - "Community 36"
Cohesion: 0.25
Nodes (3): _merge_sources(), Typed configuration loader using Pydantic Settings.  Reads from environment vari, Build a merged dict: env vars take precedence, then shared.env, then defaults.

### Community 37 - "Community 37"
Cohesion: 0.29
Nodes (5): Adapters for external systems.  - SourceAdapter: reads/writes leads to Google Sh, ApprovalAction, Approval gate service for human-in-the-loop control.  Provides: - ApprovalReques, Canonical approval-action taxonomy for the rep-application workflow.      Stages, Lead ingestion service for read-only candidate discovery.  Provides: - Candidate

### Community 38 - "Community 38"
Cohesion: 0.38
Nodes (4): hasDesignSystem(), loadColorTokens(), loadDesignSystem(), loadTypographyTokens()

### Community 39 - "Community 39"
Cohesion: 0.33
Nodes (4): applyTheme(), handleStorageChange(), ThemeToggle(), loadShellPreview()

### Community 40 - "Community 40"
Cohesion: 0.29
Nodes (4): Stub: read and write leads to Google Sheets., Return placeholder leads., Write lead state back to Sheets., SourceAdapter

### Community 43 - "Community 43"
Cohesion: 0.33
Nodes (5): _is_blocked_action(), Return True if *action* is a blocked verb or starts with one., Explicitly test whether a recommended action would be blocked.          Useful f, test_is_blocked_action_false(), test_is_blocked_action_true()

### Community 44 - "Community 44"
Cohesion: 0.33
Nodes (3): Fetch public HTML with bounded timeout and clear UA., Read existing lead URLs from the 'leads' tab for deduplication., Ingest from validated operator sources with per-source caps.          1. Fetch e

### Community 45 - "Community 45"
Cohesion: 0.33
Nodes (3): Return whether an opportunity already exists for the given lead_id.          Use, Write scored opportunities to the opportunities tab, skipping         duplicates, Serialise to opportunities tab (14 columns).

### Community 46 - "Community 46"
Cohesion: 0.33
Nodes (3): Send workflow start notification if notifier is wired.          Message text is, Send workflow success notification if notifier is wired.          Message text i, Execute research + writing for a batch of leads.

### Community 47 - "Community 47"
Cohesion: 0.4
Nodes (3): OutreachAdapter, Stub: dispatch personalised emails via Gmail / SMTP., Send a personalised email to a lead.

### Community 54 - "Community 54"
Cohesion: 0.5
Nodes (3): Approval gate workflow stage.  Handles approval summary generation and status tr, Return counts of leads by status., summarise_approval_queue()

### Community 55 - "Community 55"
Cohesion: 0.5
Nodes (3): Scoring workflow stage.  Re-evaluates or scores existing leads., Score a batch of leads., score_batch()

## Knowledge Gaps
- **303 isolated node(s):** `Domain models for lead, opportunity, task, and workflow lifecycle.  All models a`, `Finite state machine for a lead.`, `Pipeline stage for a vendor/principal opportunity in the rep-application model.`, `A single B2B lead with research and outreach state.`, `Serialise for Google Sheets.` (+298 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **19 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `cn()` connect `Community 27` to `Community 42`, `Community 14`, `Community 48`, `Community 49`, `Community 50`, `Community 51`, `Community 52`, `Community 30`?**
  _High betweenness centrality (0.255) - this node is a cross-community bridge._
- **Why does `Table()` connect `Community 35` to `Community 48`?**
  _High betweenness centrality (0.252) - this node is a cross-community bridge._
- **Why does `NotifierAdapter` connect `Community 5` to `Community 1`, `Community 35`, `Community 3`, `Community 37`, `Community 7`, `Community 8`, `Community 15`, `Community 19`, `Community 20`, `Community 28`, `Community 29`?**
  _High betweenness centrality (0.236) - this node is a cross-community bridge._
- **Are the 105 inferred relationships involving `MagicMock` (e.g. with `test_write_opportunities_dry_run()` and `test_write_opportunities_live()`) actually correct?**
  _`MagicMock` has 105 INFERRED edges - model-reasoned connections that need verification._
- **Are the 54 inferred relationships involving `GoogleSheetsAdapter` (e.g. with `Lead` and `DeeperResearchService`) actually correct?**
  _`GoogleSheetsAdapter` has 54 INFERRED edges - model-reasoned connections that need verification._
- **Are the 42 inferred relationships involving `SupervisorRelay` (e.g. with `CcaSettings` and `NotifierAdapter`) actually correct?**
  _`SupervisorRelay` has 42 INFERRED edges - model-reasoned connections that need verification._
- **Are the 45 inferred relationships involving `ApprovalGate` (e.g. with `CandidateLead` and `LeadIngester`) actually correct?**
  _`ApprovalGate` has 45 INFERRED edges - model-reasoned connections that need verification._