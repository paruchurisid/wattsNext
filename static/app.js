(() => {
  "use strict";

  const conversation = document.getElementById("conversation");
  const emptyState = document.getElementById("empty-state");
  const householdSelect = document.getElementById("household-select");
  const chips = document.getElementById("whatif-chips");
  const composer = document.getElementById("composer");
  const messageInput = document.getElementById("message-input");

  let sessionId = null;
  let lastEstimate = null; // for before/after rendering on chip use
  let currentView = "ask";
  let busy = false;
  let chatReady = false;
  let householdKnowledge = null;
  // Connection credentials belong to this tab, never shared server settings or disk.
  let connection = null;
  let connectionState = "disconnected";
  const hosted = !["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);

  function updateEngine(connected, label) {
    connectionState = connected ? "connected" : "disconnected";
    const button = document.getElementById("engine-status-btn");
    button.dataset.state = connection && connection.offline_mode ? "offline" : connectionState;
    document.getElementById("engine-label").textContent = label || (connection && connection.offline_mode
      ? "Household facts · AI off" : connected ? `${connection.provider === "local" ? "Ollama" : "Gemini"} · ${connection.model}` : "Connect your AI · Ollama or Gemini");
  }

  async function ollamaRequest(path, body) {
    const address = new URL(connection.ollama_url || "http://127.0.0.1:11434");
    if (!["http:", "https:"].includes(address.protocol) || address.username || address.password ||
        !["localhost", "127.0.0.1", "[::1]"].includes(address.hostname)) {
      throw new Error("Use an Ollama address on localhost or 127.0.0.1.");
    }
    const response = await fetch(address.origin + path, {
      method: body ? "POST" : "GET",
      ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
      signal: AbortSignal.timeout(body ? 120000 : 5000),
    });
    if (!response.ok) throw new Error("Ollama rejected the request. Check that the model is installed.");
    const result = await response.json();
    if (result.error) throw new Error("Ollama could not complete the request.");
    return result;
  }

  async function checkOllama() {
    const result = await ollamaRequest("/api/tags");
    if (!(result.models || []).some(model => model.name === connection.model || model.name === connection.model + ":latest")) {
      throw new Error(`Install ${connection.model} in Ollama, then connect again.`);
    }
    updateEngine(true);
  }

  async function loadConnection() {
    try {
      const { ok, body } = await api("/api/settings");
      if (!ok) throw new Error("Connection unavailable");
      connection = { provider: body.provider, model: body.model || "llama3.2:3b", offline_mode: body.offline_mode,
        browser_local: hosted, ollama_url: "http://127.0.0.1:11434" };
      updateEngine(!hosted && body.connected || body.provider === "gemini" && body.connected);
    } catch (_) { connection = { provider: "local", model: "llama3.2:3b", offline_mode: false, browser_local: hosted }; updateEngine(false); }
  }

  function useHouseholdKnowledge(data) {
    if (!data || !data.chat_context || !data.chat_context.ready) throw new Error("Household information is not ready yet.");
    householdKnowledge = data;
    chatReady = true;
  }

  function askAbout(question) {
    setView("ask");
    if (busy || !chatReady) return;
    sendMessage(question);
  }

  function askButton(question, label = "Ask about this") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ask-about";
    button.textContent = label + " ↗";
    button.disabled = busy || !chatReady;
    button.addEventListener("click", () => askAbout(question));
    return button;
  }

  // A critically damped spring keeps tab changes interruptible. Retargeting
  // preserves the current position and velocity; controls never wait on motion.
  const navigation = document.querySelector(".view-toggle");
  const navIndicator = document.querySelector(".nav-indicator");
  const navMotion = { x: 0, velocity: 0, target: 0, frame: null, previous: 0, initialized: false };
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  function positionNavigation() {
    const selected = navigation.querySelector('[aria-pressed="true"]');
    if (!selected) return;
    navMotion.target = selected.offsetLeft;
    navIndicator.style.width = selected.offsetWidth + "px";
    if (!navMotion.initialized || reducedMotion.matches) {
      if (navMotion.frame) cancelAnimationFrame(navMotion.frame);
      navMotion.frame = null;
      navMotion.x = navMotion.target;
      navMotion.velocity = 0;
      navMotion.initialized = true;
      navIndicator.style.transform = `translate3d(${navMotion.x}px,0,0)`;
      return;
    }
    if (!navMotion.frame) {
      navMotion.previous = performance.now();
      navMotion.frame = requestAnimationFrame(tickNavigation);
    }
  }
  function tickNavigation(now) {
    const dt = Math.min((now - navMotion.previous) / 1000, .032);
    navMotion.previous = now;
    navMotion.velocity += ((navMotion.target - navMotion.x) * 420 - navMotion.velocity * 41) * dt;
    navMotion.x += navMotion.velocity * dt;
    if (Math.abs(navMotion.x - navMotion.target) < .1 && Math.abs(navMotion.velocity) < .1) {
      navMotion.x = navMotion.target;
      navMotion.velocity = 0;
      navMotion.frame = null;
    } else navMotion.frame = requestAnimationFrame(tickNavigation);
    navIndicator.style.transform = `translate3d(${navMotion.x}px,0,0)`;
  }
  new ResizeObserver(positionNavigation).observe(navigation);
  reducedMotion.addEventListener("change", positionNavigation);

  function setBusy(value, label) {
    busy = value;
    for (const control of document.querySelectorAll("#composer button, #whatif-chips button, .ask-about, #household-select, #new-conversation-btn")) {
      control.disabled = value || !sessionId || !chatReady;
    }
    messageInput.disabled = value || !sessionId || !chatReady;
    conversation.setAttribute("aria-busy", String(value));
    document.getElementById("chat-status").textContent = label || (value ? "Finding an answer in your household's information…" : chatReady ? "Your household's information is ready. Ask a question." : "Choose a household to prepare its information.");
  }

  const EVIDENCE_LABELS = {
    source_data: "From records",
    assumption: "Assumed for this example",
    model_estimate: "Estimate",
    not_available: "Not confirmed",
  };

  // Simple hand-drawn outline icons, styled in CSS as a colored circle with
  // a white stroke glyph — echoes the AEP site's four quick-link icons.
  const ICON_PATHS = {
    warning: '<polygon points="12,3 2,20 22,20"/><line x1="12" y1="9" x2="12" y2="15"/><line x1="12" y1="17" x2="12" y2="17.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/><line x1="12" y1="8" x2="12" y2="8.01"/>',
    check: '<circle cx="12" cy="12" r="9"/><polyline points="8,12 11,15 16,9"/>',
    clock: '<circle cx="12" cy="12" r="9"/><polyline points="12,7 12,12 16,14"/>',
    bell: '<path d="M6 10a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    shield: '<path d="M12 3 4 6v6c0 5 4 8 8 9 4-1 8-4 8-9V6l-8-3z"/>',
    checklist: '<rect x="4" y="4" width="16" height="16" rx="2"/><polyline points="8,12 10,14 15,9"/>',
    list: '<line x1="9" y1="6" x2="20" y2="6"/><line x1="9" y1="12" x2="20" y2="12"/><line x1="9" y1="18" x2="20" y2="18"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
  };

  function iconCircle(kind, color, small) {
    const span = document.createElement("span");
    span.className = "icon-circle" + (small ? " icon-circle-sm" : "");
    span.style.background = color;
    span.setAttribute("aria-hidden", "true");
    span.innerHTML = `<svg viewBox="0 0 24 24">${ICON_PATHS[kind]}</svg>`;
    return span;
  }

  const RISK_ICON = { Low: "check", Moderate: "info", High: "warning" };
  const RISK_COLOR_VAR = { Low: "--color-risk-low", Moderate: "--color-risk-moderate", High: "--color-risk-high" };

  function applyStoredTheme() {
    try {
      const stored = localStorage.getItem("wattsnext-theme");
      if (stored) document.documentElement.setAttribute("data-theme", stored);
      document.getElementById("theme-select").value = stored || "system";
    } catch (_) { /* private browsing or blocked storage */ }
  }

  function setTheme(value) {
    if (value === "system") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", value);
    }
    try { localStorage.setItem("wattsnext-theme", value); } catch (_) { /* ignore */ }
  }

  async function api(path, options) {
    const resp = await fetch(path, { ...options, signal: AbortSignal.timeout(75000) });
    const body = await resp.json().catch(() => ({}));
    return { ok: resp.ok, status: resp.status, body };
  }

  async function loadHouseholds() {
    const { ok, body } = await api("/api/households");
    if (!ok || !Array.isArray(body.households) || !body.households.length) throw new Error("Households unavailable");
    const byCity = {};
    for (const h of body.households) {
      (byCity[h.city] = byCity[h.city] || []).push(h);
    }
    householdSelect.innerHTML = "";
    for (const city of Object.keys(byCity).sort()) {
      const group = document.createElement("optgroup");
      group.label = city;
      if (CSS.supports("appearance", "base-select")) {
        const heading = document.createElement("legend");
        heading.textContent = city;
        group.appendChild(heading);
      }
      for (const h of byCity[city]) {
        const opt = document.createElement("option");
        opt.value = h.household_id;
        opt.textContent = h.display_name;
        group.appendChild(opt);
      }
      householdSelect.appendChild(group);
    }
    updateHouseholdCity();
  }

  function updateHouseholdCity() {
    const selected = householdSelect.selectedOptions[0];
    document.getElementById("household-city").textContent = selected ? selected.parentElement.label + " · Sample home" : "Choose a sample home";
  }
  householdSelect.addEventListener("change", updateHouseholdCity);

  async function startSession(householdId) {
    if (busy) return;
    chatReady = false;
    householdKnowledge = null;
    sessionId = null;
    document.getElementById("wiki-content").textContent = "Preparing this household's information…";
    document.getElementById("dashboard-content").textContent = "Preparing this household's information…";
    setBusy(true, "Preparing household information for Wiki and chat…");
    try {
    const { ok, body } = await api("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ household_id: householdId }),
    });
    if (!ok || !body.session_id || !body.chat_ready) throw new Error(body.error || "Could not prepare household information.");
    useHouseholdKnowledge(body.knowledge);
    sessionId = body.session_id;
    lastEstimate = null;
    conversation.innerHTML = "";
    conversation.appendChild(emptyState);
    emptyState.hidden = false;
    chips.hidden = false;
    if (currentView === "dashboard") loadDashboard();
    if (currentView === "wiki") loadWiki();
    } catch (error) {
      addMessage("assistant", "Could not start a conversation. Check your connection and try New again.", false, null);
    } finally {
      setBusy(false);
      // Allow recovery even when the first session request failed.
      householdSelect.disabled = false;
      document.getElementById("new-conversation-btn").disabled = false;
    }
  }

  function evidenceTag(tag, labelOverride) {
    if (!tag) return "";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "evidence-tag";
    btn.textContent = labelOverride || EVIDENCE_LABELS[tag.evidence] || tag.evidence;
    btn.addEventListener("click", () => openEvidenceDialog(tag));
    return btn;
  }

  function openEvidenceDialog(tag) {
    document.getElementById("evidence-kind").textContent = EVIDENCE_LABELS[tag.evidence] || tag.evidence;
    document.getElementById("evidence-note").textContent = tag.note || "No additional detail for this value.";
    document.getElementById("evidence-dialog").showModal();
  }

  function appendChild(parent, el) { if (el) parent.appendChild(el); }

  function riskCard(risk) {
    const card = document.createElement("div");
    card.className = "card";
    if (risk.fallback && risk.fallback.fallback) {
      card.textContent = "We can't give a reliable estimate for this location. " + risk.fallback.reason;
      return card;
    }
    const chipRow = document.createElement("div");
    const chip = document.createElement("span");
    chip.className = "risk-chip risk-" + risk.risk_band.value;
    const band = risk.risk_band.value;
    chip.appendChild(iconCircle(RISK_ICON[band] || "info", `var(${RISK_COLOR_VAR[band] || "--color-risk-moderate"})`, true));
    chip.appendChild(document.createTextNode(band + " risk"));
    chipRow.appendChild(chip);
    appendChild(chipRow, evidenceTag(risk.risk_band));
    const conf = document.createElement("span");
    conf.className = "confidence-label";
    conf.textContent = "How sure we are: " + risk.confidence.value;
    chipRow.appendChild(conf);
    appendChild(chipRow, evidenceTag(risk.confidence));
    card.appendChild(chipRow);

    const reason = document.createElement("p");
    reason.textContent = risk.risk_reason;
    card.appendChild(reason);
    card.appendChild(askButton("Why is this household's power outage risk " + band.toLowerCase() + "?", "Ask about the risk"));
    return card;
  }

  function rangeBar(low, high, maxScale) {
    const wrap = document.createElement("div");
    const label = document.createElement("div");
    label.className = "range-bar-label";
    label.textContent = "Estimated repair time. Your power company has not confirmed these times.";
    wrap.appendChild(label);
    const track = document.createElement("div");
    track.className = "range-bar-track";
    const fill = document.createElement("div");
    fill.className = "range-bar-fill";
    const leftPct = Math.min(100, (low / maxScale) * 100);
    const widthPct = Math.max(2, Math.min(100 - leftPct, ((high - low) / maxScale) * 100));
    fill.style.left = leftPct + "%";
    fill.style.width = widthPct + "%";
    track.appendChild(fill);
    wrap.appendChild(track);
    const values = document.createElement("div");
    values.className = "range-bar-values";
    values.innerHTML = `<span>${low.toFixed(1)} hours</span><span>${high.toFixed(1)} hours</span>`;
    wrap.appendChild(values);
    return wrap;
  }

  function laneHeading(text, iconKind, iconColor) {
    const h4 = document.createElement("h4");
    h4.className = "section-title";
    h4.appendChild(iconCircle(iconKind, iconColor, true));
    h4.appendChild(document.createTextNode(text));
    return h4;
  }

  function alertsCard(alerts) {
    const card = document.createElement("div");
    card.className = "card";
    if (alerts.fallback && alerts.fallback.fallback) {
      card.textContent = alerts.fallback.reason;
      return card;
    }
    card.appendChild(laneHeading("Alerts", "bell", "var(--color-icon-orange)"));
    const header = document.createElement("p");
    const channel = {sms: "text messages", email: "email"}[alerts.channel] || "messages";
    header.textContent = alerts.eligible ? "Example updates are on for " + channel + ". This app does not send messages." : "Example updates are off for this household. Manage real updates through your power company.";
    card.appendChild(header);

    if (alerts.escalation_triggers && alerts.escalation_triggers.length) {
      const triggersTitle = document.createElement("p");
      triggersTitle.textContent = "When an example message would appear";
      card.appendChild(triggersTitle);
      const ul = document.createElement("ul");
      for (const t of alerts.escalation_triggers) {
        const li = document.createElement("li");
        li.textContent = `${t.trigger} → ${t.action}`;
        ul.appendChild(li);
      }
      card.appendChild(ul);
    }

    for (const preview of alerts.message_previews || []) {
      const meta = document.createElement("div");
      meta.className = "sms-meta";
      meta.textContent = `${preview.channel === "SMS" ? "Example text message" : "Example email"} · ${preview.timing}`;
      card.appendChild(meta);
      const bubble = document.createElement("div");
      bubble.className = "sms-bubble";
      bubble.textContent = preview.message;
      card.appendChild(bubble);
    }
    card.appendChild(askButton("Will this app send me updates?", "Ask about updates"));
    return card;
  }

  function estimateMessage(restoration) {
    const card = document.createElement("div");
    card.className = "card";
    card.appendChild(laneHeading("How long repairs could take", "clock", "var(--color-icon-blue)"));
    if (!restoration || restoration.fallback.fallback) {
      const p = document.createElement("p"); p.className = "empty-lane"; p.textContent = "No reliable estimate is available for this location."; card.appendChild(p);
    } else if (restoration.reference_effort_hours.value === 0) {
      const p = document.createElement("p"); p.textContent = "Repairs are complete in this example. If your power is still off, report it to your power company."; card.appendChild(p);
    } else {
      card.appendChild(rangeBar(restoration.low_hours.value, restoration.high_hours.value, 24));
      const tags = document.createElement("div"); appendChild(tags, evidenceTag(restoration.low_hours, "About the shorter time")); appendChild(tags, evidenceTag(restoration.high_hours, "About the longer time")); card.appendChild(tags);
    }
    card.appendChild(askButton("When could my power come back?", "Ask about these times"));
    return card;
  }

  function confirmedMessage(restoration) {
    const card = document.createElement("div"); card.className = "card";
    card.appendChild(laneHeading("What your power company has confirmed", "shield", "var(--color-icon-teal)"));
    const p = document.createElement("p"); p.className = "empty-lane"; p.textContent = "We do not have a live update from your power company. The times here are estimates for this example."; card.appendChild(p);
    return card;
  }

  function actionsMessage(prep) {
    const card = document.createElement("div"); card.className = "card";
    card.appendChild(laneHeading("What you can do", "checklist", "var(--color-icon-green)"));
    const actions = (prep && prep.actions) || [];
    const ordered = [...actions.filter(a => a.startsWith("SAFETY:")), ...actions.filter(a => !a.startsWith("SAFETY:"))];
    const ul = document.createElement("ul"); ordered.slice(0, 3).forEach(a => { const li = document.createElement("li"); li.textContent = a; ul.appendChild(li); });
    card.appendChild(ul);
    if (ordered.length > 3) {
      const more = document.createElement("details"); more.className = "checklist-more";
      const label = document.createElement("summary"); label.textContent = "View full checklist"; more.appendChild(label);
      const rest = document.createElement("ul"); ordered.slice(3).forEach(a => { const li = document.createElement("li"); li.textContent = a; rest.appendChild(li); });
      more.appendChild(rest); card.appendChild(more);
    }
    return card;
  }

  function renderCards(cards, parent) {
    if (!Object.keys(cards).length) return;
    const group = document.createElement("div");
    group.className = "response-details";
    if (cards.risk) { const risk = riskCard(cards.risk); risk.classList.add("risk-summary"); group.appendChild(risk); }
    if (cards.restoration) { const estimate = estimateMessage(cards.restoration); estimate.classList.add("estimate-card"); group.appendChild(estimate); }
    if (cards.prep) {
      const actions = actionsMessage(cards.prep);
      actions.classList.add("actions-card");
      group.appendChild(actions);
    }
    const more = document.createElement("details");
    more.className = "response-more";
    const label = document.createElement("summary");
    label.textContent = cards.alerts ? "Where this came from & example messages" : "Where this information came from";
    more.appendChild(label);
    if (cards.restoration || cards.prep) more.appendChild(confirmedMessage(cards.restoration));
    if (cards.alerts) more.appendChild(alertsCard(cards.alerts));
    if (more.childElementCount > 1) group.appendChild(more);
    if (cards.statistics) {
      const card = document.createElement("div"); card.className = "card statistics-card";
      card.appendChild(laneHeading("How repair times could vary", "info", "var(--color-icon-blue)"));
      const mc = cards.statistics.restoration_simulation;
      if (mc) { const values = document.createElement("p"); values.textContent = `Shorter: ${mc.p10} hours · Middle: ${mc.p50} hours · Longer: ${mc.p90} hours`; card.appendChild(values); }
      const note = document.createElement("p"); note.textContent = cards.statistics.note; card.appendChild(note); group.appendChild(card);
    }
    parent.appendChild(group);
  }

  function addMessage(role, text, offline, cards) {
    emptyState.hidden = true;
    const msg = document.createElement("div");
    msg.className = "message " + role;
    if (offline) {
      const banner = document.createElement("div");
      banner.className = "offline-banner";
      banner.textContent = "Answer from verified household facts. AI was not used.";
      msg.appendChild(banner);
    }
    const p = document.createElement("p");
    p.style.margin = "0";
    const officialLink = /(?:https:\/\/)?(?:appalachianpower\.com\/outages|redcross\.org)\b/g;
    let previous = 0;
    for (const match of text.matchAll(officialLink)) {
      p.appendChild(document.createTextNode(text.slice(previous, match.index)));
      const link = document.createElement("a");
      link.textContent = match[0];
      link.href = match[0].startsWith("https://") ? match[0] : "https://" + match[0];
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      p.appendChild(link);
      previous = match.index + match[0].length;
    }
    p.appendChild(document.createTextNode(text.slice(previous)));
    msg.appendChild(p);
    conversation.appendChild(msg);
    if (cards) renderCards(cards, msg);
    conversation.scrollTop = conversation.scrollHeight;
    return msg;
  }

  function showTyping() {
    const el = document.createElement("div");
    el.className = "typing-indicator";
    el.id = "typing-indicator";
    el.innerHTML = "<span></span><span></span><span></span>";
    conversation.appendChild(el);
    conversation.scrollTop = conversation.scrollHeight;
  }

  function hideTyping() {
    const el = document.getElementById("typing-indicator");
    if (el) el.remove();
  }

  async function sendMessage(text) {
    if (!text.trim() || !sessionId || busy || !chatReady) return;
    text = text.trim();
    setBusy(true);
    addMessage("user", text, false, null);
    showTyping();
    try {
    const payload = { session_id: sessionId, message: text, knowledge_revision: householdKnowledge.revision,
      ...(connection ? { connection } : {}) };
    let { ok, status, body } = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (ok && body.local_request) {
      const prepared = body;
      if (body.knowledge) useHouseholdKnowledge(body.knowledge);
      setBusy(true, `Asking ${connection.model} on your computer…`);
      const messages = [{ role: "system", content: prepared.local_request.system }];
      for (const turn of prepared.local_request.history) {
        messages.push({ role: turn.role === "model" ? "assistant" : "user", content: turn.parts.map(part => part.text || "").join(" ").slice(0,1200) });
      }
      messages.push({ role: "user", content: prepared.local_request.prompt });
      let generated;
      try {
        generated = await ollamaRequest("/api/chat", { model: connection.model, messages, stream: false,
          keep_alive: "10m", options: { temperature: 0, num_ctx: 4096, num_predict: 320 } });
      } catch (error) {
        updateEngine(false, "Ollama disconnected · Open connection settings");
        throw new Error("Cannot reach Ollama on your computer. Open the AI connection below to check its address and browser access, or connect Gemini.");
      }
      if (!generated.message || typeof generated.message.content !== "string" || !generated.message.content.trim() || generated.done_reason === "length") {
        throw new Error("Ollama returned an empty or incomplete answer. Please try again.");
      }
      ({ ok, status, body } = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, turn_id: prepared.turn_id, local_result: generated.message.content }) }));
    }
    hideTyping();
    if (!ok && status === 502) {
      updateEngine(false, "AI connection needs attention");
      addMessage("assistant", body.message || "I couldn't reach the AI provider (" + body.category + ").", false, null);
      offerOfflineMode();
      return;
    }
    if (!ok || typeof body.text !== "string") throw new Error(body.error || "Could not prepare a reply.");
    if (body.knowledge) useHouseholdKnowledge(body.knowledge);
    const msg = addMessage("assistant", body.text, body.offline, body.cards);
    if (body.knowledge_revision) {
      const wikiLink = document.createElement("button");
      wikiLink.type = "button";
      wikiLink.className = "wiki-source-link";
      wikiLink.textContent = "See the household facts used for this answer ↗";
      wikiLink.addEventListener("click", () => setView("wiki"));
      msg.appendChild(wikiLink);
    }
    if (body.scenario_change && body.scenario_change.before.low_hours && body.scenario_change.after.low_hours) {
      const change = body.scenario_change;
      const range = document.createElement("div");
      range.className = "before-after";
      range.textContent = `${change.before.low_hours.value}-${change.before.high_hours.value} hours → ${change.after.low_hours.value}-${change.after.high_hours.value} hours`;
      msg.prepend(range);
    }
    if (body.local_model || body.gemini_model || body.local_fallback) {
      const note = document.createElement("div");
      note.className = "reply-source";
      note.textContent = body.local_model || body.gemini_model ? `${body.local_model ? "Ollama" : "Gemini"} · ${body.local_model || body.gemini_model} · Household context`
        : (body.local_error && body.local_error.category === "validation"
          ? "We used the household facts directly because the AI answer could not be verified."
          : "AI is unavailable. This answer comes directly from your household's information.");
      msg.prepend(note);
    }
    if (body.local_model || body.gemini_model) updateEngine(true);
    if (body.cards && body.cards.restoration && !body.cards.restoration.fallback.fallback) {
      lastEstimate = body.cards.restoration;
    }
    if (currentView === "dashboard") loadDashboard();
    if (currentView === "wiki") loadWiki();
    } catch (error) {
      hideTyping();
      const msg = addMessage("assistant", error.name === "TimeoutError"
        ? "The reply took too long. Please try again, or choose offline mode in Settings."
        : "I couldn't complete that request. " + (error.message || "Check your connection and try again."), false, null);
      const retry = document.createElement("button");
      retry.type = "button";
      retry.textContent = "Try again";
      retry.addEventListener("click", () => { if (!busy) { retry.remove(); sendMessage(text); } });
      msg.appendChild(retry);
    } finally {
      hideTyping();
      setBusy(false);
      messageInput.focus();
    }
  }

  function offerOfflineMode() {
    const card = document.createElement("div");
    card.className = "card";
    const p = document.createElement("p");
    p.textContent = "Switch to offline explanation mode to keep going?";
    card.appendChild(p);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Use offline mode";
    btn.addEventListener("click", async () => {
      connection = { ...(connection || { provider: "local" }), offline_mode: true };
      updateEngine(false);
      card.remove();
      addMessage("assistant", "AI is off. You can now ask questions using the household facts.", true, null);
    });
    card.appendChild(btn);
    conversation.appendChild(card);
    conversation.scrollTop = conversation.scrollHeight;
  }

  async function runWhatIf(action) {
    if (!sessionId || busy) return;
    setBusy(true, "Updating Wiki and chat for this example…");
    try {
    const { ok, body } = await api("/api/whatif", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, action }),
    });
    if (!ok) throw new Error(body.error || "Could not update the scenario.");
    if (!body.chat_ready) throw new Error("The updated household information is not ready yet.");
    useHouseholdKnowledge(body.knowledge);

    emptyState.hidden = true;
    const msg = document.createElement("div");
    msg.className = "message assistant";

    if (!body.after.fallback.fallback && body.before.low_hours && body.after.low_hours) {
      const before = body.before, after = body.after;
      const ba = document.createElement("div");
      ba.className = "before-after";
      ba.innerHTML = `<span class="before">${before.low_hours.value}-${before.high_hours.value} hours</span><span>→</span><span class="after">${after.low_hours.value}-${after.high_hours.value} hours</span>`;
      msg.appendChild(ba);
    }

    const label = {
      block_access: "The example now has a blocked road. Wiki and chat have the updated repair times.",
      clear_access: "The road is clear in this example. Wiki and chat have been updated.",
      add_crews: "We added two repair teams to the example. Wiki and chat have been updated.",
      complete_repairs: "Repairs are complete in this example. This does not confirm that power is back at a real address.",
      reset: "The example is back to its starting point. Wiki and chat have been updated.",
    }[action];
    const p = document.createElement("p");
    p.textContent = label;
    msg.appendChild(p);

    conversation.appendChild(msg);
    renderCards({ risk: body.risk, restoration: body.after, prep: body.prep, alerts: body.alerts }, msg);
    conversation.scrollTop = conversation.scrollHeight;

    if (currentView === "dashboard") loadDashboard();
    if (currentView === "wiki") loadWiki();
    } catch (error) {
      addMessage("assistant", "Could not update the scenario. " + error.message, false, null);
    } finally { setBusy(false); }
  }

  document.getElementById("empty-state").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-question]");
    if (btn) sendMessage(btn.dataset.question);
  });

  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    if (busy || !sessionId) return;
    const text = messageInput.value;
    messageInput.value = "";
    sendMessage(text);
  });

  chips.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-action]");
    if (btn) runWhatIf(btn.dataset.action);
  });

  householdSelect.addEventListener("change", () => startSession(householdSelect.value));

  document.getElementById("new-conversation-btn").addEventListener("click", () => startSession(householdSelect.value));

  document.getElementById("evidence-close").addEventListener("click", () => {
    document.getElementById("evidence-dialog").close();
  });

  const settingsDialog = document.getElementById("settings-dialog");
  function updateProviderFields() {
    document.getElementById("gemini-settings").hidden = document.getElementById("provider-select").value !== "gemini";
    document.getElementById("local-settings").hidden = document.getElementById("provider-select").value !== "local";
  }
  document.getElementById("provider-select").addEventListener("change", updateProviderFields);
  updateProviderFields();
  function settingsStatus(body) {
    if (body.offline_mode) return "AI is off. Answers use this household’s Wiki facts.";
    if (body.connected) return "Connected — " + (body.provider === "local" ? "Ollama · " : "") + body.model;
    if (body.last_error) return body.last_error.message || "Connection unavailable (" + body.last_error.category + ").";
    return "AI is not connected. Start Ollama on this computer, or turn on answers without AI.";
  }
  async function openSettings() {
    settingsDialog.showModal();
    document.getElementById("settings-status").textContent = "Checking connection…";
    try {
    if (!connection) await loadConnection();
    document.getElementById("offline-toggle").checked = connection.offline_mode;
    document.getElementById("provider-select").value = connection.provider;
    document.getElementById("ollama-url-input").value = connection.ollama_url || "http://127.0.0.1:11434";
    document.getElementById("ollama-model-input").value = connection.provider === "local" ? connection.model : "llama3.2:3b";
    document.getElementById("ollama-origin-help").textContent = `OLLAMA_ORIGINS=${location.origin}`;
    updateProviderFields();
    document.getElementById("settings-status").textContent = settingsStatus({ ...connection, connected: connectionState === "connected" });
    } catch (_) { document.getElementById("settings-status").textContent = "Could not load Settings. Check the app connection and try again."; }
  }
  document.getElementById("settings-btn").addEventListener("click", openSettings);
  document.getElementById("engine-status-btn").addEventListener("click", openSettings);
  document.getElementById("settings-close").addEventListener("click", () => settingsDialog.close());
  document.getElementById("settings-save").addEventListener("click", async () => {
    const save = document.getElementById("settings-save");
    save.disabled = true;
    document.getElementById("settings-status").textContent = "Saving and checking connection…";
    try {
    const apiKey = document.getElementById("api-key-input").value.trim();
    const offline = document.getElementById("offline-toggle").checked;
    const provider = document.getElementById("provider-select").value;
    const previous = connection;
    const candidate = { ...connection, provider, offline_mode: offline };
    if (provider === "local") {
      candidate.model = document.getElementById("ollama-model-input").value.trim() || "llama3.2:3b";
      candidate.ollama_url = document.getElementById("ollama-url-input").value.trim();
      candidate.browser_local = true;
    } else if (!offline) {
      const key = apiKey || (connection.provider === "gemini" ? connection.api_key : "");
      if (key) {
        const { ok, body } = await api("/api/connection", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: key }) });
        if (!ok) throw new Error(body.message || body.error || "Gemini connection failed.");
        candidate.api_key = key;
        candidate.model = body.model;
      } else if (!(connection.provider === "gemini" && connectionState === "connected")) {
        throw new Error("Enter your Gemini API key to connect.");
      }
      candidate.browser_local = false;
    }
    connection = candidate;
    try {
      if (!offline && provider === "local") await checkOllama();
    } catch (error) {
      connection = previous;
      if (error instanceof TypeError) throw new Error("Your browser could not reach Ollama. Allow local network access for this site, keep Ollama running, and check the connection help below.");
      throw error;
    }
    updateEngine(!offline);
    document.getElementById("settings-status").textContent = settingsStatus({ ...connection, connected: !offline });
    } catch (error) { document.getElementById("settings-status").textContent = error.message || "Could not connect. Check your engine and try again."; }
    finally { save.disabled = false; document.getElementById("api-key-input").value = ""; }
  });

  document.getElementById("theme-select").addEventListener("change", (e) => setTheme(e.target.value));

  // Storm activity dashboard
  const ALERT_LABELS = {
    pre_storm: "Before the storm",
    outage_confirmed: "Damage in the example",
    estimate_updated: "Estimate updated",
    restoration_complete: "Repairs done",
  };
  function repairLabel(value) {
    return ({transformer:"Replace the transformer",primary:"Repair the power line",primary_wire:"Repair the power line",pole:"Replace the power pole"})[value] || value.replace(/_/g, " ");
  }
  function eventText(event) {
    if (event.type === "whatif_applied") return "Example changed: " + ({block_access:"road blocked",clear_access:"road open",add_crews:"more repair teams",complete_repairs:"repairs done",reset:"started over"}[event.detail.action] || "updated");
    if (event.type === "estimate_changed") return `Estimate changed: ${event.detail.before[0]}-${event.detail.before[1]} hours → ${event.detail.after[0]}-${event.detail.after[1]} hours`;
    if (event.type === "alert_previewed") return "Example message shown: " + (ALERT_LABELS[event.detail.alert_type] || event.detail.alert_type);
    return event.type;
  }

  function dashboardSection(title, iconKind, iconColor) {
    const section = document.createElement("div");
    section.className = "dashboard-section";
    const h3 = document.createElement("h3");
    h3.className = "section-title";
    if (iconKind) h3.appendChild(iconCircle(iconKind, iconColor, true));
    h3.appendChild(document.createTextNode(title));
    section.appendChild(h3);
    return section;
  }

  function renderDashboard(data) {
    const root = document.getElementById("dashboard-content");
    root.innerHTML = "";

    if (data.risk.fallback && data.risk.fallback.fallback) {
      const p = document.createElement("p");
      p.textContent = "We can't give a reliable estimate for this location. " + data.risk.fallback.reason;
      root.appendChild(p);
      return;
    }

    const grid = document.createElement("div");
    grid.className = "dashboard-grid";

    const riskSection = dashboardSection("Risk", "warning", "var(--color-icon-orange)");
    riskSection.appendChild(riskCard(data.risk));
    grid.appendChild(riskSection);

    const estimateSection = dashboardSection("How long repairs could take", "clock", "var(--color-icon-blue)");
    if (data.restoration.reference_effort_hours.value === 0) {
      const p = document.createElement("p");
      p.textContent = "Repairs are done in this example. If your power is still off, report it to your power company.";
      estimateSection.appendChild(p);
    } else {
      if (data.previous_estimate && (data.previous_estimate.low_hours !== data.restoration.low_hours.value || data.previous_estimate.high_hours !== data.restoration.high_hours.value)) {
        const ba = document.createElement("div");
        ba.className = "before-after";
        ba.innerHTML = `<span class="before">${data.previous_estimate.low_hours}-${data.previous_estimate.high_hours} hours</span><span>→</span><span class="after">${data.restoration.low_hours.value}-${data.restoration.high_hours.value} hours</span>`;
        estimateSection.appendChild(ba);
      }
      estimateSection.appendChild(rangeBar(data.restoration.low_hours.value, data.restoration.high_hours.value, 24));
      const tagRow = document.createElement("div");
      appendChild(tagRow, evidenceTag(data.restoration.low_hours, "About the shorter time"));
      appendChild(tagRow, evidenceTag(data.restoration.high_hours, "About the longer time"));
      estimateSection.appendChild(tagRow);
    }
    grid.appendChild(estimateSection);
    root.appendChild(grid);

    const simulationSection = dashboardSection("How repair times could vary", "info", "var(--color-icon-blue)");
    const mc = data.monte_carlo;
    if (mc) {
      const fan = document.createElement("div");
      fan.className = "probability-fan";
      [ ["Shorter time", mc.p10], ["Middle time", mc.p50], ["Longer time", mc.p90] ].forEach(([label, value]) => {
        const item = document.createElement("div"); item.className = "fan-item";
        item.innerHTML = `<span>${label}</span><strong>${value.toFixed(1)} hours</strong>`;
        fan.appendChild(item);
      });
      simulationSection.appendChild(fan);
    }
    const topology = document.createElement("div"); topology.className = "topology-flow";
    (data.topology || []).forEach((node, index) => {
      const step = document.createElement("div"); step.className = "topology-step";
      step.innerHTML = `<span class="topology-node">${index + 1}</span><span>${({substation_breaker:"Local power station",sectionalizer_fuse:"Power-line protection",service_transformer:"Neighborhood transformer"})[node.stage] || node.stage.replace(/_/g, " ")}</span><small>${({restored_first:"First step",queued:"Later step",complete:"Done"})[node.status] || node.status.replace(/_/g, " ")}</small>`;
      topology.appendChild(step);
    });
    const explanation = document.createElement("p");
    explanation.textContent = householdKnowledge ? householdKnowledge.statistics.note : "These are possible repair times, not a confirmed schedule.";
    simulationSection.appendChild(explanation);
    const powerHeading = document.createElement("h4"); powerHeading.textContent = "How electricity reaches this home"; simulationSection.appendChild(powerHeading);
    simulationSection.appendChild(topology);
    simulationSection.appendChild(askButton("What do the shorter, middle, and longer times mean?"));
    root.appendChild(simulationSection);

    const timelineSection = dashboardSection("Example repair steps", "list", "var(--color-icon-teal)");
    const jobs = (data.timeline && data.timeline.jobs) || [];
    if (!jobs.length) {
      const p = document.createElement("p");
      p.className = "empty-lane";
      p.textContent = "No repair jobs are needed for this home in the example.";
      timelineSection.appendChild(p);
    } else {
      for (const job of jobs) {
        const row = document.createElement("div");
        row.className = "timeline-row";
        const crew = document.createElement("span");
        crew.className = "crew-badge";
        crew.textContent = "Team " + job.crew;
        row.appendChild(crew);
        const label = document.createElement("span");
        label.textContent = repairLabel(job.label.value) + " — " + job.duration_hours.value + " hours";
        row.appendChild(label);
        const status = document.createElement("span");
        status.className = "status-badge status-" + job.status;
        status.textContent = ({in_progress:"First job",pending:"Waiting",queued:"Waiting",complete:"Done"})[job.status] || job.status.replace(/_/g, " ");
        row.appendChild(status);
        timelineSection.appendChild(row);
      }
    }
    timelineSection.appendChild(askButton("What changes when I try a different example?", "Ask about repair teams"));
    root.appendChild(timelineSection);

    const alertsSection = dashboardSection("Example messages", "bell", "var(--color-icon-orange)");
    for (const alert of data.alerts) {
      const row = document.createElement("div");
      row.className = "alert-row";
      const left = document.createElement("div");
      const name = document.createElement("div");
      name.className = "alert-name";
      name.textContent = ALERT_LABELS[alert.type] || alert.type;
      left.appendChild(name);
      const timing = document.createElement("div");
      timing.className = "alert-timing";
      timing.textContent = alert.timing;
      left.appendChild(timing);
      if (alert.triggered) {
        const msg = document.createElement("div");
        msg.className = "alert-msg";
        msg.textContent = alert.message;
        left.appendChild(msg);
      }
      row.appendChild(left);
      const badge = document.createElement("span");
      badge.className = alert.triggered ? "triggered-badge" : "not-triggered-badge";
      badge.textContent = alert.triggered ? "Example shown" : "Not shown";
      row.appendChild(badge);
      alertsSection.appendChild(row);
    }
    root.appendChild(alertsSection);

    const eventsSection = dashboardSection("Changes you have tried", "clock", "var(--color-icon-teal)");
    if (!data.events.length) {
      const p = document.createElement("p");
      p.className = "empty-lane";
      p.textContent = "Choose an example below to see what could change.";
      eventsSection.appendChild(p);
    } else {
      for (const event of data.events) {
        const row = document.createElement("div");
        row.className = "event-row";
        const time = document.createElement("time");
        time.dateTime = event.timestamp;
        time.textContent = new Date(event.timestamp).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
        row.appendChild(time);
        const span = document.createElement("span");
        span.textContent = eventText(event);
        row.appendChild(span);
        eventsSection.appendChild(row);
      }
    }
    root.appendChild(eventsSection);
    loadWeatherMap(root);
  }

  async function loadWeatherMap(root) {
    const section = dashboardSection("Weather & outage risk outlook", "warning", "var(--color-icon-orange)");
    const note = document.createElement("p"); note.className = "weather-disclaimer";
    note.textContent = "Loading NWS alerts…"; section.appendChild(note);
    const controls = document.createElement("div"); controls.className = "weather-controls";
    const label = document.createElement("label"); label.textContent = "Forecast day ";
    const dayPicker = document.createElement("select"); dayPicker.setAttribute("aria-label", "Forecast day");
    label.appendChild(dayPicker); controls.appendChild(label); section.appendChild(controls);
    const detail = document.createElement("p"); detail.className = "weather-disclaimer";
    detail.setAttribute("aria-live", "polite"); detail.textContent = "Loading seven-day seasonal outlook…"; section.appendChild(detail);
    const map = document.createElement("div"); map.id = "weather-map"; map.className = "weather-map";
    section.appendChild(map); root.appendChild(section);
    if (!window.L) { map.textContent = "Map unavailable. Check the National Weather Service for current warnings."; return; }
    const leafletMap = L.map(map, { scrollWheelZoom: false }).setView([38.5, -88], 5);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap contributors" }).addTo(leafletMap);
    const alerts = L.layerGroup().addTo(leafletMap);
    const risk = L.layerGroup().addTo(leafletMap);
    const events = L.layerGroup();
    L.control.layers(null, { "Live NWS alerts": alerts, "Outage risk index (estimated)": risk, "Potential weather events": events }, { collapsed: false }).addTo(leafletMap);
    const popup = lines => {
      const el = document.createElement("div");
      lines.forEach(line => { const p = document.createElement("p"); p.textContent = line; el.appendChild(p); });
      return el;
    };
    const loadAlerts = async () => {
      try {
        const response = await fetch("/api/weather/alerts"); if (!response.ok) throw new Error();
        const geo = await response.json();
        if (!geo.live) throw new Error();
        const colors = { Extreme: "#8e24aa", Severe: "#d32f2f", Moderate: "#ef6c00", Minor: "#2e7d32" };
        L.geoJSON(geo, { style: f => ({ color: colors[f.properties.severity] || "#546e7a", fillOpacity: .25, weight: 1 }),
          onEachFeature: (f, layer) => layer.bindPopup(popup([f.properties.event, f.properties.area, f.properties.headline || "Active NWS alert"])) }).addTo(alerts);
        note.textContent = `${geo.features.length} active NWS alerts. Some alerts have no map geometry. Alerts are separate from modeled risk.`;
      } catch (_) { note.textContent = "Live NWS alerts unavailable. Forecast layers have independent availability."; }
    };
    const loadOutlook = async () => {
      try {
        const response = await fetch("/api/weather/outlook"); if (!response.ok) throw new Error();
        const geo = await response.json();
        const dates = [...new Set(geo.features.flatMap(f => f.properties.days.map(d => d.date)))].sort();
        if (!dates.length) throw new Error();
        dates.forEach(date => { const option = document.createElement("option"); option.value = date; option.textContent = date; dayPicker.appendChild(option); });
        const render = () => {
          risk.clearLayers(); events.clearLayers();
          const selected = dayPicker.value;
          const month = Number(selected.slice(5, 7));
          const season = month === 12 || month <= 2 ? "Winter" : month <= 5 ? "Spring" : month <= 8 ? "Summer" : "Autumn";
          const summaries = [];
          geo.features.forEach(f => {
            const p = f.properties, day = p.days.find(d => d.date === selected); if (!day) return;
            const latlng = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
            const color = { High: "#dc2626", Elevated: "#d97706", Low: "#15803d" }[day.band];
            const c = day.conditions;
            const info = [p.name + " · " + selected, `${day.band} weather-related outage risk · ${day.index}/100 index (not a probability)`,
              `Gusts ${c.gust} km/h · precipitation ${c.rain} mm · snow ${c.snow} cm · ${c.low}–${c.high} °C`,
              day.drivers.length ? "Drivers: " + day.drivers.join(", ") : "No screening thresholds exceeded.",
              day.history_days ? `${day.history_days} historical days in this calendar month; ${Math.round(day.historical_hazard_day_fraction * 100)}% exceeded a weather threshold.` : "Historical baseline unavailable; forecast-only score."];
            L.circleMarker(latlng, { radius: 13, color, fillColor: color, fillOpacity: .65, weight: 2 }).bindPopup(popup(info)).addTo(risk);
            if (day.drivers.length) L.marker(latlng).bindPopup(popup(info)).addTo(events);
            summaries.push(`${p.name}: ${day.band} (${day.index}/100)`);
          });
          detail.textContent = `${season} · ${selected} · ` + summaries.join(" · ") + (geo.errors.length ? " · " + geo.errors.join("; ") : "");
        };
        dayPicker.addEventListener("change", render); render();
        const method = document.createElement("details");
        const summary = document.createElement("summary"); summary.textContent = "How this estimate works"; method.appendChild(summary);
        method.appendChild(popup([geo.method, geo.coverage, "Screening thresholds: gusts ≥50 km/h, precipitation ≥20 mm/day, snow ≥5 cm/day, heat ≥38.7 °C or cold ≤−16.7 °C. Low <40; elevated 40–69; high ≥70. These are prototype thresholds, not official warnings.", "Green: low · Amber: elevated · Red: high. Updated " + new Date(geo.generated_at).toLocaleString()]));
        const source = document.createElement("a"); source.href = "https://open-meteo.com/"; source.textContent = "Weather data: Open-Meteo"; source.target = "_blank"; source.rel = "noopener"; method.appendChild(source);
        section.appendChild(method);
      } catch (_) { detail.textContent = "Seasonal outlook unavailable. No risk estimate can be shown. Reopen Storm Activity to retry."; dayPicker.disabled = true; }
    };
    await Promise.allSettled([loadAlerts(), loadOutlook()]);
  }

  async function loadDashboard() {
    if (!sessionId) return;
    const requestedSession = sessionId;
    try {
      const { ok, body } = await api("/api/dashboard?session_id=" + encodeURIComponent(requestedSession));
      if (requestedSession !== sessionId || currentView !== "dashboard") return;
      if (!ok) throw new Error("Dashboard unavailable");
      renderDashboard(body);
    } catch (_) { document.getElementById("dashboard-content").textContent = "Could not load the example. Select Storm Activity again to retry."; }
  }

  function wikiSection(id, title) {
    const section = document.createElement("section");
    section.id = "wiki-" + id;
    section.className = "wiki-section";
    const heading = document.createElement("h2");
    heading.textContent = title;
    section.appendChild(heading);
    return section;
  }

  function renderWiki(data) {
    const root = document.getElementById("wiki-content");
    root.replaceChildren();
    const title = document.createElement("h2");
    title.className = "wiki-household";
    title.textContent = data.household.display_name + " · " + data.household.city;
    root.appendChild(title);
    const status = document.createElement("p");
    status.className = "honesty-strip";
    status.textContent = "Example only · " + (data.scenario.repairs_complete ? "Repairs marked complete" : "Repairs still needed") +
      " · " + (data.scenario.access_blocked ? "Road blocked" : "Road open");
    root.appendChild(status);
    const nav = document.createElement("nav");
    nav.className = "wiki-toc";
    nav.setAttribute("aria-label", "On this Wiki page");
    for (const [id, label] of [["summary", "At a glance"], ["statistics", "Possible repair times"], ["actions", "Your next steps"], ["questions", "Common questions"]]) {
      const a = document.createElement("a"); a.href = "#wiki-" + id; a.textContent = label; nav.appendChild(a);
    }
    root.appendChild(nav);
    const summary = wikiSection("summary", "What's happening to this household");
    if (data.fallback.fallback) {
      const note = document.createElement("p"); note.textContent = data.fallback.reason || "We can't give a reliable estimate for this location."; summary.appendChild(note);
    } else {
      const grid = document.createElement("div"); grid.className = "dashboard-grid";
      grid.appendChild(riskCard(data.risk)); grid.appendChild(estimateMessage(data.restoration)); summary.appendChild(grid);
      const confidence = document.createElement("p"); confidence.textContent = data.risk.confidence.note; summary.appendChild(confidence);
      summary.appendChild(askButton("How sure are these estimates?", "Ask about how sure we are"));
      const needs = Object.entries(data.household.declared_needs).filter(([, value]) => value).map(([key]) => ({power_bank:"Power bank available",needs_phone_for_work:"Needs phone for work",medical_device:"Medical equipment needs electricity"}[key] || key.replace(/_/g," ")));
      const note = document.createElement("p"); note.className = "wiki-needs";
      note.textContent = "What you shared: " + (needs.join(" · ") || "No extra needs shared") + "."; summary.appendChild(note);
      const jobs = data.timeline.jobs || [];
      const list = document.createElement("ul");
      for (const job of jobs) { const li = document.createElement("li"); li.textContent = repairLabel(job.label.value) + ": " + job.duration_hours.value + " hours of work for one team"; list.appendChild(li); }
      if (jobs.length) summary.appendChild(list);
    }
    root.appendChild(summary);
    const stats = wikiSection("statistics", "Possible repair times");
    const mc = data.statistics.restoration_simulation;
    if (mc) {
      const fan = document.createElement("div"); fan.className = "probability-fan";
      for (const [label, value] of [["Shorter time", mc.p10], ["Middle time", mc.p50], ["Longer time", mc.p90]]) {
        const item = document.createElement("div"); item.className = "fan-item";
        const caption = document.createElement("span"); caption.textContent = label;
        const number = document.createElement("strong"); number.textContent = value.toFixed(1) + " hours";
        item.append(caption, number); fan.appendChild(item);
      }
      stats.appendChild(fan);
      const runs = document.createElement("p"); runs.textContent = "Based on " + mc.iterations.toLocaleString() + " computer examples of these repairs."; stats.appendChild(runs);
    }
    const modelNote = document.createElement("p"); modelNote.className = "wiki-model-note"; modelNote.textContent = data.statistics.note; stats.appendChild(modelNote);
    stats.appendChild(askButton("What do the shorter, middle, and longer times mean?"));
    root.appendChild(stats);
    const actions = wikiSection("actions", "What you can do now");
    const checklist = document.createElement("ul");
    for (const action of data.prep.actions) { const li = document.createElement("li"); li.textContent = action; checklist.appendChild(li); }
    actions.appendChild(checklist);
    actions.appendChild(askButton("What should I do now?", "Ask about your next steps"));
    if (!data.fallback.fallback) actions.appendChild(alertsCard(data.alerts));
    root.appendChild(actions);
    const faq = wikiSection("questions", "Common questions");
    for (const item of data.faqs) {
      const details = document.createElement("details"); details.className = "wiki-faq";
      const question = document.createElement("summary"); question.textContent = item.question;
      const answer = document.createElement("p"); answer.textContent = item.answer;
      details.append(question, answer, askButton(item.question, "Ask chat about this")); faq.appendChild(details);
    }
    root.appendChild(faq);
    const links = document.createElement("p"); links.className = "wiki-official-links";
    for (const [label, href] of [["Official outage center", "https://appalachianpower.com/outages"], ["Red Cross relief information", "https://redcross.org"]]) {
      const a = document.createElement("a"); a.textContent = label; a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; links.appendChild(a);
    }
    root.appendChild(links);
    const sources = document.createElement("p"); sources.className = "reply-source";
    sources.textContent = "These household facts also power Ask. Changing your household or scenario keeps both views in sync.";
    root.appendChild(sources);
  }

  async function loadWiki() {
    if (!sessionId) return;
    const requestedSession = sessionId;
    const root = document.getElementById("wiki-content");
    if (householdKnowledge) renderWiki(householdKnowledge);
    else root.textContent = "Preparing this household's information…";
    try {
      const { ok, body } = await api("/api/wiki?session_id=" + encodeURIComponent(requestedSession));
      if (requestedSession !== sessionId) return;
      if (!ok) throw new Error("Wiki unavailable");
      useHouseholdKnowledge(body);
      if (currentView === "wiki") renderWiki(body);
    } catch (_) { root.textContent = "Could not load household information. Select Wiki again to retry."; }
  }

  function setView(view) {
    currentView = view;
    document.querySelector(".app").dataset.view = view;
    document.querySelector(".skip-link").href = view === "ask" ? "#conversation" : view === "dashboard" ? "#dashboard-view" : "#wiki-view";
    const askBtn = document.getElementById("view-ask-btn");
    const dashBtn = document.getElementById("view-dashboard-btn");
    const dashView = document.getElementById("dashboard-view");
    const wikiBtn = document.getElementById("view-wiki-btn");
    const wikiView = document.getElementById("wiki-view");
    wikiBtn.setAttribute("aria-pressed", String(view === "wiki"));
    wikiView.hidden = view !== "wiki";
    composer.hidden = view !== "ask";
    document.getElementById("chat-status").hidden = view !== "ask";
    if (view === "ask") {
      conversation.hidden = false;
      dashView.hidden = true;
      askBtn.setAttribute("aria-pressed", "true");
      dashBtn.setAttribute("aria-pressed", "false");
    } else if (view === "dashboard") {
      conversation.hidden = true;
      dashView.hidden = false;
      askBtn.setAttribute("aria-pressed", "false");
      dashBtn.setAttribute("aria-pressed", "true");
      loadDashboard();
    } else {
      conversation.hidden = true;
      dashView.hidden = true;
      askBtn.setAttribute("aria-pressed", "false");
      dashBtn.setAttribute("aria-pressed", "false");
      loadWiki();
    }
    positionNavigation();
    const panel = view === "ask" ? conversation : view === "dashboard" ? dashView : wikiView;
    if (!reducedMotion.matches) {
      panel.getAnimations().forEach(animation => animation.cancel());
      panel.animate([{ opacity: .6 }, { opacity: 1 }], { duration: 160, easing: "ease-out" });
    }
  }

  document.getElementById("view-ask-btn").addEventListener("click", () => setView("ask"));
  document.getElementById("view-dashboard-btn").addEventListener("click", () => setView("dashboard"));
  document.getElementById("view-wiki-btn").addEventListener("click", () => setView("wiki"));
  document.getElementById("open-wiki-btn").addEventListener("click", () => setView("wiki"));

  applyStoredTheme();
  positionNavigation();
  setBusy(false, "Loading sample households…");
  Promise.all([loadConnection(), loadHouseholds()]).then(() => startSession(householdSelect.value)).catch(() => {
    document.getElementById("chat-status").textContent = "Could not load households. Refresh to try again.";
  });
})();
