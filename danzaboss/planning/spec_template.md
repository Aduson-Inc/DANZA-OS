# Spec — <project name>

> Spec-Driven Development (Upgrade #3). Written BEFORE any code. The plan and all
> tasks derive from this document. If reality diverges from the spec, the spec is
> updated first, then the plan is regenerated. Onboarding fills this in — it
> replaces the ad-hoc feature-list.md.

## 1. Intent
One paragraph: what this software is and who it's for.

## 2. Functional requirements
- FR-1: <capability> — Acceptance: <observable, testable outcome>
- FR-2: ...

## 3. Non-functional requirements
- Performance budget: <e.g. p95 < 200ms>
- Security constraints: <auth model, data protection>
- Accessibility: <target, e.g. WCAG 2.1 AA>
- Observability: <what must be traced>

## 4. Data model
Entities, fields, relationships. (Feeds Samantha's map.)

## 5. External services / APIs
Each with: purpose, auth method, whether the user has access, free alternative.

## 6. Explicit non-goals
What this system deliberately will NOT do (prevents scope creep).

## 7. Verification strategy
How the whole system is proven correct end-to-end. Every FR maps to at least one
concrete verification (test/command/http/schema). No FR without a check.

## 8. Open questions
Anything unresolved. Blocks dispatch of the affected tasks until answered.
