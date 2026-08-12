# WhatsPilot — Demo Walkthrough Script + Screenshot Shot List

Built from a real walkthrough of your running app (localhost:8000, "Solar Business" test
account). Two things came up while going through it that need handling before anything
goes public — flagged clearly below. Everything else is ready to shoot.

---

## ⚠️ Before you take/publish any screenshots

**1. Real customer data is visible on the Dashboard and in open conversations.**
The inbox currently shows real phone numbers and names — `+919962824442`, `Saranya S`
(+918248598810), `Shanthi`, and real message content. This is the actual data from your
test/sandbox business. Publishing this as-is on a public Upwork listing would expose real
people's phone numbers and private messages.

Two ways to fix it, pick one:
- **Best: seed a small "Demo" business** with 4-5 fake contacts (e.g. "Priya Menon",
  "+91 98xxx xxxxx" style obviously-fake numbers) and a few sample conversations about a
  plausible product/service. Screenshot that instead — takes ~15 minutes and you never have
  to worry about it again for future demos either.
- **Faster: crop or blur** the phone number and name in the conversations list (left panel)
  and the chat header before uploading anywhere. The lead-scoring panel on the right (Lead
  Health, Confidence, Score) is fine to show since it's not personally identifying on its own.

**2. The Settings page currently shows `tatapower.com` as an indexed website.**
That's presumably a test site you used to try the AI-training feature, not a real client of
yours. Using a real, recognizable company's domain in a public demo could look like you're
implying a relationship with them that doesn't exist. Swap it for a placeholder
(`yourbusiness.com`) or your own site before screenshotting Settings.

**3. Automation Rules currently has test-quality rule names** ("check", "ruke 4", "low lead")
visible in the Automation Rule Performance table on Analytics. Worth renaming 2-3 of these to
realistic examples ("Follow Up on Pricing Question," "Escalate Urgent Request") before
screenshotting — takes 2 minutes per rule and makes the product look sharper.

None of this blocks writing the script or planning the shots — just don't hit "publish" on
Upwork with raw screenshots until at least #1 is handled.

---

## Screenshot shot list (in the order they should appear in the listing)

| # | Screen | URL | Status | Notes |
|---|--------|-----|--------|-------|
| 1 | Inbox + conversation view | `/` (click a conversation) | ⚠️ needs demo data or blur | The hero shot — shows AI replying, lead score panel, tags |
| 2 | Analytics overview | `/analytics` | ✅ safe as-is | Lead Distribution, Lead Status donuts — no PII |
| 3 | Analytics — Revenue & Rule Performance | `/analytics` (scrolled) | ⚠️ rename test rules first | Otherwise safe, aggregate data only |
| 4 | Automation Rules — rule detail expanded | `/` (scroll to Automation Rules, expand a rule) | ✅ safe as-is | Shows the condition → action builder clearly |
| 5 | Settings — AI training on your website | `/settings` | ⚠️ swap test domain first | Good screen for "AI knows your business" pitch |
| 6 | CRM cards — Timeline / Pipeline / Reminders | `/` (scroll to CRM row) | ✅ safe as-is | Empty-state is fine, or fill with demo data |

Recommended order for the Upwork listing images: **1 → 4 → 2 → 5**, since #1 sells the core
idea (AI replies + tracks leads) and should be the first thing a buyer sees.

---

## Video walkthrough script (60–90 seconds)

Written for a screen recording with voiceover — matches the pacing Upwork buyers expect from
a Project Catalog demo video. Read it once out loud before recording; adjust timing to your
own voice.

---

**[0:00–0:10] — Open on the Inbox**

> "This is WhatsPilot — an AI assistant that runs inside your business's own WhatsApp number.
> Every message a customer sends lands right here."

*(Screen: dashboard inbox, conversation list visible)*

**[0:10–0:25] — Open a conversation**

> "The AI replies automatically, using information trained specifically on your business —
> your services, your pricing, your FAQs. And every single conversation is automatically
> tracked as a lead, so nothing gets forgotten."

*(Screen: click into a conversation, point out the AI reply bubble and the Lead Score panel
on the right — Confidence, Lead Health, Lead Score)*

**[0:25–0:40] — Automation Rules**

> "You can set rules without writing any code — for example, the moment a lead scores above
> 90, automatically create a follow-up reminder, or tag it as high priority. This runs in the
> background around the clock."

*(Screen: Automation Rules section, expand "High Value Lead" rule showing the
Lead Score ≥ 90 → Create Reminder flow)*

**[0:40–0:55] — Analytics**

> "And you get a real dashboard — lead distribution, conversion status, revenue trends, and
> exactly how well each of your automation rules is performing. No more guessing which leads
> are worth chasing."

*(Screen: Analytics page — Lead Distribution and Lead Status donuts, scroll to show Revenue
Trend)*

**[0:55–1:10] — AI trained on your business**

> "The AI isn't generic — point it at your website and it learns your actual products and
> answers, so customers get real, specific answers instead of a canned chatbot response."

*(Screen: Settings page, Indexed Websites section)*

**[1:10–1:20] — Close**

> "You get your own private dashboard, your own number, set up and live in days — not weeks.
> Message me if you'd like to see this running for your business."

*(Screen: back to dashboard, or a simple end card with your name/contact)*

---

## Notes for you

- Keep the recording to under 90 seconds — Upwork Catalog video views drop off fast past
  that, and buyers are scanning multiple listings.
- Record at 1440px+ width if you can (matches what you were just looking at) so text stays
  sharp when Upwork compresses the video.
- Once you've fixed the three flagged items above, this same shot list works for every future
  Upwork/Fiverr listing or client pitch — reuse it rather than rebuilding each time.
