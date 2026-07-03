# Stack Philosophy

This file guides Carmella and Tony D when recommending tech stacks.

---

## Core Principles

1. **Free-first.** Never suggest paid services as the default. If a free option exists, use it.
2. **Lightweight-first.** Default to the simplest setup that works. Less complexity = fewer things to break.
3. **Local-first.** Prefer tools that run on the user's machine over cloud dependencies.
4. **No assumptions.** Don't assume the user has anything installed. Verify and help them set up.
5. **Flexible.** Power users will tell you what they want. Respect their choice.

---

## Decision Tree

### Does the user know what they want?
- **Yes** → Use their stack. Confirm it fits the app requirements.
- **No preference** → Research and suggest (see below).
- **Complete beginner** → Pick the lightest option. Walk them through setup.

### What kind of app is it?

**Static site / portfolio / landing page:**
- HTML + CSS + vanilla JS
- Or: Astro (lightweight, zero JS by default)
- No database needed
- Deploy: GitHub Pages (free)

**Interactive web app (single page):**
- React + Vite (fast, lightweight, huge ecosystem)
- Or: Vue + Vite (simpler learning curve)
- Database: SQLite (local, zero setup) or JSON files for simple data
- Deploy: GitHub Pages or Netlify free tier

**Web app with user accounts + database:**
- React/Vue + Vite (frontend)
- Express or FastAPI (backend)
- SQLite for development, Postgres for production if needed
- Auth: simple email/password with bcrypt, or free auth libraries
- Deploy: Railway free tier, Render free tier, or self-host

**Mobile app:**
- React Native + Expo (cross-platform, one codebase)
- Or: Flutter (if user prefers)
- Backend: same as web app

**API / backend only:**
- Python + FastAPI (simple, fast, great docs)
- Or: Node.js + Express (if user prefers JS)
- Database: SQLite → Postgres as needed

---

## Database Selection

| Need | Recommendation | Why |
|------|---------------|-----|
| Simple data, single user | JSON files or SQLite | Zero setup, no server |
| Multiple users, moderate data | SQLite | Still zero setup, handles more than people think |
| High concurrency, production scale | PostgreSQL (local install) | Free, powerful, industry standard |
| Need cloud database | Research free tiers (Neon, PlanetScale, etc.) | Only when local won't work |

**Default: SQLite.** It handles way more than beginners think. Only escalate when there's a real reason.

---

## Hardware Considerations

**Weak/old machine:**
- No Docker
- No heavy build tools (prefer Vite over Webpack)
- SQLite over Postgres
- Lighter frameworks (Astro, vanilla JS, Vue over Next.js)
- Fewer dev dependencies

**Modern machine:**
- Full flexibility
- Docker if useful
- Any framework
- User probably knows what they want

---

## What We Never Do

- Never suggest paid services as the default option
- Never assume the user has Node.js, Python, Git, or anything else installed
- Never pick a stack without explaining why in plain language
- Never use a heavy framework when a light one works
- Never add cloud dependencies when local works
