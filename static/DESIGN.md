# Watt'sNext interface design

The interface applies the user-supplied Apple Design skill, retained in
`skills/apple-design/SKILL.md`. Read that file before extending this design.

## Direction

Calm, legible and immediate. The interface uses a neutral canvas, system
fonts, a blue interaction accent, opaque content surfaces and translucent
navigation. Risk colors communicate risk rather than branding. Every view
shares one token system in `static/styles.css`; do not append competing skins.

## Structure

- Floating navigation preserves Ask, Storm Activity and Wiki in one location.
  The selected segment follows a critically damped spring. Rapid selection
  changes preserve position and velocity and never block input.
- Ask keeps the composer visible while the conversation scrolls independently.
  A reply groups its estimates and next steps into one response. Evidence and
  alert previews use explicit disclosure controls. Medical safety guidance is
  always among the visible checklist items.
- Storm Activity uses a summary grid, duration percentiles, a repair timeline,
  alerts, events and a separate weather map. Calculated values remain untouched.
- Wiki uses editorial headings, an on-page contents list, clear household
  summaries and native keyboard-accessible FAQ disclosures.
- Settings uses grouped rows and a native modal. Gemini key entry appears only
  when Gemini is selected. Escape dismisses dialogs and browser focus returns
  to the invoking control.

## Tokens and type

Light: background #f5f5f7, surfaces #ffffff, primary text #1d1d1f,
secondary text #62626a, filled controls #006edb, text links #0066cc.
Dark: background #111113, surfaces #1c1c1f, primary text #f5f5f7,
secondary text #aaaab3, text links #73b4ff. Filled blue controls retain
white text at sufficient contrast in both appearances.

System fonts use optical sizing, tight display tracking, near-neutral body
tracking and comfortable line height. Layout spacing uses rem values.
Content cards have 24px radii, controls use pill shapes and evidence tags
remain visually secondary with readable labels.

## Motion and access

Tab motion is an interruptible requestAnimationFrame spring with critically
damped behavior. View changes cross-fade briefly, without blocking interaction.
Button feedback starts on press. Reduced motion makes the spring immediate
and disables looping effects; reduced transparency uses opaque chrome;
increased contrast adds stronger borders. Focus rings are visible, the skip
link follows the active view, dialogs use native focus management, and every
status retains text alongside color. No decorative gestures or moving
backgrounds compete with outage guidance.

## Verification

Check desktop and 375px mobile widths, both themes, long chat responses,
Settings, FAQ expansion, scenario changes and the no-path fallback. Preserve
the Python tests and JavaScript syntax/build checks.
