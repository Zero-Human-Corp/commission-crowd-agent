# Manual Application Workflow

Version: MVP Browser Discovery v0.1.0 | Date: 2026-06-10

---

## Principle

**The CCA MVP never submits applications automatically.** Every application-to-principal requires:

1. Pipeline generates a draft (truthful, evidence-based)
2. Operator reviews the draft and the opportunity
3. Operator approves via the Google Sheets `approvals` tab
4. **Operator manually submits** the application on the CommissionCrowd website

There is no browser automation for form filling and no API endpoint for submission.

---

## Step-by-Step Workflow

### Step 1: Pipeline Discovers and Scores

Run the shadow or controlled-write pipeline. Qualified opportunities produce a draft.

```bash
python -m commission_crowd_agent.cli shadow-run --limit 5 --min-commission 20
```

Look for output like:
```
Draft prepared for OPP-9001: SaaS Analytics — UK
Score: 82
Subject: Independent Sales Representative Application — SaaS Analytics — UK
```

---

### Step 2: Operator Review

Read the draft body in the console or in the generated report. Ask:

- Is the commission structure acceptable?
- Is the territory a match?
- Does the company look legitimate? (do a quick web search if unsure)
- Are the residual terms clear?

If any answer is "no," **do not approve.** The pipeline will not submit without approval.

---

### Step 3: Approve in Google Sheets

If using controlled-write, the pipeline has already created a row in the `approvals` tab:

| approval_id | entity_id | requested_action | status | operator_decision | decided_at_utc |
|-------------|-----------|------------------|--------|-------------------|----------------|
| A001 | OPP-9001 | apply_to_principal | **pending** | | |

**Operator action:**
1. Open the Google Sheet → `approvals` tab.
2. Find the row with `approval_id = A001`.
3. Change `status` from `pending` → `approved`.
4. Enter `approved` in `operator_decision`.
5. Enter current UTC timestamp in `decided_at_utc` (e.g., `2026-06-10T12:00:00`).

---

### Step 4: Manual Submission on CommissionCrowd

1. Log into [https://www.commissioncrowd.com](https://www.commissioncrowd.com) as the operator.
2. Navigate to the opportunity page (use `source_url` from the draft / approval row).
3. Click **Apply** or **Express Interest**.
4. Paste the draft body (from the console output or approval notes) into the application form.
5. Attach any requested documents (CV, cover letter).
6. Submit.

**The pipeline does not do this for you.**

---

### Step 5: Update CRM

After manual submission, update the CRM manually or wait for the next browser discovery run to pick up the new `application_submitted` state.

If you want immediate tracking, edit the Google Sheets `opportunities` tab:
- Find the row with `source_id = OPP-9001`
- Change `status` to `application_submitted`
- Add a note with the submission date

---

## Why Manual?

| Risk of Automation | Mitigation |
|--------------------|------------|
| Wrong opportunity submitted | Operator must verify every target |
| Boilerplate application rejected | Drafts ask clarifying questions; operator customises |
| Legal liability (acting as operator's agent) | Operator retains full control |
| CAPTCHA / anti-bot on CommissionCrowd | Manual submission bypasses all bot detection |
| Terms-of-service violation | No automated posting; human submits |

---

## If the Operator Rejects

Change the approval row:
- `status` → `rejected`
- `operator_decision` → `rejected`
- Add reason in `notes`

The pipeline will not create a new approval for the same opportunity unless the record is deleted from the Sheet.

---

## Re-approval Policy

An already-approved record cannot be approved again. The `ApprovalGate.approve()` method returns:

```json
{"ok": false, "error": "Approval A001 is already approved"}
```

If the operator needs to re-open a decision, they must create a new approval row with a new `approval_id`.
