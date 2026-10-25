# Watt'sNext — AEP Outage Concierge (HackOHI/O 2026)

Deadline: **8:00 p.m. Eastern today.** Working demo > extra features. Stop adding scope at 7:15.

Product name is **Watt'sNext** (spelled exactly like that: capital W, apostrophe, capital N, no space). It replaces the old working name "Lumen". Rename every user-visible "Lumen" string. Tagline: *"Know what's next when the power goes out."*

## What we're building

A customer-facing assistant for a storm. A customer picks a sample household (by city) and asks, in their own words:
- Will I lose power? (risk band + confidence + why)
- How long could repairs take? (a range, never one exact time)
- What should I do to prepare? (tailored to what they *declare*, never inferred)
- Do I qualify for alerts? (eligibility + channel + escalation triggers + message previews)

Python computes every number. The language model only interprets questions, calls supported tools, and explains the results.

## Step 0: figure out which situation you're in

1. **Existing app present** (`server.py`, `concierge/`, `static/`, `tests/`): **do not rebuild.** Run `python -m unittest discover -s tests -v` first and note the result. Then do the Phases below as edits.
2. **No existing app**: rebuild the same architecture (Python 3.10+, Starlette + Uvicorn, plain HTML/CSS/JS in `static/`, no frontend build step). Ask the user for the AEP data package path. If it's unavailable, build `data/sample.json` with the 4 cases and 12 synthetic households described below, clearly labeled as synthetic.

Before editing anything, run `git init && git add -A && git commit -m "baseline"` if there is no git repo. Commit after every phase.

## Architecture (keep)

- `server.py`: routes, in-memory sessions, chat, provider connection. Binds to 127.0.0.1.
- `concierge/engine.py`: risk, restoration, comparisons, change explanations.
- `concierge/cases.py`: replay cases. `concierge/customer_services.py`: prep + alerts.
- `concierge/tools.py`: tools exposed to the model. `concierge/gemini.py`: provider client.
- `data/`: anonymized prepared sample, labor reference, case evidence. No premise IDs, equipment IDs, addresses, or precise coordinates may reach the browser.

## Calculation rules (must match; these are acceptance tests)

- **Restoration effort** = reference install + removal hours × quantity × **4.5 indirect multiplier**. Do **not** add drive/setup/safety time again (the 4.5 already includes it).
- Treat workbook hours as **crew-hours** (stated assumption, shown in UI). One crew per job; independent jobs run in parallel when crews are free; supply returns only when *all* repairs on the household's path finish. Extra crews never split one job.
- Range = **75%–150%** of reference effort, labeled "scenario range, not a confidence interval".
- Transformer case (one 25 kVA unit) → **6.7–13.5 h**. With blocked access (+3 h assumed) → **9.7–16.5 h**. Add tests asserting both.
- **Risk band**: unrepaired assigned damage on the household's upstream path → High; otherwise storm setting calm/moderate/severe → Low/Moderate/High. Always labeled "demonstration rule, not a calibrated probability".
- **Confidence (new, required by the brief)**: derive from evidence quality, not from vibes:
  - Medium: the damage type and access flag come from source records, but assigning them to this household is a replay assumption (all current cases).
  - Low: the case uses an assumed duration (blocked access) or the household path failed consistency checks.
  - Show the reason in one sentence.
- **Cannot-predict fallback (new)**: if a household has no validated upstream path or required inputs are missing, return `fallback: true` with a plain reason. The UI then shows "We can't give a reliable estimate for this location" plus general safety guidance and the official Appalachian Power outage link.

## Phases (time-boxed)

### Phase 1: Make the AI conversation reliable (by 6:45)
- Gemini: call the list-models endpoint with the user's key and pin the first allowlisted model that completes a tool-call round trip. Show the chosen model name in Settings. Keep the honest error categories (quota, permission, unavailable).
- **Add "Offline explanation mode"** for when no provider works. Build answers from the same tool outputs using deterministic templates. Each answer carries a visible banner: "Offline mode — generated from rules, not AI." It is *never* used silently. The user switches it on in Settings, or accepts a one-click prompt after a connection error. This keeps the demo alive without pretending.
- Answer length: **80–180 words** for substantive questions and 1–3 sentences for follow-ups. (The old 250–450 target is too long for a stressed customer and for judges reading on screen.) Each answer covers: the direct answer, why, one or two next steps, and the main uncertainty. Ask at most one follow-up question.

