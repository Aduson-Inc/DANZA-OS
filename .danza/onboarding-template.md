# DANZA Onboarding System

Tony D must complete this before ANY build begins.
This is a COLLABORATIVE DISCOVERY PROCESS, not a questionnaire.

Questions use a multi-choice format where possible. Read the user's selection and follow the instruction for that path.

---

## BEFORE YOU START

- Read user memory files (MEMORY.md and linked files) if they exist
- Honor known preferences — adapt your style to who the user is
- Read .danza/stack-philosophy.md for tech stack guidance

---

## 1. PROJECT OVERVIEW

**"What are we building today?"**

Let the user describe their idea in their own words. Don't interrupt with sub-questions yet — let them paint the picture.

**AFTER they describe it:**
→ Spawn Carmella to research competing/similar apps in this space
→ Present research findings before moving to features
→ Suggest features the user may not have thought of

---

## 2. CORE GOALS

**"What are the must-have features vs nice-to-haves?"**

- Walk through what they described and categorize each feature
- Must-haves: the app doesn't work without these
- Nice-to-haves: would be great, but can come later

**FOR ANY NOVEL OR UNIQUE FEATURES:**
→ Explore at least 3 edge cases with the user
→ Ask: What happens when [unexpected scenario]?
→ Don't move on until edge cases are addressed

---

## 3. USER FLOW

**"How does someone use this app from start to finish?"**

- How does a user enter the app?
- What are the key actions they take?
- What is the desired end result?

---

## 4. AUTHENTICATION

**"Does your app need user accounts?"**

Options:
- **A) Yes** → What type? (email/password, Google login, etc.) Any roles/permissions?
- **B) No** → Move on
- **C) I'm not sure** → Tony D explains when auth is needed and helps decide

**HARD STOP:** Auth decisions affect everything downstream. Confirm before proceeding.

---

## 5. DATA & STORAGE

**"Does your app need to save data?"**

Options:
- **A) Yes, users create and store data** → What kind? (text, images, files, etc.)
- **B) Just displays information** → Where does the info come from?
- **C) I'm not sure** → Tony D explains with examples and helps decide

If data storage needed, follow stack-philosophy.md for database selection (free-first, local-first).

**HARD STOP:** Database decisions affect everything downstream. Confirm before proceeding.

---

## 6. API / EXTERNAL SERVICES

**"Does your app need to connect to any outside services?"**

Options:
- **A) Yes** → Which ones? What do they provide?
- **B) No** → Move on
- **C) I don't know what that means** → Tony D explains APIs in simple terms with examples relevant to their app

**FOR EACH EXTERNAL SERVICE:**
→ Confirm user has access, OR
→ Help them set up (prefer free alternatives)
→ Do NOT assume the user has any accounts

---

## 7. FRONTEND / UI

**"How should your app look and feel?"**

- Any design preferences? (colors, style, mood)
- Mobile, desktop, or both?
- Any apps you've seen that look like what you want?

**WHEN VISUAL PREFERENCES ARE STATED:**
→ Spawn Hank immediately to produce design tokens
→ Populate design-tokens.json before onboarding ends

---

## 8. TECH STACK

**"Do you have a preferred tech stack for your application?"**

Options:
- **A) Yes, I know what I want** → What is it? Tony D confirms compatibility with the app requirements.
- **B) No preference, suggest one for me** → Tony D and Carmella research the best FREE, lightweight stack for this specific app. Present 2-3 options with tradeoffs. Then verify the user has the basics installed (Node.js, Python, etc.).
- **C) I don't know anything about this stuff** → That's completely fine! We'll pick the simplest, lightest setup that works for your app. No paid services, no complex configuration.

**FOR OPTION B:**
→ Spawn Carmella to research stacks suited to the app type
→ Follow stack-philosophy.md (free-first, lightweight-first)
→ Present options with plain-language explanations
→ After user picks, verify prerequisites are installed:
  - "Do you have Node.js installed? Let's check."
  - "Do you have Python installed? Let's check."
  - Walk them through installing anything missing

**FOR OPTION C:**
→ Skip the choices entirely — pick the lightest free stack that works
→ Follow stack-philosophy.md strictly
→ Walk them through EVERY setup step:
  - Check what's already on their computer
  - Install prerequisites together
  - Confirm everything works before moving on
→ Encourage them: "You don't need to understand all of this right now. We'll handle the technical parts."

---

## 9. CONSTRAINTS

**"Anything else we should know?"**

- Timeline? (no rush, ASAP, specific deadline)
- Budget? (free tools only, or willing to pay for services)
- Computer specs? (older/slower machine, or modern/powerful)

If older machine → enforce lightweight stack choices
If free only → no paid services, period

---

## 10. FINAL CHECK

Tony MUST ask:

**"Is there anything we haven't covered that could affect how this app works?"**

Repeat until user says NO.

---

## 11. VALIDATION

Tony summarizes EVERYTHING:

- What the app does
- Features (must-have + nice-to-have)
- Edge cases for novel features
- Tech stack (with reasoning)
- Design direction
- Any external services

User must confirm:

**"Yes, proceed."**

---

## 12. PRE-BUILD GATE

**BEFORE presenting the feature list, Tony D MUST:**

1. Consult CORTEX procedural memory — standard build orders for this app type
2. Update decision-log.md with ALL decisions made during onboarding
3. Update turn-log.md with this turn's record
4. Update self-assessment-log.md
5. Create run log in .danza/logs/

This is a GATE. Feature list cannot be presented until these are done.

---

## 13. ONBOARDING COMPLETE

Only AFTER this:

→ Samantha maps system
→ Tony creates feature list (informed by CORTEX build orders)
→ Execution begins

---

## 14. ONBOARDING EVOLUTION RULE

If ANY missing info is discovered later:

→ Add it to:
.danza/onboarding-misses.md

→ Future onboarding MUST include it
