# Universal Agent Configuration & Guardrails

## Core Conventions
- Maintain 100% strict non-overlapping file ownership when running in parallel workflows.
- Always run local testing suites natively via virtual environments before declaring a task complete.
- Do not execute broad unsolicited code refactors outside the direct target task scope.

## Memory Upstream Sync
- At the conclusion of every successful debug or execution cycle, append a high-level summary entry to learnings.md containing the discovered root cause, file path, and resolved fix.
