# Watt'sNext: personas, user stories, and workflows

These fictional stories show how people could use Watt'sNext to understand their household's power risk, possible repair times, and next steps. Each diagram follows a common task rather than a particular screen layout.

**Current product:** sample households, example repair scenarios, computed repair times, Wiki, Ask, Storm Activity, and local AI with a direct-facts fallback. Notifications are previews; the app does not send them. Repair times are estimates, and the current model does not provide a reliable outage percentage.

**Proposed extensions:** event-specific hurricane and tornado scenarios, verified planned-maintenance notices, and live utility updates. These are future stories, not features the current prototype already delivers. A local model still needs the app server and its data to be reachable; it does not make the website work without an internet connection.

## Fictional personas

| Persona | Household and situation | Main question | What success looks like |
|---|---|---|---|
| Maya Chen, remote customer-support worker | Lives with her partner and a child in a coastal community. Depends on her phone for work and has a power bank. | “What should I get ready, and how much work might I miss?” | A short checklist, understandable repair estimates, and an explanation of what is uncertain. |
| Luis Rivera, caregiver | Lives with his father in a rural community. His father uses powered medical equipment, which Luis explicitly tells the app about. | “What should we plan for if the power goes out?” | Clear limits on estimates and a reminder to arrange approved backup power with the device provider, without a promise of faster repairs. |
| Denise Brooks, small-business owner | Runs a home bakery in a neighborhood with overhead power lines. Plans orders around electrical equipment. | “Can I plan tomorrow's work around this interruption?” | A clear distinction between an example estimate and an official notice, plus an easy way to ask follow-up questions. |

## 1. First visit: understand this household

**Story:** As Maya, I want a simple overview before asking questions, so I can understand what the app knows about my home.

**Status:** Supported for sample households.

```mermaid
flowchart TD
    A[Choose a sample household] --> B[Compute risk and possible repair times]
    B --> C[Prepare household Wiki and chat context]
    C --> D{Household facts ready?}
    D -->|No| E[Show a clear loading or retry message]
    E --> B
    D -->|Yes| F[Enable chat]
    F --> G[Read the Wiki summary]
    G --> H{Need an explanation?}
    H -->|Yes| I[Choose Ask about the risk]
    I --> J[Open Ask with a question about the current risk level]
    J --> K[Explain the current household facts in plain language]
    H -->|No| L[Review next steps]
    K --> L
```

**Done when:** The household is clearly identified, chat becomes available only after its facts are prepared, and the risk button asks why that household has its current risk level.

## 2. Hurricane: prepare before possible outages

**Story:** As Maya, I want to understand a hurricane example and prepare my household, so I can plan charging, supplies, and work.

**Status:** Preparation and blocked-road examples exist. A hurricane-specific dataset and official warning integration are proposed.

```mermaid
flowchart TD
    A[Load a hurricane example for the household] --> B[Compute estimates and prepare Wiki]
    B --> C[Read risk and what to do now]
    C --> D[Ask what to prepare for this household]
    D --> E[Explain charging and supply steps]
    E --> F{Try a blocked-road example?}
    F -->|Yes| G[Apply an assumed access delay]
    G --> H[Recompute estimates and refresh Wiki and chat]
    H --> I[Explain the changed times and lower certainty]
    F -->|No| J[Use the current example]
    I --> K[Make a household preparation plan]
    J --> K
    K --> L[Check official sources for current warnings and outages]
```

**Example chat:** “If a road is blocked, why could repairs take longer?”

**Done when:** Maya can explain what changed in the example and knows that an assumed delay is not a measured hurricane delay or a confirmed restoration time.

## 3. Tornado: urgent safety first, outage questions later

**Story:** As Luis, I want the app to separate urgent weather safety from repair estimates, so I do not mistake a chat answer for an official warning.

**Status:** The current chat redirects requests for live information. Tornado-specific safety routing and datasets are proposed.

