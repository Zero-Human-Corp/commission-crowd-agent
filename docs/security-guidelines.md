**Security Guidelines Document**

**Product:** CommissionCrowd Invisible Agent (MVP)  
**Version:** 1.0  
**Date:** May 21, 2026  

---

### 1. Introduction

This document outlines the security guidelines for the **CommissionCrowd Invisible Agent**. As a headless automation system handling lead data and sending personalized emails on behalf of clients, security is critical for protecting sensitive information, maintaining client trust, and ensuring compliance.

The system processes personal and business data (names, emails, company information) and performs outbound communication. Therefore, security must be treated as a core requirement rather than an afterthought.

---

### 2. Security Principles

| Principle                  | Description                                                                 | Application in this System |
|---------------------------|-----------------------------------------------------------------------------|----------------------------|
| **Least Privilege**       | Only grant the minimum access required                                      | Use scoped credentials and limited permissions |
| **Defense in Depth**      | Apply multiple layers of protection                                         | Combine n8n security, Google access controls, and operational practices |
| **Data Minimization**     | Only collect and process data that is necessary                             | Avoid storing unnecessary personal data |
| **Auditability**          | Maintain clear records of actions                                           | Use status tracking and logs in Google Sheets |
| **Human Oversight**       | Never allow fully autonomous sensitive actions                              | Mandatory approval before sending emails |
| **Transparency**          | Make security-related actions visible to the Operator                       | Clear error logging and status updates |

---

### 3. Credential & Secret Management

Proper handling of credentials is one of the most important security aspects.

**Guidelines:**

- Store **all credentials** exclusively in the **n8n Credential Store** (encrypted).
- Never hardcode API keys, tokens, or passwords inside workflows.
- Use **separate credentials** per client where possible (especially for Gmail/SMTP).
- Rotate credentials periodically (especially Google OAuth and Telegram bot tokens).
- Use **OAuth2** instead of service account keys or passwords whenever available (Google Sheets and Gmail).
- Limit the scope of Google credentials to only what is needed (e.g., Sheets and Gmail access only).

**Recommended Credentials to Create in n8n:**
- Google Sheets OAuth2
- Gmail OAuth2 (per client when possible)
- Telegram Bot Token
- Ollama.com Cloud API Key

---

### 4. Data Protection

**Guidelines:**

- Treat all lead data in Google Sheets as **sensitive**.
- Do not copy lead data into external tools or temporary storage unnecessarily.
- Avoid logging full email content or personal data in n8n execution history when possible.
- Use the `Error Log` column in Google Sheets instead of exposing full data in alerts.
- When sharing Google Sheets with clients, only share the necessary tabs and use view-only access where appropriate.
- Regularly review and clean up old lead data if retention is not required.

**Data Flow Security:**
- Data moves between: Google Sheets → n8n → Ollama.com Cloud → n8n → Google Sheets → Email
- Minimize the amount of data sent to external LLM services (only send what is needed for personalization).

---

### 5. Access Control

**Operator Access:**
- Restrict Telegram bot access to the Operator’s private chat only.
- Do not add the Telegram bot to group chats.
- Use strong authentication on the n8n instance (enable Basic Auth or SSO if available).
- Limit who has edit access to the Google Sheets (especially the `Approved` column).

**Client Data Access:**
- Only share Google Sheets with clients when necessary.
- Prefer giving clients **view-only** access or specific tab access.
- Never give clients direct access to n8n or Telegram bot controls.

---

### 6. Communication Security

| Channel               | Security Measures                                      | Recommendations |
|-----------------------|--------------------------------------------------------|-----------------|
| **Google Sheets**     | OAuth2 authentication                                  | Use OAuth instead of service accounts when possible |
| **Telegram**          | Bot token + private chat only                          | Never share bot token publicly |
| **Ollama.com Cloud**  | API authentication                                     | Keep API key secure in n8n credentials |
| **Email Sending**     | Use authenticated SMTP or Gmail OAuth                  | Prefer OAuth over app passwords |
| **OCI Server**        | Use security lists and firewall rules                  | Restrict inbound access to necessary ports only |

