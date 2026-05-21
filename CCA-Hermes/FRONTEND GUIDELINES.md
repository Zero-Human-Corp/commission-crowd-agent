**Frontend Guidelines Document**

**Product:** CommissionCrowd Invisible Agent (MVP)  
**Version:** 1.0  
**Date:** May 21, 2026  
**Purpose:** This document defines the frontend approach, user experience principles, and interface guidelines for the CommissionCrowd Invisible Agent. It ensures consistency with the product’s core philosophy of being **completely headless and invisible**.

---

### 1. Introduction

The CommissionCrowd Invisible Agent is intentionally designed as a **headless system**. There is **no custom web application, dashboard, or frontend codebase**.

All user interaction happens through two existing, familiar tools:

- **Google Sheets** — Primary interface for data, review, and approval
- **Telegram** — Control panel and notification channel

This document provides guidelines to ensure these interfaces deliver a clean, efficient, and professional operator experience while maintaining the product’s “invisible” value proposition.

---

### 2. Frontend Philosophy

| Principle                  | Description                                                                 | Why It Matters |
|---------------------------|-----------------------------------------------------------------------------|----------------|
| **Headless by Default**   | No custom UI should be built unless absolutely necessary                    | Keeps development effort low and aligns with product vision |
| **Familiarity First**     | Use tools the Operator already knows (Google Sheets + Telegram)             | Reduces learning curve and friction |
| **Minimalism**            | Only show what is necessary                                                 | Prevents overwhelm and maintains focus on outcomes |
| **Human-in-the-Loop**     | Approval must always require explicit human action                          | Ensures quality and control |
| **Transparency**          | Status and actions should be clearly visible in Google Sheets               | Builds trust and auditability |
| **No Client Friction**    | Clients should never need to log into anything new                          | Core product differentiator |

**Golden Rule:**  
If a feature requires building a custom screen or dashboard, **question whether it is truly needed** for the MVP.

---

### 3. Primary Interfaces

| Interface          | Role                              | Primary Users     | Interaction Type          | Priority |
|--------------------|-----------------------------------|-------------------|---------------------------|----------|
| **Google Sheets**  | Data entry, review, approval      | Operator          | Read + Write              | High     |
| **Telegram Bot**   | Notifications + Commands          | Operator          | Read + Write (commands)   | High     |
| Custom Web App     | None (Not in scope)               | —                 | —                         | None     |

---

### 4. Google Sheets UI/UX Guidelines

Google Sheets serves as the **main working interface**. It must be structured for clarity and ease of use.

#### 4.1 Sheet Organization

- Use **separate sheets** within one workbook or separate workbooks per client when scaling.
- Recommended structure:
  - `Leads` (Main working sheet)
  - `Config` (Client settings)
  - `RunLog` (Optional historical log)

#### 4.2 Leads Sheet Guidelines

| Column                  | Formatting Recommendation                  | Purpose                              | Notes |
|-------------------------|--------------------------------------------|--------------------------------------|-------|
| Lead ID                 | Plain text                                 | Unique identifier                    | Auto-generated if possible |
| Full Name / Company     | Bold for name                              | Quick identification                 | — |
| Research Notes          | Wrap text, light background                | Review context                       | Keep concise |
| Email Subject           | Bold                                       | Quick scan                           | — |
| Email Body              | Wrap text                                  | Full review                          | Limit to 2–3 paragraphs |
| Personalization Score   | Color scale (Red → Green)                  | Quick quality indicator              | 1–10 scale |
| Status                  | Dropdown + Conditional formatting          | Workflow visibility                  | Use colors (e.g. Draft Ready = Yellow) |
| Approved                | Checkbox                                   | Explicit approval action             | Most important interaction |
| Sent Timestamp          | Date format                                | Audit trail                          | — |
| Error Log               | Red text / Wrap text                       | Troubleshooting                      | Only visible when errors exist |

**Best Practices:**
- Use **conditional formatting** heavily on the `Status` column.
- Freeze the header row.
- Use **filters** enabled by default.
- Keep important action columns (especially `Approved`) near the left side.
- Add a **Notes / Comments** column for operator remarks.

#### 4.3 Config Sheet Guidelines

