# Watt'sNext interface design

The interface applies the user-supplied Apple Design skill, retained in
`skills/apple-design/SKILL.md`. Read that file before extending this design.

## Direction

Calm, legible and immediate. The interface uses a neutral canvas, system
fonts, a blue interaction accent, opaque content surfaces and translucent
navigation. Risk colors communicate risk rather than branding. Every view
shares one token system in `static/styles.css`; do not append competing skins.

## Structure

- A quiet desktop sidebar preserves Ask, Storm Activity and Wiki in one location,
  with the household picker and workspace actions below. Smaller screens use
  floating navigation; its selected segment follows an interruptible spring.
- Household selection retains native select semantics and keyboard behavior.
  Supporting browsers use a themed translucent picker with city headings,
  44px rows and a selected checkmark; other browsers retain the system picker.
  The collapsed control includes a home icon and desktop city context.
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
- The desktop workspace fills the viewport with a broad conversation area and
  an independently sized, centered composer capped at 880px. The conversation
  scrolls above it. Mobile scenario controls scroll horizontally to leave room
  for the conversation. Starter prompts offer clear first actions.
- The desktop new-chat state uses two columns across the available workspace:
  welcome context on the left and suggested questions on the right. Short
  windows reduce vertical spacing and heading size so the whole welcome and
  composer remain visible without clipping or scrolling. Conversation history
  retains independent scrolling once messages are present.
- The engine control beside the composer identifies Ollama, Gemini, or explicit
  facts-only mode. Keys remain in tab memory; connection errors never silently
  change the chosen provider. Browser-local Ollama inference is checked against
  server-computed household facts before it is shown as a model answer.

## Tokens and type

Light: background #f5f5f7, surfaces #ffffff, primary text #1d1d1f,
secondary text #62626a, filled controls #006edb, text links #0066cc.
Dark: background #111113, surfaces #1c1c1f, primary text #f5f5f7,
secondary text #aaaab3, text links #73b4ff. Filled blue controls retain
white text at sufficient contrast in both appearances.

System fonts use optical sizing, tight display tracking, near-neutral body
tracking and comfortable line height. Layout spacing uses rem values.
Content cards have 1.15rem radii, navigation uses rounded rows, and evidence tags
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