**Recommendations:**
- Always use **HTTPS** for all external API calls.
- Avoid sending sensitive data in plain Telegram messages when possible (use summaries instead of full lead details).

---

### 7. Workflow & Automation Security

**Guidelines:**

- Design workflows to be **idempotent** to prevent duplicate actions.
- Never allow automatic email sending without the `Approved` flag being explicitly set.
- Implement proper **status validation** before executing sensitive actions (especially sending).
- Use **error handling workflows** to prevent silent failures.
- Validate input data from Google Sheets before processing (e.g., check for valid email format).
- Limit batch sizes in research workflows to reduce blast radius in case of errors.

**Critical Rule:**
> **No email should ever be sent without explicit Operator approval** via both the checkbox in Google Sheets **and** a Telegram trigger.

---

### 8. Logging & Monitoring

**Guidelines:**

- Maintain clear status tracking in Google Sheets for audit purposes.
- Log errors in the dedicated `Error Log` column.
- Send Telegram alerts for critical failures, but avoid including full sensitive data in alerts.
- Regularly review n8n execution history for unusual activity.
- Keep Run Logs (if implemented) for operational visibility.

**What to Log:**
- Status changes
- Number of leads processed
- Successful sends
- Errors and failures

**What to Avoid Logging:**
- Full email content in public logs
- Full personal data in Telegram notifications

---

### 9. Compliance Considerations

Since the user operates from **South Africa**, the following should be considered:

- **POPIA (Protection of Personal Information Act)**: The system processes personal information. Ensure lawful processing, especially when sending marketing emails.
- Obtain proper consent or rely on legitimate interest where applicable.
- Include clear unsubscribe mechanisms in all emails.
- Maintain records of processing activities (status logs help with this).
- Be transparent with clients about how their leads are being processed.

**General Recommendations:**
- Always include proper unsubscribe language in email templates.
- Do not scrape or use leads without a legitimate basis.
- Document data flows for compliance reviews.

---

### 10. Operational Security Best Practices

| Area                        | Recommendation                                                                 |
|----------------------------|--------------------------------------------------------------------------------|
| **n8n Instance**           | Keep n8n updated. Use strong authentication. Backup workflows regularly.      |
| **Google Sheets**          | Use sharing settings carefully. Enable version history.                       |
| **Telegram Bot**           | Keep bot token secure. Restrict to private chat only.                         |
| **Email Sending**          | Warm up domains if sending high volumes. Monitor deliverability.              |
| **Backups**                | Regularly export n8n workflows as JSON. Enable Google Sheets version history. |
| **Access Reviews**         | Periodically review who has access to Sheets and n8n.                         |
| **Incident Response**      | If a breach or major error occurs, immediately stop affected workflows.       |

---

### 11. Incident Response (High-Level)

In case of a security incident or major failure:

1. Immediately pause affected n8n workflows.
2. Review logs in n8n and Google Sheets.
3. Notify affected clients if personal data or sending was compromised.
4. Revoke and rotate any potentially compromised credentials.
5. Investigate root cause before resuming operations.

---

### 12. Summary of Key Security Rules

| #  | Rule                                                                 | Priority |
|----|----------------------------------------------------------------------|----------|
| 1  | Never hardcode credentials in workflows                              | Critical |
| 2  | Always require explicit approval before sending emails               | Critical |
| 3  | Store all secrets in n8n Credential Store                            | Critical |
| 4  | Restrict Telegram bot to Operator’s private chat only                | High     |
| 5  | Use OAuth2 instead of passwords where possible                       | High     |
| 6  | Maintain clear audit logs in Google Sheets                           | High     |
| 7  | Apply the principle of least privilege to all access                 | High     |
| 8  | Regularly review and rotate credentials                              | Medium   |
| 9  | Minimize sensitive data sent to external LLM services                | Medium   |
| 10 | Follow POPIA and include proper unsubscribe mechanisms               | High     |

---

These **Security Guidelines** should be followed during development, deployment, and daily operation of the CommissionCrowd Invisible Agent.

Would you like me to expand this into a more detailed version (e.g., with specific n8n configuration recommendations or a **Security Checklist** for go-live)?