- Keep it clean and well-labeled.
- Use clear section headers.
- Include example values where helpful (especially for tone and ICP).

---

### 5. Telegram Bot Guidelines

Telegram acts as the **lightweight control center**.

#### 5.1 Notification Guidelines

- Keep notifications **concise and actionable**.
- Always include a direct link to the relevant Google Sheet when possible.
- Use clear emojis for quick scanning:
  - ✅ = Success / Completed
  - ⚠️ = Warning / Needs attention
  - 📋 = Drafts ready for review
  - 📤 = Emails sent

**Example Notification:**
```
📋 23 new drafts ready for review  
Client: HVAC_Pro_Solutions  
→ Open Sheet: [Link]
```

#### 5.2 Command Guidelines

Recommended simple commands:

| Command                  | Purpose                              | Response Style          |
|--------------------------|--------------------------------------|-------------------------|
| `/approve [Client]`      | Trigger sending of approved leads    | Confirmation + count    |
| `/send pending`          | Send all currently approved leads    | Confirmation            |
| `/status [Client]`       | Show current pipeline status         | Summary                 |
| `/run research`          | Manually trigger research workflow   | Acknowledgment          |

**Best Practices:**
- Keep commands short and memorable.
- Provide helpful feedback after every command.
- Avoid overloading the bot with too many commands in the MVP.

---

### 6. Operator Experience Principles

| Principle                    | Guideline                                                                 |
|-----------------------------|---------------------------------------------------------------------------|
| **Low Cognitive Load**      | Minimize steps between review and approval                                |
| **Clear Status Visibility** | Operator should understand the state of any lead in under 5 seconds       |
| **Explicit Actions**        | Never auto-send. Always require checkbox + Telegram trigger               |
| **Fast Feedback**           | Provide immediate confirmation after commands                             |
| **Error Clarity**           | Errors should be visible in Sheets and alerted via Telegram               |
| **Consistency**             | Use the same column names and status values across all clients            |

---

### 7. Do’s and Don’ts

**Do’s**
- Use Google Sheets formatting (conditional formatting, data validation, filters) to improve usability.
- Make the `Approved` column highly visible and easy to toggle.
- Send useful, non-spammy Telegram notifications.
- Maintain consistent column structure across clients.
- Prioritize readability in Research Notes and Email Body columns.

**Don’ts**
- Do **not** build a custom web dashboard or admin panel in the MVP.
- Do **not** create complex Telegram bots with many nested menus.
- Do **not** hide important information behind multiple clicks or sheets.
- Do **not** auto-approve or auto-send emails.
- Do **not** overload the Operator with too many notifications.

---

### 8. Accessibility & Usability

- Use clear, descriptive column headers.
- Apply consistent color coding for status (avoid relying only on color).
- Keep email drafts readable (avoid very long walls of text).
- Ensure the Google Sheet works well on both desktop and tablet (common for operators).

---

### 9. Future Considerations (Post-MVP)

If a lightweight frontend is ever considered in the future, the following rules should apply:

- Only build a frontend if it significantly improves operator efficiency.
- Any frontend must remain **optional** — the core system must continue working via Sheets + Telegram.
- Preferred approach: Simple internal tool (e.g., Retool, Softr, or lightweight React app) that reads/writes to the same Google Sheets backend.
- Never expose a frontend to clients.

---

### 10. Summary

| Aspect                    | Guideline                                      |
|---------------------------|------------------------------------------------|
| Custom Frontend           | Not required for MVP                           |
| Primary Interface         | Google Sheets                                  |
| Control Interface         | Telegram Bot                                   |
| Design Goal               | Simplicity, clarity, and minimal friction      |
| Approval Model            | Explicit (Checkbox + Telegram trigger)         |
| Philosophy                | Invisible, familiar, and operator-friendly     |

---

This **Frontend Guidelines Document** ensures that the user experience remains aligned with the product’s headless and invisible nature while delivering a practical and efficient workflow for the Operator.

Would you like me to create a companion document such as:
- **Google Sheets Template Design Specifications**?
- **Telegram Bot Interaction Patterns**?
- A combined **Operator Runbook** that includes both frontend and operational steps?