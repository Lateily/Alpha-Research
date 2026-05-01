# Team Structure & Roles

> Last updated: 2026-05-01

---

## Three-Party Model

```
Junyan (Owner)
   │
   ├── Direction, final investment decisions, deployment approvals
   │
   ├── Franky (Research Director, part-time)
   │       Weekly 1h: quality review + idea injection
   │       MIT信息流: external intelligence source
   │
   └── AI Stack (Builders)
           Claude: primary research + reasoning + architecture
           Codex:  production code quality + edge case defense
           (Gemini/Grok: future document/sentiment layer)
```

---

## Junyan — Platform Owner

**Role:** Sets direction. Makes all investment decisions. Approves production changes.

**What Junyan does:**
- Defines which stocks go on watchlist (only Junyan edits watchlist.json)
- Approves all git merges to main
- Calls `/auto` or `开始工作` to start autonomous work sessions
- Reviews STATUS.md + REVIEW_REQUEST.md weekly
- Deploys real capital (when model is mature)

**What Junyan does NOT do:**
- Write code (delegates to Claude/Codex)
- Do routine data analysis (delegates to pipeline)

---

## Franky — Research Director (Part-Time)

**Role:** Quality gate. External intelligence. Idea injector.

**Time commitment:** ~1 hour/week. Never expected to write code.

**Core contribution —挑漏洞 (find the hole):**
Every week, read 1-2 platform research outputs and answer ONE question:
> "What's the weakest link in this thesis? What question does this analysis not answer?"

Examples of useful pushback:
- "The EPS upgrade thesis skips explaining WHY gross margin improves — what's the mechanism?"
- "This thesis ignores the risk that BYD's EV subsidies phase out in 2027"
- "The catalyst is vague. 'Industry inflection' is not a catalyst."

**Weekly workflow:**
1. Receive Telegram alert with that week's top research output
2. Read it (5-10 min)
3. Fill in `REVIEW_REQUEST.md` with ≤3 observations
4. Junyan reviews → routes to Claude/Codex

**Idea injection:**
- MIT 信息流: course material, faculty research, conversations that touch on investment methodology, data science, alternative data — anything that could upgrade our framework
- Write it in `REVIEW_REQUEST.md` under "New Ideas"

**Access level:**
- GitHub: **read-only** (can see all code, cannot push)
- Telegram group: member (receives all daily platform alerts)
- `REVIEW_REQUEST.md`: write access (his primary contribution channel)

**What Franky does NOT do:**
- Write production code
- Make investment decisions
- Approve deployments

---

## Claude — Primary AI Builder

**Role:** Research engine + primary architect + code author.

**What Claude owns:**
- `api/research.js`, `api/debate.js` — LLM research quality
- `scripts/*.py` — pipeline logic, data processing
- `src/Dashboard.jsx` — frontend rendering
- All documentation (CLAUDE.md, STATUS.md, this file)

**Working protocol:**
- Reads STATUS.md at start of every session
- Reads STRATEGY.md before proposing any KR
- Reads INVESTMENT_FRAMEWORK.md before generating research
- Updates STATUS.md at end of every session
- Every PR goes through code review before merge

---

## Codex — Code Implementation Specialist

**Role:** Production code quality. Edge case defense. Refactoring.

**What Codex owns:**
- Code correctness, test coverage, edge cases
- Refactoring for maintainability
- Security review of API endpoints

**Working protocol:**
- Reads AGENTS.md at entry (write boundaries)
- Writes only to `experiments/` unless explicitly promoted
- Communicates with Claude via JSON file handshake (see AGENT_PROTOCOL.md)
- Never pushes to git directly — all commits go via Junyan review

---

## Decision Authority Matrix

| Decision | Junyan | Franky | Claude | Codex |
|----------|--------|------|--------|-------|
| Add/remove watchlist ticker | ✅ ONLY | advise | advise | — |
| Merge to main | ✅ ONLY | — | propose | propose |
| Deploy real capital | ✅ ONLY | advise | — | — |
| Research framework changes | ✅ approve | advise | propose | — |
| Algorithmic changes (scripts) | ✅ approve | — | propose | propose |
| Code review gate | — | — | ✅ | ✅ |
| Quality review (thesis) | ✅ final | ✅ primary | produce | — |

---

## Communication Channels

| Channel | Purpose | Frequency |
|---------|---------|-----------|
| Telegram group | Daily platform alerts, wrongIf alerts | Daily (automated) |
| `REVIEW_REQUEST.md` | Franky feedback → Claude input | Weekly |
| GitHub Issues (future) | Bug reports, feature requests | As needed |
| In-person / WeChat | Direction setting, weekly sync | Weekly |
