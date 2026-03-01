# Outreach Strategy & Compliance

## Legal Reality

B2B cold email is legal in the EU under GDPR "legitimate interest" (Recital 47 explicitly mentions direct marketing). Companies like 11x.ai, Instantly, Smartlead all operate at scale this way. The key is doing it properly.

## Pre-Flight Compliance Check (Every Message)

Every outreach message passes this before sending:

1. **Business email only** — no personal addresses (gmail, hotmail). Only `name@company.com`
2. **Legal basis documented** — legitimate interest rationale linked to recipient's professional role
3. **Sender identity clear** — real name, real company, real domain
4. **Purpose stated** — why you're reaching out
5. **Opt-out present** — one-click unsubscribe in every message
6. **Suppression list checked** — opted-out contacts never contacted again
7. **Data minimization** — only store name, role, company, business email

## Channel Playbooks

### Email (Primary Autonomous Channel)
- Dedicated sending domain (not main domain)
- Domain warming: 2-week ramp (5 → 10 → 20 → 50/day)
- DKIM/SPF/DMARC properly configured
- Cap: 50 cold emails/day per domain in V1
- Agent drafts → compliance check validates → system sends
- Reply classification: interested / not interested / opt-out / bounce
- Opt-outs added to suppression list immediately

### LinkedIn (Semi-Autonomous)
- Browser automation (Playwright) on real account
- Rate limits: max 25 connection requests/day, max 50 messages/day
- Always personalized per profile
- Value-first messaging: "I'm researching [problem] and noticed you deal with [thing]"
- Monitor SSI score, back off if declining

### Reddit (Content-First)
- Post genuinely helpful content in relevant subreddits
- Comment on relevant threads with real value
- DM only people who explicitly express interest
- Build karma before any outreach content
- Track engagement as signal quality evidence

### X/Twitter (Content + Engagement)
- Post research insights publicly
- Engage with relevant conversations
- DMs only to people who engage with your content first (warm)

## Conversation Handling

The Conversation Agent runs autonomous async text conversations (email replies, LinkedIn messages). This is how AI SDR companies operate.

### Constraints
- **Transparency**: configurable — either disclosed AI or human-name AI-operated (industry standard for B2B)
- **Goals**: understand workflow/pain → validate problem → gauge willingness to pay → schedule call or propose pilot
- **Every conversation extracts**: problem confirmed (y/n), current workaround, budget authority, willingness-to-pay signal (0-1), suggested next step, full transcript as evidence

### Human Escalation Triggers
- Strong buying intent detected
- Complex questions agent can't answer
- Confusion about who they're talking to
- Commitment negotiation (pricing, terms, scope)

## Interview Support Tiers

| Tier | Mode | V1? | How It Works |
|------|------|-----|-------------|
| A | Fully autonomous text | ✅ | Agent handles email/message reply conversations |
| B | Agent-assisted human calls | ✅ | Agent generates script + dossier, human does call, agent transcribes + extracts |
| C | Autonomous voice | ❌ | Future. Requires explicit disclosure/consent |