```mermaid
flowchart TD
    A[Luis opens the app during a tornado concern] --> B{Asking about an immediate warning?}
    B -->|Yes| C[Direct to official emergency alerts and instructions]
    C --> D[Do not make an all-clear claim from household data]
    B -->|No| E[Open the household example]
    D --> F[When safe, review the household's power questions]
    F --> E
    E --> G[Prepare computed facts and Wiki before chat]
    G --> H[Ask which example repairs affect this household]
    H --> I[Explain damaged equipment and uncertain repair times]
    I --> J{Need current outage status?}
    J -->|Yes| K[Open the official power-company outage center]
    J -->|No| L[Review household next steps]
```

**Example chat:** “Does the damage in this example mean my home has lost power?”

**Done when:** Luis understands that example damage does not confirm a current outage and that the app cannot decide when a tornado threat has passed.

## 4. Severe thunderstorm: understand why more teams may not help

**Story:** As Denise, I want to compare repair examples, so I can understand why extra repair teams do not always shorten the wait.

**Status:** Supported with the existing damage examples and repair-team controls. The example is not a live thunderstorm forecast.

```mermaid
flowchart TD
    A[Open a storm repair example] --> B[Review possible repair times in Wiki]
    B --> C[Try two more repair teams]
    C --> D[Recalculate the repair schedule]
    D --> E{Can separate repairs run at the same time?}
    E -->|Yes| F[Show any shorter estimated time]
    E -->|No| G[Show that the estimate may stay the same]
    F --> H[Refresh Wiki and chat with the new facts]
    G --> H
    H --> I[Ask why the estimate changed or stayed the same]
    I --> J[Explain parallel repairs and single-job limits]
    J --> K[Compare the examples before planning work]
```

**Example chat:** “Why didn't adding two repair teams make this repair faster?”

**Done when:** Denise understands that teams can work on different jobs, while one repair cannot simply be divided by the number of teams.

## 5. Planned maintenance: plan around an official notice

**Story:** As Denise, I want a planned power interruption explained clearly, so I can schedule baking and contact customers early.

**Status:** Proposed. The current prototype does not ingest verified maintenance notices or know a household's planned interruption schedule.

```mermaid
flowchart TD
    A[Receive a planned-maintenance notice] --> B{Verified notice available to the product?}
    B -->|No| C[Explain that no official schedule is available]
    C --> D[Direct Denise to her power company]
    B -->|Yes| E[Match notice to the correct household]
    E --> F[Prepare Wiki with notice source and update time]
    F --> G[Separate scheduled hours from predicted repair times]
    G --> H[Ask what the planned interruption means]
    H --> I[Explain the notice and its stated limits]
    I --> J[Plan charging and work around the official schedule]
    J --> K{Notice changes?}
    K -->|Yes| L[Refresh Wiki and chat before the next answer]
    L --> G
    K -->|No| M[Keep the current notice visible]
```

**Example chat:** “Is this the scheduled shutoff time, or just an estimate?”

**Done when:** Official scheduled hours remain clearly distinct from predictions, and chat never invents a maintenance notice.

## 6. Medical equipment: personalize preparation without promising priority

**Story:** As Luis, I want to share a medical-equipment need, so I receive relevant preparation guidance without relying on a repair estimate for medical planning.

**Status:** Supported for explicit declarations of powered medical equipment in the current conversation.

```mermaid
flowchart TD
    A[Luis explicitly says he uses powered medical equipment] --> B[Save the declared need for this conversation]
    B --> C[Refresh household Wiki and preparation guidance]
    C --> D[Show the medical backup-power reminder]
    D --> E[Explain that a generic power bank is not an approved substitute]
    E --> F[Direct Luis to the device provider for a backup-power plan]
    F --> G[Explain that the declaration does not guarantee faster repairs]
    G --> H[Answer follow-up questions from current household facts]
```

**Example chat:** “I use a CPAP. What should I plan before an outage?”

**Done when:** Guidance uses only an explicit declaration, retains the provider-approved backup-power message, and does not change repair priority or make assumptions about health.

## 7. Missing data or unavailable AI: still give an honest answer