### Phase 2: Fill the brief's gaps (by 7:15)
- **Restoration-complete flow**: add a "Mark repairs complete" case control. The assistant then says power should be back per the simulation, tells the customer what to do if theirs is still out (a nested outage: check breakers, then report), and the alert preview shows the restoration-complete message. Together with pre-storm, outage-confirmed and estimate-updated, all 4 required messages are now covered.
- **Visible scenario controls without clutter**: under the input box, show 3–4 small "what-if" chips that change one input and ask the question: "What if access is blocked?", "What if 2 more crews arrive?", "What if repairs finish?", "Start over before the storm". Judges must be able to change an input and watch the answer change.
- **Alert rules**: show escalation triggers explicitly:
  - Estimate moves by 2 hours or more → send an update.
  - Declared power-dependent medical device → recommend a phone call and an emergency plan, never promise priority restoration.
  - Restoration complete → send a confirmation.
  - Also show the timing for each message and the opted-in channel.
- **Evidence tags (our differentiator)**: every number in an answer card carries a small tag:
  - `Source data`: from AEP records.
  - `Assumption`: crew-hours, the +3 h delay, the 25 kVA quantity, case assignment.
  - `Model estimate`.
  - `Not available`: nothing is confirmed by the utility in this prototype. Show this as an explicit empty "Confirmed by utility" lane.

  Clicking a tag opens the existing evidence dialog at that item.

### Phase 3: Polish (by 7:40, then freeze)
- Use the **ui-ux-pro-max** skill to choose palette/type/spacing for a calm, trustworthy utility product, write `static/DESIGN.md`, and implement it as CSS custom properties. Use the **frontend-design** skill for direction: distinctive, not a generic chatbot look.
- **Keep the layout**: one conversation, a city selector, a new-conversation button and a settings gear, with detail in dialogs. No dashboard.
- **Inside assistant messages, render compact cards when structured data is present:**
  - A risk chip with confidence.
  - A restoration range bar labeled "Model estimate — not confirmed by the utility".
  - A three-lane layout: Estimate / Confirmed by utility / What you can do.
  - Before/after ranges when an estimate changes.

  Use only backend values; never parse numbers out of prose and never hardcode them.
- **Empty state**: the Watt'sNext name, the tagline, and 4 starter questions.
- **Style the rest:**
  - Typing indicator.
  - Phone-style SMS bubbles in alert previews.
  - Light and dark mode.
  - WCAG AA contrast.
  - Keyboard focus.
  - `aria-live` for new messages.
  - `prefers-reduced-motion` support.
  - A 375px mobile layout.
- Verify in the browser at desktop width and 375px. Fix console errors.

## Hard rules

- All existing tests stay green. Add tests for: confidence levels, the fallback, the restoration-complete flow, offline-mode labeling, and the two acceptance ranges above.
- **Never:**
  - Invent probabilities, current outages, crew positions, shelter status, or compensation eligibility.
  - Claim live weather, outage, or crew feeds.
  - Show facility locations.
  - Infer health information.
- For questions needing live or account data (is a shelter open, do I get a credit), the assistant says it doesn't have that data and points to the official Appalachian Power and Red Cross sources.
- Never put API keys in files, logs, or commits. Keys go in the Settings field only.

## Demo acceptance walkthrough (run before 7:45)

1. Pick Roanoke, transformer case. Household A has a power bank and needs a phone for work. Ask "Will I lose power and for how long?" Expect High, Medium confidence, 6.7–13.5 h, and evidence tags.
2. Switch to household B with a declared power-dependent medical device. Ask the same question. Expect the same range but different priorities: a provider-approved backup plan, phone-call escalation, and no promise that a generic battery can power the device.
3. Tap "What if access is blocked?" Expect 9.7–16.5 h, before/after ranges shown, the change attributed only to the access assumption, Low confidence, and an estimate-updated alert preview.
4. Tap "What if repairs finish?" Expect the restoration-complete message and nested-outage guidance.
5. Ask "Is the shelter on Main St open?" Expect an honest "no live data" answer with official links.
6. Disconnect the provider. Expect an honest error, and the offline mode works with its banner.

Finish with a short `README.md`: how to run, the folder map, the assumptions list, and what is and isn't verified.