**Story:** As Maya, I want a useful response when the model or household data is unavailable, so I know what I can trust and what to try next.

**Status:** Supported. This is an AI-service fallback, not a promise that the website works without a network connection.

```mermaid
flowchart TD
    A[Ask a household question] --> B{Reliable household estimate available?}
    B -->|No| C[Say that a reliable estimate is unavailable]
    C --> D[Give general preparation guidance and official outage link]
    B -->|Yes| E[Retrieve relevant prepared Wiki facts]
    E --> F{Local AI available?}
    F -->|No| G[Answer directly from household facts]
    F -->|Yes| H[Generate a plain-language explanation]
    H --> I{Answer passes fact checks?}
    I -->|No| G
    I -->|Yes| J[Show AI answer with a link to Wiki]
    G --> K[Label the answer as coming directly from household facts]
```

**Example chat:** “Can you still explain this if the AI is unavailable?”

**Done when:** The app does not invent missing numbers and clearly identifies when an answer comes directly from household facts.

## 8. Repairs marked complete: distinguish an example from real power

**Story:** As Denise, I want to understand what “repairs complete” means, so I do not assume my equipment has power based on an example.

**Status:** Supported as an example control; it is not a live utility restoration confirmation.

```mermaid
flowchart TD
    A[Mark example repairs complete] --> B[Recompute repair time as zero in the example]
    B --> C[Refresh Wiki and chat]
    C --> D[Explain that example work is complete]
    D --> E[State that this does not confirm power at a real address]
    E --> F{User says the power is still off?}
    F -->|Yes| G[Explain next checks and reporting to the power company]
    F -->|No| H[Review supplies and recharge essential devices]
    G --> I[Use official sources for real outage status]
```

**Example chat:** “The example says repairs are done, but my power is still off. What now?”

**Done when:** An example completion never appears as a confirmed real-world restoration message.

## 9. New data arrives: keep every answer tied to the current facts

**Story:** As any household user, I want Wiki and Ask to use the same current information, so I do not receive answers from an older household or scenario.

**Status:** Supported for household selection, scenario changes, declared needs, and changes to the loaded source catalog. A live ingestion pipeline is proposed separately.

```mermaid
sequenceDiagram
    actor User
    participant UI as Watt'sNext interface
    participant Server as App server
    participant Models as Risk and repair calculations
    participant Wiki as Household Wiki snapshot
    participant AI as Local language model
    User->>UI: Select household or change the example
    UI->>UI: Disable chat while preparing
    UI->>Server: Request current household facts
    Server->>Models: Compute risk and repair-time statistics
    Models-->>Server: Return computed results and limits
    Server->>Wiki: Build FAQ answers and model context
    Wiki-->>Server: Return prepared snapshot and revision
    Server->>Server: Clear older chat context when facts change
    Server-->>UI: Return prepared Wiki and chat-ready status
    UI->>UI: Enable chat
    User->>UI: Ask a question
    UI->>Server: Send the question
    Server->>Wiki: Retrieve relevant facts for this household
    Server->>AI: Provide question and current Wiki context
    AI-->>Server: Return a plain-language explanation
    Server->>Server: Check facts and recheck the current revision
    alt Facts changed during generation
        Server->>Wiki: Prepare the latest snapshot
        Server-->>UI: Return an answer directly from updated facts
    else Facts stayed the same
        Server-->>UI: Return checked answer or direct-facts fallback
    end
    UI-->>User: Show answer and link to household Wiki
```

**Done when:** Computation and Wiki preparation happen before chat readiness; old facts cannot influence a new scenario's answer. The language model receives context for each question rather than being retrained every time data changes.

## Suggested walkthroughs

- **Maya:** first visit → hurricane preparation → unavailable-AI fallback.
- **Luis:** tornado information limits → explicit medical-equipment declaration → current Wiki-based questions.
- **Denise:** storm repair-team comparison → completion example → proposed planned-maintenance journey.

For a current-product demonstration, use the sample households and existing scenario controls. Present hurricane-specific, tornado-specific, and planned-maintenance flows as proposed extensions.
