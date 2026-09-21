let csrfToken = "";
let controlState = { connected: false, hydrated: false };
let portfolioState = { labs: [], edges: [] };
let isConnecting = false;
let runtimeAction = "start";
let renderedRoute = "";
// Which lab this browser is looking at. Selection is per viewer, never a
// server-side switch, so many browsers can inspect different labs at once.
let selectedLabId = null;

function readStored(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value == null ? fallback : JSON.parse(value);
  } catch (error) {
    return fallback;
  }
}

function writeStored(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    /* per-viewer convenience only */
  }
}

let openTabs = Array.isArray(readStored("efferents-open-labs", []))
  ? readStored("efferents-open-labs", [])
  : [];
const storedSelected = readStored("efferents-selected-lab", null);
if (typeof storedSelected === "string" && storedSelected) selectedLabId = storedSelected;

function labPath(kind) {
  return `/api/labs/${encodeURIComponent(selectedLabId)}/${kind}`;
}
let labBudget = { spent: 0, cap: 0 };
let portfolioBudget = { spent: 0, cap: 0 };

function renderBudget() {
  const route = currentRoute();
  const meta = document.getElementById("budget-meta");
  const isNetwork = route === "network";
  const budget = isNetwork ? portfolioBudget : labBudget;
  const show = isNetwork
    ? portfolioState.labs.length > 0
    : route === "observe" && controlState.connected;
  meta.hidden = !show;
  if (!show) return;
  const percent = budget.cap > 0
    ? Math.min(100, Math.max(0, (budget.spent / budget.cap) * 100))
    : 0;
  text(
    "budget",
    `${isNetwork ? "all labs" : "this lab"} · ` +
      `$${budget.spent.toFixed(2)} / $${budget.cap.toFixed(2)} daily`,
  );
  document.getElementById("budget-fill").style.width = `${percent}%`;
}

async function getJSON(path) {
  const response = await fetch(path);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `${path} returned ${response.status}`);
  }
  return payload;
}

async function postJSON(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Efferents-CSRF": csrfToken,
    },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || `${path} returned ${response.status}`);
  }
  return body;
}

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function text(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value == null ? "" : String(value);
}

function showMessage(id, message = "", type = "") {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = message;
  element.className = `form-message${type ? ` ${type}` : ""}`;
}

function formatMetric(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  const magnitude = Math.abs(number);
  if (magnitude !== 0 && (magnitude >= 10000 || magnitude < 0.0001)) {
    return number.toExponential(3);
  }
  return number.toLocaleString(undefined, { maximumSignificantDigits: 6 });
}

function quantile(values, fraction) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const position = (sorted.length - 1) * fraction;
  const lower = Math.floor(position);
  const remainder = position - lower;
  return sorted[lower + 1] == null
    ? sorted[lower]
    : sorted[lower] + remainder * (sorted[lower + 1] - sorted[lower]);
}

function compactRunId(value) {
  const runId = String(value || "");
  if (runId.length <= 22) return runId || "—";
  return `…${runId.slice(-21)}`;
}

function formatTimestamp(value, compact = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value).replace("T", " ").slice(0, compact ? 16 : 19);
  }
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "UTC",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: compact ? undefined : "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type) => parts.find((part) => part.type === type)?.value || "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}` +
    (compact ? "" : `:${get("second")}`);
}

function formatRelativeTime(value) {
  if (!value) return "no activity";
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return formatTimestamp(value, true);
  const elapsed = Math.max(0, Date.now() - timestamp);
  const minutes = Math.floor(elapsed / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function isCluster() {
  return controlState.mode === "cluster";
}

function isJoined() {
  return Boolean(controlState.session && controlState.session.joined);
}

function currentRoute() {
  const route = window.location.hash.replace(/^#/, "");
  if (route === "steer") return "observe";
  const known = ["connect", "observe", "network", "join", "intake"];
  if (known.includes(route)) return route;
  return isCluster() ? "network" : "connect";
}

function renderRoute() {
  let route = currentRoute();
  if (isCluster()) {
    if (controlState.hydrated && !isJoined()) {
      route = "join";
    } else if (route === "join") {
      renderTerminalPanel(controlState.session);
      document.getElementById("join-form").hidden = true;
      text("join-title", `You are in, ${(controlState.session.owner || {}).name || "friend"}`);
    } else if (route === "connect") {
      route = "network";
    } else if (route === "observe" && controlState.hydrated && !controlState.connected) {
      route = "network";
    }
  } else if (["join", "intake"].includes(route)) {
    route = "connect";
  } else if (controlState.hydrated && !controlState.connected && !["connect", "network"].includes(route)) {
    route = "connect";
  }
  if (window.location.hash !== `#${route}`) {
    history.replaceState(null, "", `#${route}`);
  }
  if (route === "intake") ensureIntakeLoaded();
  document.querySelectorAll("[data-route-view]").forEach((view) => {
    view.hidden = view.dataset.routeView !== route;
  });
  document.querySelectorAll("[data-route-link]").forEach((link) => {
    if (link.dataset.routeLink === route) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
  const labRail = document.getElementById("lab-rail");
  const showRail = !["connect", "join"].includes(route) && portfolioState.labs.length > 0;
  labRail.hidden = !showRail;
  document.getElementById("workspace-frame").classList.toggle("with-lab-rail", showRail);
  if (renderedRoute && renderedRoute !== route) window.scrollTo(0, 0);
  renderedRoute = route;
  if (isCluster() && isJoined() && !controlState.connected) {
    const owner = controlState.session.owner || {};
    const badge = document.getElementById("status-badge");
    badge.className = "status-badge joined";
    text("status-text", owner.name || "joined");
  }
  document.title = `efferents — ${route}`;
  renderLabTabs();
  renderBudget();
}

function initRouting() {
  window.addEventListener("hashchange", renderRoute);
  document.querySelectorAll("[data-route-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      if (link.getAttribute("aria-disabled") === "true") {
        event.preventDefault();
        showMessage("connect-message", "Connect a lab before opening this workspace.", "error");
      }
    });
  });
  renderRoute();
}

function setRuntimeStatus(status) {
  const normalized = String(status || "stopped").toLowerCase();
  const badge = document.getElementById("status-badge");
  badge.className = `status-badge ${normalized}`;
  text("status-text", normalized);
  text(
    "steer-runtime-state",
    normalized === "running"
      ? "agent is running"
      : normalized === "paused"
        ? "paused snapshot"
        : "queued locally",
  );
}

function setContractState(contract, phase = "result") {
  document.querySelectorAll("[data-contract]").forEach((item) => {
    const key = item.dataset.contract;
    const state = item.querySelector(".check-state");
    item.classList.remove("checking", "passed");
    if (phase === "checking") {
      item.classList.add("checking");
      state.textContent = "checking";
    } else if (contract?.[key]) {
      item.classList.add("passed");
      state.textContent = "passed";
    } else {
      state.textContent = "waiting";
    }
  });
}

function renderSteering(records) {
  const steering = Array.isArray(records) ? records : [];
  text("steering-count", `${steering.length} ${steering.length === 1 ? "record" : "records"}`);
  const element = document.getElementById("steering-history");
  if (!steering.length) {
    element.innerHTML = '<div class="empty-state">No directions</div>';
    return;
  }
  element.innerHTML = steering.map((record) => {
    const mode = String(record.mode || "auto").replace(/_/g, " ");
    const label = record.action ? String(record.action) : mode;
    const who = record.by ? ` · ${esc(record.by)}` : "";
    const ack = record.acknowledged === false ? " · queued" : "";
    return `<article class="steering-record">` +
      `<div class="steering-record-meta">` +
        `<time>${esc(formatTimestamp(record.timestamp, true))} UTC</time>` +
        `<span class="steering-mode">${esc(label)}${who}${ack}</span>` +
      `</div>` +
      `<p>${esc(record.message || "")}</p>` +
    `</article>`;
  }).join("");
}

function renderControl(info) {
  if (info.csrf_token) csrfToken = info.csrf_token;
  controlState = { ...controlState, ...info };
  const connected = Boolean(info.connected);
  const pausedDemo = Boolean(info.paused_demo);
  controlState.connected = connected;
  controlState.hydrated = true;

  const connectionBar = document.getElementById("connection-bar");
  connectionBar.hidden = !connected;
  renderBudget();

  if (!connected) {
    setRuntimeStatus("disconnected");
    if (!isConnecting) setContractState(info.contract);
    renderSteering([]);
    renderRoute();
    return;
  }

  text("observe-lab-title", info.lab_id || "unnamed-lab");
  text("observe-lab-meta", `${info.domain || "unclassified"} / ${info.status || "stopped"}`);
  text("connection-source", info.remote
    ? `runs on ${info.source || "the owner's machine"} · steer it there`
    : (info.source || info.submission_dir || "local submission"));
  setRuntimeStatus(info.status);
  setContractState(info.contract);
  renderSteering(info.steering);

  const keyState = document.getElementById("api-key-state");
  keyState.textContent = pausedDemo
    ? "Paused demo · no model calls"
    : info.has_api_key ? "API key ready" : "API key missing";
  keyState.classList.toggle("ready", Boolean(info.has_api_key) && !pausedDemo);
  document.getElementById("activity-state").innerHTML = pausedDemo
    ? '<span aria-hidden="true"></span> history'
    : '<span aria-hidden="true"></span> live';
  const live = info.status === "running" || info.status === "paused";
  const ownerPaused = Boolean(info.owner_paused);
  const mine = (controlState.mode !== "cluster" || Boolean(info.mine)) && !info.remote;
  document.getElementById("start-lab").hidden = pausedDemo || live || !mine;
  document.getElementById("stop-lab").hidden = pausedDemo || !live || !mine;
  document.getElementById("pause-lab").hidden = pausedDemo || !live || ownerPaused || !mine;
  document.getElementById("resume-lab").hidden = pausedDemo || !ownerPaused || !mine;
  document.getElementById("connect-submit").disabled = pausedDemo;
  const owner = document.getElementById("connection-owner");
  owner.hidden = !info.owner_name;
  owner.textContent = info.owner_name
    ? `${info.owner_name}${info.track ? ` · ${info.track}` : ""}`
    : "";
  const steerForm = document.getElementById("steer-form");
  steerForm.hidden = !mine;
  steerForm.querySelectorAll("textarea, select, button").forEach((control) => {
    control.disabled = pausedDemo;
  });
  const activityPanel = document.querySelector(".activity-panel");
  if (pausedDemo && !activityPanel.dataset.pausedDefault) {
    activityPanel.dataset.pausedDefault = "collapsed";
    activityPanel.classList.add("collapsed");
    const activityToggle = activityPanel.querySelector("[data-panel-toggle]");
    activityToggle.setAttribute("aria-expanded", "false");
    activityToggle.textContent = "Show";
  }
  renderRoute();
}

function selectedPortfolioLab() {
  if (selectedLabId) {
    return portfolioState.labs.find((lab) => lab.lab_id === selectedLabId) || null;
  }
  return portfolioState.labs.find((lab) => lab.selected) || null;
}

function markSelected() {
  const chosen = selectedPortfolioLab();
  portfolioState.labs.forEach((lab) => {
    lab.selected = Boolean(chosen) && lab.lab_id === chosen.lab_id;
  });
}

function renderLabTabs() {
  const strip = document.getElementById("lab-tabs");
  const route = currentRoute();
  const known = new Map(portfolioState.labs.map((lab) => [lab.lab_id, lab]));
  openTabs = openTabs.filter((labId) => known.has(labId));
  const selected = selectedPortfolioLab();
  if (selected && route === "observe" && !openTabs.includes(selected.lab_id)) {
    openTabs.push(selected.lab_id);
  }
  writeStored("efferents-open-labs", openTabs);
  strip.hidden = route === "connect" || portfolioState.labs.length === 0;
  const networkActive = route === "network";
  strip.innerHTML =
    `<button class="lab-tab home${networkActive ? " active" : ""}" type="button" ` +
    `data-tab-network aria-current="${networkActive ? "true" : "false"}">` +
    `<span class="tab-name">network</span></button>` +
    openTabs.map((labId) => {
      const lab = known.get(labId);
      const active = Boolean(lab.selected) && route === "observe";
      return `<button class="lab-tab${active ? " active" : ""}" type="button" ` +
        `data-tab="${esc(labId)}" aria-current="${active ? "true" : "false"}">` +
        `<i class="tab-led ${esc(lab.status || "stopped")}" aria-hidden="true"></i>` +
        `<span class="tab-name">${esc(labId)}</span>` +
        `<span class="tab-close" data-close="${esc(labId)}" title="Close tab">×</span></button>`;
    }).join("");
  strip.querySelector("[data-tab-network]").addEventListener("click", () => {
    window.location.hash = "network";
  });
  strip.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.addEventListener("click", async (event) => {
      const close = event.target.closest("[data-close]");
      if (close) {
        event.stopPropagation();
        await closeLabTab(close.dataset.close);
        return;
      }
      if (tab.dataset.tab === selectedPortfolioLab()?.lab_id) {
        window.location.hash = "observe";
      } else {
        await selectPortfolioLab(tab.dataset.tab, true);
      }
    });
  });
}

async function closeLabTab(labId) {
  const wasActive = selectedPortfolioLab()?.lab_id === labId;
  openTabs = openTabs.filter((openId) => openId !== labId);
  writeStored("efferents-open-labs", openTabs);
  if (wasActive && openTabs.length) {
    await selectPortfolioLab(openTabs[openTabs.length - 1], true);
    return;
  }
  if (wasActive) {
    window.location.hash = "network";
  }
  renderLabTabs();
}

async function openLabTab(labId) {
  if (!openTabs.includes(labId)) openTabs.push(labId);
  writeStored("efferents-open-labs", openTabs);
  await selectPortfolioLab(labId, true);
}

function renderLabRail() {
  const labs = Array.isArray(portfolioState.labs) ? portfolioState.labs : [];
  text("lab-portfolio-count", String(labs.length).padStart(2, "0"));
  const list = document.getElementById("lab-list");
  if (!labs.length) {
    list.innerHTML = '<div class="empty-state">No local labs</div>';
    renderRoute();
    return;
  }
  list.innerHTML = labs.map((lab, index) => {
    const headline = lab.headline || {};
    const metric = headline.best == null
      ? `${headline.observations || 0} observations`
      : `${esc(headline.column || "metric")} ${esc(formatMetric(headline.best))}`;
    const ownerLine = lab.owner_name ? ` · ${esc(lab.owner_name)}` : "";
    return `<button class="lab-list-item${lab.selected ? " selected" : ""}${lab.mine ? " mine" : ""}${lab.remote ? " remote" : ""}" ` +
      `type="button" data-lab-select="${esc(lab.lab_id)}" role="listitem" ` +
      `aria-current="${lab.selected ? "true" : "false"}">` +
      `<span class="lab-seq">${String(index + 1).padStart(2, "0")}</span>` +
      `<span class="lab-list-copy"><strong>${esc(lab.lab_id)}</strong>` +
      `<small>${esc(lab.domain || "unclassified")}${ownerLine}</small>` +
      `<span>${metric}</span>` +
      `<span class="lab-verdict${lab.verdict?.status === "falsified" ? " falsified" : ""}">` +
      `${esc(lab.verdict?.line || "verdict: undecided")}</span></span>` +
      `<span class="lab-list-state ${esc(lab.status || "stopped")}">` +
      `<i aria-hidden="true"></i>${esc(formatRelativeTime(lab.last_activity))}</span>` +
      `</button>`;
  }).join("");
  list.querySelectorAll("[data-lab-select]").forEach((button) => {
    button.addEventListener("click", async () => {
      await openLabTab(button.dataset.labSelect);
    });
  });
  renderRoute();
}

function portfolioNodePosition(index, count) {
  const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / Math.max(count, 1));
  return {
    x: 50 + Math.cos(angle) * (count < 3 ? 29 : 35),
    y: 50 + Math.sin(angle) * (count < 3 ? 27 : 34),
  };
}

function renderNetwork() {
  const labs = portfolioState.labs || [];
  const lines = document.getElementById("network-lines");
  const nodes = document.getElementById("network-nodes");
  const journalsLayer = document.getElementById("network-journals");
  const ideasLayer = document.getElementById("network-ideas");
  const empty = document.getElementById("network-empty");
  const hub = document.querySelector(".network-hub");
  const positions = new Map();
  lines.innerHTML = "";
  nodes.innerHTML = "";
  journalsLayer.innerHTML = "";
  ideasLayer.innerHTML = "";
  const packet = (a, b, cls = "") => {
    const motion = svgElement("animateMotion", {
      dur: `${2.4 + (Math.abs(a.x - b.x) % 8) / 10}s`,
      begin: `-${(Math.abs(a.x + b.y) % 20) / 10}s`,
      repeatCount: "indefinite",
      path: `M${a.x * 10},${a.y * 5.6} L${b.x * 10},${b.y * 5.6}`,
    });
    const dot = svgElement("circle", { r: 3, class: `network-packet ${cls}` });
    dot.appendChild(motion);
    lines.appendChild(dot);
  };
  const people = isCluster() && controlState.session && controlState.session.people != null
    ? ` · ${controlState.session.people} ${controlState.session.people === 1 ? "person" : "people"}`
    : "";
  text("network-node-count", `${labs.length} ${labs.length === 1 ? "lab" : "labs"}${people}`);

  if (!labs.length) {
    empty.hidden = false;
    empty.textContent = isCluster() ? "No labs yet · start one under New lab" : "Connect a lab";
    hub.hidden = true;
    return;
  }
  empty.hidden = true;
  hub.hidden = false;

  labs.forEach((lab, index) => {
    const position = portfolioNodePosition(index, labs.length);
    positions.set(lab.lab_id, position);
    lines.appendChild(svgElement("line", {
      x1: 500,
      y1: 280,
      x2: position.x * 10,
      y2: position.y * 5.6,
      class: "hub-edge",
    }));
    const button = document.createElement("button");
    button.type = "button";
    button.className = `map-node ${lab.status || "stopped"}${lab.selected ? " selected" : ""}${lab.mine ? " mine" : ""}${lab.remote ? " remote" : ""}`;
    button.dataset.mapLab = lab.lab_id;
    button.style.left = `${position.x}%`;
    button.style.top = `${position.y}%`;
    const owner = lab.owner_name ? `<small class="map-node-owner">${esc(lab.owner_name)}${lab.remote ? " · laptop" : ""}</small>` : "";
    button.innerHTML = `<span class="map-node-state"><i aria-hidden="true"></i>${esc(lab.status || "stopped")}</span>` +
      `<strong>${esc(lab.lab_id)}</strong><small>${esc(lab.domain || "unclassified")}</small>${owner}`;
    button.addEventListener("click", async () => {
      await openLabTab(lab.lab_id);
    });
    nodes.appendChild(button);
  });

  const journals = new Map();
  labs.forEach((lab) => {
    const key = lab.domain || "unclassified";
    const group = journals.get(key) || [];
    group.push(lab);
    journals.set(key, group);
  });
  journals.forEach((members, domain) => {
    const points = members.map((lab) => positions.get(lab.lab_id));
    const center = points.reduce((sum, point) => ({ x: sum.x + point.x, y: sum.y + point.y }), { x: 0, y: 0 });
    center.x /= points.length;
    center.y /= points.length;
    const label = document.createElement("div");
    label.className = "network-journal";
    label.style.left = `${center.x}%`;
    label.style.top = `${Math.max(7, center.y - 22)}%`;
    label.innerHTML = `<small>JOURNAL · DOMAIN INBOX</small><b>${esc(domain)}</b><small>${members.length} labs</small>`;
    const labGrid = document.createElement("div");
    labGrid.className = "journal-labs";
    label.appendChild(labGrid);
    journalsLayer.appendChild(label);
    members.forEach((lab) => {
      const position = positions.get(lab.lab_id);
      const hub = { x: center.x * 10, y: center.y * 5.6 };
      const nucleus = { x: position.x * 10, y: position.y * 5.6 };
      for (let fiber = -2; fiber <= 2; fiber += 1) {
        const bend = (hub.y + nucleus.y) / 2;
        lines.appendChild(svgElement("path", {
          d: `M${hub.x},${hub.y} C${hub.x + fiber * 16},${bend} ${nucleus.x + fiber * 16},${bend} ${nucleus.x},${nucleus.y}`,
          class: "journal-fiber",
          fill: "none",
        }));
      }
      for (let fiber = 0; fiber < 14; fiber += 1) {
        const angle = fiber * Math.PI / 7;
        const tip = { x: nucleus.x + Math.cos(angle) * 28, y: nucleus.y + Math.sin(angle) * 24 };
        lines.appendChild(svgElement("path", {
          d: `M${nucleus.x},${nucleus.y} C${nucleus.x + Math.cos(angle) * 10},${nucleus.y + Math.sin(angle) * 8} ${tip.x - Math.cos(angle) * 8},${tip.y - Math.sin(angle) * 8} ${tip.x},${tip.y}`,
          class: "lab-fiber",
          fill: "none",
        }));
      }
      lines.appendChild(svgElement("circle", { cx: nucleus.x, cy: nucleus.y, r: 5, class: "lab-nucleus" }));
      const question = lab.hypothesis?.question || lab.hypothesis?.claim || "Awaiting first hypothesis";
      const card = document.createElement("article");
      card.className = `lab-structure ${lab.status || "stopped"}${lab.selected ? " selected" : ""}`;
      const owner = lab.owner_name ? `<small class="map-node-owner">${esc(lab.owner_name)}${lab.remote ? " · laptop" : ""}</small>` : "";
      card.innerHTML = `<button type="button" class="lab-identity"><strong>${esc(lab.lab_id)}</strong><small>${esc(lab.status || "stopped")}${lab.remote ? " · read only" : ""}</small>${owner}</button>` +
        `<div class="lab-loop" aria-label="Autoresearch loop"><span>owner steering</span><i>→</i><span>supervisor + agents</span><i>→</i><span class="gate">hypothesis</span><i>→</i><span class="gate">bounded run</span><i>→</i><span>evidence + paper</span><b class="lab-flow-packet" aria-hidden="true">◆</b></div>` +
        `<div class="lab-ideas"><small>GROUP OF IDEAS</small><p>${esc(question.length > 78 ? `${question.slice(0, 75)}…` : question)}</p></div>`;
      card.querySelector(".lab-identity").addEventListener("click", async () => { await openLabTab(lab.lab_id); });
      labGrid.appendChild(card);
    });
  });

  (portfolioState.edges || []).forEach((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return;
    lines.appendChild(svgElement("line", {
      x1: source.x * 10,
      y1: source.y * 5.6,
      x2: target.x * 10,
      y2: target.y * 5.6,
      class: `domain-edge edge-${String(edge.kind || "shared-domain")}`,
    }));
    packet(source, target, "domain");
  });

}

function renderPortfolio(payload) {
  portfolioState = {
    labs: Array.isArray(payload?.labs) ? payload.labs : [],
    edges: Array.isArray(payload?.edges) ? payload.edges : [],
  };
  if (!selectedLabId) {
    // First load in a single-lab workspace: follow the server's default lab.
    const serverDefault = portfolioState.labs.find((lab) => lab.selected);
    if (serverDefault) selectedLabId = serverDefault.lab_id;
  }
  markSelected();
  markMine();
  portfolioBudget = portfolioState.labs.reduce(
    (sum, lab) => ({
      spent: sum.spent + Number(lab.budget?.spent || 0),
      cap: sum.cap + Number(lab.budget?.cap || 0),
    }),
    { spent: 0, cap: 0 },
  );
  renderLabRail();
  renderLabTabs();
  renderBudget();
  renderNetwork();
}

async function refreshPortfolio() {
  renderPortfolio(await getJSON("/api/labs"));
}

async function selectPortfolioLab(labId, openObserver) {
  selectedLabId = labId;
  writeStored("efferents-selected-lab", labId);
  markSelected();
  if (openObserver) window.location.hash = "observe";
  const info = await getJSON(labPath("control"));
  renderControl(info);
  renderLabRail();
  renderLabTabs();
  renderNetwork();
  await refreshObserver();
}

const CLAMP_THRESHOLD = 260;

function applyThesisClamp(id) {
  const copy = document.getElementById(id);
  const block = copy.closest(".thesis-block");
  const long = (copy.textContent || "").length > CLAMP_THRESHOLD;
  let button = block.querySelector(".clamp-toggle");
  if (!button) {
    button = document.createElement("button");
    button.type = "button";
    button.className = "clamp-toggle";
    button.addEventListener("click", () => {
      const expanded = block.dataset.expanded !== "true";
      block.dataset.expanded = String(expanded);
      copy.classList.toggle("clamped", !expanded);
      button.textContent = expanded ? "Collapse" : "Read in full";
    });
    block.appendChild(button);
  }
  const expanded = block.dataset.expanded === "true";
  copy.classList.toggle("clamped", long && !expanded);
  button.hidden = !long;
  if (!expanded) button.textContent = "Read in full";
}

function renderState(state) {
  if (!controlState.connected) return;
  setRuntimeStatus(state.status || controlState.status);

  labBudget = {
    spent: Number(state.budget?.spent || 0),
    cap: Number(state.budget?.cap || 0),
  };
  renderBudget();

  const hypothesis = state.hypothesis || {};
  text("student", hypothesis.student ? `student / ${hypothesis.student}` : "student / —");
  const question = hypothesis.question || "No open campaign.";
  const claim = hypothesis.claim || "No claim.";
  text("question", question);
  text("claim", question.replace(/\s+/g, " ").trim() === claim.replace(/\s+/g, " ").trim()
    ? "Matches the active hypothesis above."
    : claim);
  text("falsifier", hypothesis.falsifier || "No falsifier.");
  applyThesisClamp("claim");
  applyThesisClamp("falsifier");
}

function renderRuns(data) {
  const headline = data.headline || { column: "metric", direction: "min" };
  const direction = headline.direction === "max" ? "max" : "min";
  const directionLabel = direction === "max" ? "higher is better" : "lower is better";
  const runs = Array.isArray(data.runs) ? data.runs : [];
  const history = data.history || {};
  const observedRuns = runs.filter((run) => Number.isFinite(Number(run.value)));
  const eligibleRuns = observedRuns.filter((run) => run.eligible !== false);
  const eligibleValues = eligibleRuns.map((run) => Number(run.value));
  const recentBest = eligibleValues.length
    ? (direction === "max" ? Math.max(...eligibleValues) : Math.min(...eligibleValues))
    : null;
  const best = Number.isFinite(Number(history.best)) ? Number(history.best) : recentBest;
  const latest = eligibleRuns.length ? Number(eligibleRuns[0].value) : null;
  const bestRunId = history.best_run_id ||
    eligibleRuns.find((run) => Number(run.value) === best)?.run_id || "";
  const median = quantile(eligibleValues, 0.5);
  const lowerQuartile = quantile(eligibleValues, 0.25);
  const upperQuartile = quantile(eligibleValues, 0.75);
  const iqr = lowerQuartile == null || upperQuartile == null
    ? null
    : upperQuartile - lowerQuartile;
  const excludedCount = runs.filter((run) => run.eligible === false).length;

  text("metric-label", headline.column || "Headline metric");
  text("metric-direction", directionLabel);
  text("run-metric-header", headline.column || "Result");
  text("run-count", `${runs.length} recent / ${Number(history.total || runs.length)} total`);
  text("metric-best", formatMetric(best));
  text("metric-latest", formatMetric(latest));
  text("metric-eligible", `${eligibleRuns.length} / ${runs.length}`);
  text("metric-median", formatMetric(median));
  text("metric-iqr", formatMetric(iqr));
  const bestRunElement = document.getElementById("metric-best-run");
  bestRunElement.textContent = compactRunId(bestRunId);
  bestRunElement.title = bestRunId;

  if (latest == null || best == null) {
    text("metric-delta", "—");
  } else {
    const gap = direction === "max" ? best - latest : latest - best;
    text("metric-delta", Math.abs(gap) < Number.EPSILON ? "at best" : formatMetric(gap));
  }

  const tbody = document.querySelector("#runs tbody");
  tbody.innerHTML = "";
  const firstBestIndex = runs.findIndex((run) =>
    run.eligible !== false && Number.isFinite(Number(run.value)) && Number(run.value) === best
  );
  runs.forEach((run, index) => {
    const numericValue = Number(run.value);
    const hasValue = Number.isFinite(numericValue);
    const eligible = hasValue && run.eligible !== false;
    const excluded = run.eligible === false;
    const tiesBest = eligible && best != null && numericValue === best;
    const isBest = tiesBest && index === firstBestIndex;
    const row = document.createElement("tr");
    row.className = isBest ? "is-best" : excluded ? "is-excluded" : "";
    const failures = Array.isArray(run.constraint_failures)
      ? run.constraint_failures.join("; ")
      : "";
    if (failures) row.title = failures;
    const validity = isBest
      ? "best"
      : tiesBest
        ? "ties best"
        : excluded
          ? "excluded"
          : hasValue
            ? "eligible"
            : "missing";
    row.innerHTML =
      `<td>${String(runs.length - index).padStart(2, "0")}</td>` +
      `<td class="run-id" title="${esc(run.run_id || "")}">${esc(run.run_id || "—")}</td>` +
      `<td title="${esc(run.started_at || "")}">${esc(formatTimestamp(run.started_at))}</td>` +
      `<td class="metric-cell">${esc(formatMetric(run.value))}</td>` +
      `<td><span class="signal-tag${isBest ? " best" : excluded ? " excluded" : ""}">` +
      `${validity}</span></td>`;
    tbody.appendChild(row);
  });

  if (!runs.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="5"><div class="empty-state">No runs</div></td>';
    tbody.appendChild(row);
  }

  renderTrend(Array.isArray(data.series) ? data.series : [], direction, {
    metric: headline.column || "metric",
    eligible: eligibleRuns.length,
    excluded: excludedCount,
    median,
  });
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

function renderTrend(series, direction, summary = {}) {
  const svg = document.getElementById("trend");
  svg.innerHTML = "";
  const finiteSeries = series.filter((point) => Number.isFinite(Number(point.value)));
  svg.setAttribute(
    "aria-label",
    `${summary.metric || "metric"} across ${finiteSeries.length} eligible observations`,
  );

  if (!finiteSeries.length) {
    text("trend-caption", "No eligible metric observations");
    text("metric-range", "—");
    return;
  }

  const width = 600;
  const height = 180;
  const padding = { top: 14, right: 18, bottom: 24, left: 62 };
  const values = finiteSeries.map((point) => Number(point.value));
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const rawSpan = rawMax - rawMin;
  const span = rawSpan || Math.max(Math.abs(rawMax) * 0.1, 1);
  const min = rawMin - span * 0.08;
  const max = rawMax + span * 0.08;
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  for (let index = 0; index <= 4; index += 1) {
    const y = padding.top + (chartHeight / 4) * index;
    svg.appendChild(svgElement("line", {
      x1: padding.left,
      x2: width - padding.right,
      y1: y,
      y2: y,
      class: "grid-line",
    }));
    const tick = svgElement("text", {
      x: padding.left - 7,
      y: y + 3,
      "text-anchor": "end",
    });
    tick.textContent = formatMetric(max - ((max - min) / 4) * index);
    svg.appendChild(tick);
  }

  const coordinates = finiteSeries.map((point, index) => {
    const x = finiteSeries.length === 1
      ? padding.left + chartWidth / 2
      : padding.left + (index / (finiteSeries.length - 1)) * chartWidth;
    const y = padding.top + (1 - ((Number(point.value) - min) / (max - min))) * chartHeight;
    return { x, y, value: Number(point.value) };
  });

  if (coordinates.length > 1) {
    const linePoints = coordinates.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
    const areaPoints = `${padding.left},${height - padding.bottom} ${linePoints} ` +
      `${width - padding.right},${height - padding.bottom}`;
    svg.appendChild(svgElement("polygon", { points: areaPoints, class: "area" }));
    svg.appendChild(svgElement("polyline", { points: linePoints, class: "trend-line" }));
  }

  const best = direction === "max" ? rawMax : rawMin;
  coordinates.forEach((point) => {
    const isBest = point.value === best;
    svg.appendChild(svgElement("circle", {
      cx: point.x,
      cy: point.y,
      r: isBest ? 3.7 : 2.5,
      class: `point${isBest ? " best" : ""}`,
    }));
  });

  if (summary.median != null) {
    const medianY = padding.top +
      (1 - ((Number(summary.median) - min) / (max - min))) * chartHeight;
    svg.appendChild(svgElement("line", {
      x1: padding.left,
      x2: width - padding.right,
      y1: medianY,
      y2: medianY,
      class: "reference-line",
    }));
    const medianLabel = svgElement("text", {
      x: width - padding.right,
      y: medianY - 4,
      "text-anchor": "end",
      class: "reference-label",
    });
    medianLabel.textContent = `median ${formatMetric(summary.median)}`;
    svg.appendChild(medianLabel);
  }

  const startLabel = svgElement("text", {
    x: padding.left,
    y: height - 6,
    "text-anchor": "start",
  });
  startLabel.textContent = formatTimestamp(finiteSeries[0].started_at, true);
  svg.appendChild(startLabel);
  const endLabel = svgElement("text", {
    x: width - padding.right,
    y: height - 6,
    "text-anchor": "end",
  });
  endLabel.textContent = formatTimestamp(finiteSeries[finiteSeries.length - 1].started_at, true);
  svg.appendChild(endLabel);

  text(
    "trend-caption",
    `${finiteSeries.length} eligible / chronological` +
      (summary.excluded ? ` · ${summary.excluded} excluded` : ""),
  );
  text("metric-range", `range ${formatMetric(rawMin)} — ${formatMetric(rawMax)}`);
}

function evidenceComparisonKey(record, axis) {
  const shared = Object.entries(record.dimensions || {})
    .filter(([key]) => key !== axis)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify([record.started_at || "", shared]);
}

function groupEvidenceRecords(records, comparison) {
  const axis = comparison?.axis;
  if (!axis) return records.map((record) => ({ kind: "single", records: [record] }));

  const candidates = new Map();
  records.forEach((record) => {
    const value = record.dimensions?.[axis];
    if (value == null) return;
    const key = evidenceComparisonKey(record, axis);
    if (!candidates.has(key)) candidates.set(key, []);
    candidates.get(key).push(record);
  });

  const pairedKeys = new Set(
    [...candidates.entries()]
      .filter(([, group]) => new Set(group.map((record) => record.dimensions[axis])).size > 1)
      .map(([key]) => key),
  );
  const emitted = new Set();
  const groups = [];
  records.forEach((record) => {
    const value = record.dimensions?.[axis];
    const key = value == null ? null : evidenceComparisonKey(record, axis);
    if (key && pairedKeys.has(key)) {
      if (!emitted.has(key)) {
        groups.push({ kind: "comparison", records: candidates.get(key) });
        emitted.add(key);
      }
      return;
    }
    groups.push({ kind: "single", records: [record] });
  });
  return groups;
}

function evidenceVariantLabel(value, comparison) {
  return comparison?.labels?.[value] || String(value).replace(/[_-]+/g, " ");
}

function renderEvidenceRecord(record, metricPanels, hiddenDimensions = new Set()) {
  const dimensions = Object.entries(record.dimensions || {})
    .filter(([key]) => !hiddenDimensions.has(key));
  const failures = Array.isArray(record.constraint_failures)
    ? record.constraint_failures
    : [];
  const artifact = (record.artifacts || [])[0];
  const metricRows = metricPanels
    .filter((metric) => record.metrics?.[metric.column] != null)
    .map((metric) =>
      `<div><dt title="${esc(metric.label)}">${esc(metric.label)}</dt>` +
      `<dd>${esc(formatMetric(record.metrics[metric.column]))}</dd></div>`
    ).join("");
  return `<article class="evidence-record ${record.eligible ? "is-eligible" : "is-excluded"}">` +
    (artifact
      ? `<a class="evidence-artifact" href="${esc(artifact.url)}" target="_blank" rel="noopener" ` +
        `aria-label="Open ${esc(record.name)} image at full resolution">` +
        `<img src="${esc(artifact.url)}" loading="lazy" alt="${esc(record.name)} visual result"></a>`
      : "") +
    `<div class="evidence-record-body"><div class="evidence-record-head">` +
    `<strong title="${esc(record.run_id)}">${esc(record.name || compactRunId(record.run_id))}</strong>` +
    `<span class="evidence-validity">${record.eligible ? "eligible" : "excluded"}</span></div>` +
    (dimensions.length
      ? `<div class="evidence-dimensions">` + dimensions.map(([key, value]) =>
        `<span>${esc(key)}=<strong>${esc(value)}</strong></span>`).join("") + `</div>`
      : "") +
    `<dl class="evidence-metrics">${metricRows}</dl>` +
    (failures.length
      ? `<p class="evidence-failure">${failures.map(esc).join(" · ")}</p>`
      : "") +
    `</div></article>`;
}

function renderEvidenceComparison(group, metricPanels, comparison) {
  const axis = comparison.axis;
  const order = Array.isArray(comparison.order) ? comparison.order : [];
  const records = [...group.records].sort((left, right) => {
    const leftIndex = order.indexOf(String(left.dimensions?.[axis]));
    const rightIndex = order.indexOf(String(right.dimensions?.[axis]));
    if (leftIndex < 0 && rightIndex < 0) return 0;
    if (leftIndex < 0) return 1;
    if (rightIndex < 0) return -1;
    return leftIndex - rightIndex;
  });
  const shared = Object.entries(records[0].dimensions || {})
    .filter(([key]) => key !== axis);
  const hidden = new Set([axis, ...shared.map(([key]) => key)]);
  const labels = records.map((record) =>
    evidenceVariantLabel(record.dimensions?.[axis], comparison));
  const sharedLabel = shared.map(([key, value]) =>
    `${key}=${value}`).join(" · ");
  return `<section class="evidence-comparison" aria-label="Matched comparison: ${esc(labels.join(" versus "))}">` +
    `<header class="evidence-comparison-head"><div>` +
    `<span>Matched comparison</span><strong>${esc(sharedLabel || "shared run context")}</strong></div>` +
    `<small>same ${esc(shared.map(([key]) => key).join(" / ") || "context")} · only ${esc(axis)} changes</small>` +
    `</header><div class="evidence-comparison-grid">` +
    records.map((record, index) => {
      const value = record.dimensions?.[axis];
      const label = evidenceVariantLabel(value, comparison);
      return `<div class="evidence-variant"><header class="evidence-variant-head">` +
        `<span>${String(index + 1).padStart(2, "0")}</span><strong>${esc(label)}</strong>` +
        `<small>${esc(axis)}=${esc(value)}</small></header>` +
        renderEvidenceRecord(record, metricPanels, hidden) + `</div>`;
    }).join("") + `</div></section>`;
}

function renderEvidence(data) {
  const panel = document.getElementById("evidence-panel");
  const records = Array.isArray(data?.records) ? data.records : [];
  const metricPanels = Array.isArray(data?.panels) ? data.panels : [];
  const constraints = Array.isArray(data?.constraints) ? data.constraints : [];
  const comparison = data?.comparison || {};
  const groups = groupEvidenceRecords(records, comparison);
  const matched = groups.filter((group) => group.kind === "comparison").length;
  const standalone = groups.length - matched;
  panel.hidden = records.length === 0;
  text(
    "evidence-count",
    `${matched} matched / ${standalone} standalone / ${Number(data?.artifact_count || 0)} images`,
  );
  if (!records.length) return;

  const gates = document.getElementById("evidence-gates");
  gates.innerHTML = constraints.length
    ? constraints.map((constraint) =>
      `<span class="evidence-gate"><strong>${esc(constraint.label || constraint.column)}</strong> ` +
      `${esc(constraint.column)} ${esc(constraint.op)} ${esc(formatMetric(constraint.value))}</span>`
    ).join("")
    : '<span class="evidence-axis"><strong>No eligibility gates</strong></span>';
  gates.insertAdjacentHTML(
    "beforeend",
    `<span class="evidence-axis"><strong>${metricPanels.length}</strong> configured metrics</span>`,
  );

  const gallery = document.getElementById("evidence-gallery");
  gallery.innerHTML = groups.map((group) => group.kind === "comparison"
    ? renderEvidenceComparison(group, metricPanels, comparison)
    : renderEvidenceRecord(group.records[0], metricPanels)
  ).join("");
}

function formatCI(ci) {
  return Array.isArray(ci) && ci.length === 2
    ? `[${formatMetric(ci[0])}, ${formatMetric(ci[1])}]`
    : "—";
}

function renderVerdict(data) {
  const falsifiers = Array.isArray(data?.falsifiers) ? data.falsifiers : [];
  const buckets = Array.isArray(data?.buckets) ? data.buckets : [];
  const columns = Array.isArray(data?.columns) ? data.columns : [];
  const axes = Array.isArray(data?.axes) ? data.axes : [];
  const comparison = data?.comparison || {};
  const runs = Number(data?.n_runs || 0);
  text("verdict-count", `${runs} succeeded ${runs === 1 ? "run" : "runs"}`);

  const line = document.getElementById("verdict-line");
  line.textContent = data?.line || "verdict: undecided";
  line.classList.toggle("falsified", data?.verdict === "falsified");

  const falsifierBody = document.querySelector("#falsifiers tbody");
  falsifierBody.innerHTML = falsifiers.length
    ? falsifiers.map((f) =>
      `<tr><td>${esc(f.id)}</td><td>${esc(f.bucket)}</td>` +
      `<td class="status-${esc(f.status)}">${esc(f.status === "insufficient_data" ? "insufficient" : f.status)}</td>` +
      `<td class="rule-cell">${esc(f.rule)} — ${esc(f.detail)}</td></tr>`
    ).join("")
    : '<tr><td colspan="4" class="empty-state">No falsifiers declared in lab.yaml</td></tr>';

  const armLabel = (arm) => comparison.labels?.[arm] || arm;
  const arms = [];
  buckets.forEach((bucket) => Object.keys(bucket.arms || {}).forEach((arm) => {
    if (!arms.includes(arm)) arms.push(arm);
  }));
  const pairedMetrics = [];
  buckets.forEach((bucket) => Object.keys(bucket.paired || {}).forEach((metric) => {
    if (!pairedMetrics.includes(metric)) pairedMetrics.push(metric);
  }));
  const axisLabel = axes.length ? axes.join(" × ") : "all runs";
  text(
    "buckets-meta",
    `${buckets.length} ${buckets.length === 1 ? "bucket" : "buckets"} by ${axisLabel}` +
      (comparison.axis && arms.length ? ` · ${arms.map(armLabel).join(" vs ")}` : ""),
  );

  const head = [`<th scope="col">Bucket</th>`, `<th scope="col">n</th>`];
  columns.forEach((c) => head.push(`<th scope="col" class="metric-head">median ${esc(c.label || c.column)}</th>`));
  // Only metrics some arm actually reports; the flat panel medians cover the rest.
  const armColumns = columns.filter((c) =>
    buckets.some((bucket) => arms.some((arm) => bucket.arms?.[arm]?.[c.column]))
  );
  arms.forEach((arm) => armColumns.forEach((c) =>
    head.push(`<th scope="col" class="metric-head">${esc(armLabel(arm))} ${esc(c.column)}</th>`)
  ));
  pairedMetrics.forEach((metric) =>
    head.push(`<th scope="col" class="metric-head">Δ${esc(metric)} · 95% CI</th>`)
  );
  document.querySelector("#buckets thead tr").innerHTML = head.join("");

  const bucketBody = document.querySelector("#buckets tbody");
  bucketBody.innerHTML = buckets.length
    ? buckets.map((bucket) => {
      const cells = [`<td>${esc(bucket.label)}</td>`, `<td>${esc(bucket.n)}</td>`];
      columns.forEach((c) => cells.push(
        `<td class="metric-cell">${esc(formatMetric(bucket.columns?.[c.column]?.median))}</td>`
      ));
      arms.forEach((arm) => armColumns.forEach((c) => cells.push(
        `<td class="metric-cell">${esc(formatMetric(bucket.arms?.[arm]?.[c.column]?.median))}</td>`
      )));
      pairedMetrics.forEach((metric) => {
        const p = bucket.paired?.[metric];
        cells.push(`<td class="metric-cell">${p
          ? `${esc(formatMetric(p.median))} <span class="ci">${esc(formatCI(p.ci95))} n=${esc(p.n)}</span>`
          : "—"}</td>`);
      });
      return `<tr>${cells.join("")}</tr>`;
    }).join("")
    : `<tr><td colspan="${head.length}" class="empty-state">No succeeded runs</td></tr>`;
}

function renderPapers(papers) {
  const records = Array.isArray(papers) ? papers : [];
  const element = document.getElementById("papers");
  text("paper-count", `${records.length} ${records.length === 1 ? "record" : "records"}`);

  if (!records.length) {
    element.innerHTML = '<div class="empty-state">No cleared papers</div>';
    return;
  }

  element.innerHTML = records.map((paper) =>
    `<article class="paper-record">` +
      `<div class="record-glyph" aria-hidden="true">↗</div>` +
      `<div><div class="paper-title">${esc(paper.title || "Untitled artifact")}</div>` +
      `<div class="paper-meta">${esc(paper.campaign_id || "no campaign")} · ${esc(paper.published_at || "undated")}</div></div>` +
      `<div class="paper-status">${esc(paper.status || "draft")}</div>` +
    `</article>`
  ).join("");
}

function renderActivity(activities) {
  const records = Array.isArray(activities) ? activities : [];
  const element = document.getElementById("activity");

  if (!records.length) {
    element.innerHTML = '<div class="empty-state">No agent events</div>';
    return;
  }

  element.innerHTML = records.map((activity) => {
    const body = String(activity.body || "").replace(/\s+/g, " ").trim();
    return `<article class="activity-item">` +
      `<time class="activity-when">${esc(formatTimestamp(activity.timestamp, true))} UTC</time>` +
      `<div class="activity-content"><div class="activity-title" title="${esc(activity.title)}">${esc(activity.title)}</div>` +
      (body ? `<div class="activity-body">${esc(body)}</div>` : "") +
      `</div></article>`;
  }).join("");
}

async function refreshObserver() {
  if (!controlState.connected) return;
  if (document.hidden || currentRoute() !== "observe") return;
  const scoped = Boolean(selectedLabId);
  const requests = [
    ["/api/state", renderState],
    ["/api/runs", renderRuns],
    ["/api/evidence", renderEvidence],
    ["/api/verdict", renderVerdict],
    ["/api/papers", renderPapers],
    ["/api/activity", renderActivity],
  ];
  const results = await Promise.allSettled(
    requests.map(async ([path, renderer]) => {
      const url = scoped ? labPath(path.replace("/api/", "")) : path;
      return renderer(await getJSON(url));
    })
  );
  results
    .filter((result) => result.status === "rejected")
    .forEach((result) => console.error(result.reason));
}

async function refresh() {
  try {
    const session = await getJSON("/api/control");
    if (session.csrf_token) csrfToken = session.csrf_token;
    controlState.mode = session.mode || "local";
    renderSession(session);
    if (isCluster() && !isJoined()) {
      // Reads are gated on the join code; show the join view and stop here.
      portfolioState = { labs: [], edges: [] };
      renderControl(session);
      return;
    }
    await refreshPortfolio();
    if (selectedLabId && portfolioState.labs.some((lab) => lab.lab_id === selectedLabId)) {
      const info = await getJSON(labPath("control"));
      info.mine = Boolean(portfolioState.labs.find((lab) => lab.lab_id === selectedLabId)?.mine);
      renderControl(info);
    } else {
      selectedLabId = null;
      renderControl(session);
    }
    await refreshObserver();
  } catch (error) {
    console.error(error);
  }
}

// Hosted (cluster) mode: identity, nav visibility, owner marks.
function renderSession(session) {
  controlState.session = session.cluster || null;
  const cluster = isCluster();
  const joined = cluster && isJoined();
  document.querySelectorAll("[data-cluster-only]").forEach((el) => { el.hidden = !joined; });
  document.querySelectorAll("[data-local-only]").forEach((el) => { el.hidden = cluster; });
  if (cluster) {
    const info = controlState.session || {};
    text("network-hub-label", info.name || "lab network");
    if (info.joined && info.owner) {
      text("status-text", info.owner.name);
    }
  }
}

function markMine() {
  const mine = new Set((controlState.session && controlState.session.my_labs) || []);
  portfolioState.labs.forEach((lab) => { lab.mine = mine.has(lab.lab_id); });
}

function initIntakeTabs() {
  const tabs = document.querySelectorAll("[data-intake-tab]");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((other) => {
        const active = other === tab;
        other.setAttribute("aria-selected", String(active));
      });
      document.querySelectorAll("[data-intake-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.intakePanel !== tab.dataset.intakeTab;
      });
    });
  });

  const copy = document.getElementById("copy-command");
  copy.addEventListener("click", async () => {
    const command = document.getElementById("agent-command").textContent;
    try {
      await navigator.clipboard.writeText(command);
      copy.textContent = "Copied";
    } catch (error) {
      copy.textContent = "Select + copy";
    }
    setTimeout(() => { copy.textContent = "Copy"; }, 1600);
  });
}

function initConnectForm() {
  const form = document.getElementById("connect-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const source = document.getElementById("github-source").value.trim();
    const button = document.getElementById("connect-submit");
    isConnecting = true;
    button.disabled = true;
    button.textContent = "Connecting…";
    setContractState({}, "checking");
    showMessage("connect-message", "Checking out and validating the submission contract…");
    try {
      const info = await postJSON("/api/connect", { source });
      renderControl(info);
      showMessage(
        "connect-message",
        `${info.lab_id} connected · not executed`,
        "success",
      );
      window.location.hash = "observe";
      await Promise.all([refreshPortfolio(), refreshObserver()]);
    } catch (error) {
      setContractState({});
      showMessage("connect-message", error.message, "error");
    } finally {
      isConnecting = false;
      button.disabled = false;
      button.textContent = "Connect lab";
    }
  });
}

function initSteeringForm() {
  const form = document.getElementById("steer-form");
  const message = document.getElementById("steer-message");
  message.addEventListener("input", () => text("steer-count", message.value.length));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    showMessage("steer-message-state", "Recording direction in the steering ledger…");
    try {
      const result = await postJSON(selectedLabId ? labPath("steer") : "/api/steer", {
        message: message.value,
        mode: document.getElementById("steer-mode").value,
      });
      message.value = "";
      text("steer-count", "0");
      renderSteering(result.steering);
      showMessage(
        "steer-message-state",
        result.status === "running"
          ? "Direction recorded · next agent pass"
          : "Direction recorded · read on start",
        "success",
      );
    } catch (error) {
      showMessage("steer-message-state", error.message, "error");
    } finally {
      submit.disabled = false;
    }
  });
}

const RUNTIME_COPY = {
  start: {
    kicker: "Local execution", title: "Start lab?",
    copy: "Repository commands · local compute · configured LLM budget",
    label: "Authorize this local run.", button: "Confirm start",
    progress: "Starting the daemon…",
  },
  stop: {
    kicker: "Stop execution", title: "Stop lab?",
    copy: "Stop after current process · preserve written evidence",
    label: "Authorize this stop request.", button: "Confirm stop",
    progress: "Stopping the daemon…",
  },
  pause: {
    kicker: "Pause spending", title: "Pause lab?",
    copy: "Recorded as owner steering · takes effect at the next agent step · evidence preserved",
    label: "Authorize this pause.", button: "Confirm pause",
    progress: "Queuing the pause…",
  },
  resume: {
    kicker: "Resume spending", title: "Resume lab?",
    copy: "Lifts the owner pause · recorded as owner steering",
    label: "Authorize this resume.", button: "Confirm resume",
    progress: "Queuing the resume…",
  },
};

function openRuntimeDialog(action) {
  runtimeAction = action;
  const copy = RUNTIME_COPY[action] || RUNTIME_COPY.start;
  text("runtime-dialog-kicker", copy.kicker);
  text("runtime-dialog-title", copy.title);
  text("runtime-dialog-copy", copy.copy);
  text("runtime-confirm-label", copy.label);
  text("runtime-confirm-button", copy.button);
  const checkbox = document.getElementById("runtime-confirm-check");
  checkbox.checked = false;
  document.getElementById("runtime-confirm-button").disabled = true;
  showMessage("runtime-dialog-message");
  document.getElementById("runtime-dialog").showModal();
}

function initRuntimeControls() {
  const dialog = document.getElementById("runtime-dialog");
  const checkbox = document.getElementById("runtime-confirm-check");
  const confirm = document.getElementById("runtime-confirm-button");
  document.getElementById("start-lab").addEventListener("click", () => openRuntimeDialog("start"));
  document.getElementById("stop-lab").addEventListener("click", () => openRuntimeDialog("stop"));
  document.getElementById("pause-lab").addEventListener("click", () => openRuntimeDialog("pause"));
  document.getElementById("resume-lab").addEventListener("click", () => openRuntimeDialog("resume"));
  checkbox.addEventListener("change", () => {
    confirm.disabled = !checkbox.checked;
  });
  confirm.addEventListener("click", async () => {
    confirm.disabled = true;
    showMessage("runtime-dialog-message", (RUNTIME_COPY[runtimeAction] || {}).progress || "");
    try {
      const legacy = `/api/lab/${runtimeAction}`;
      const info = await postJSON(selectedLabId ? labPath(runtimeAction) : legacy, { confirmed: true });
      renderControl(info);
      dialog.close();
      await refreshObserver();
    } catch (error) {
      showMessage("runtime-dialog-message", error.message, "error");
      confirm.disabled = false;
    }
  });
}

function initPanelToggles() {
  document.querySelectorAll("[data-panel-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = button.closest(".panel");
      const collapsed = panel.classList.toggle("collapsed");
      button.setAttribute("aria-expanded", String(!collapsed));
      button.textContent = collapsed ? "Show" : "Hide";
    });
  });
}

// --- hosted cluster: join ------------------------------------------------------

function initJoinForm() {
  const form = document.getElementById("join-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = document.getElementById("join-submit");
    button.disabled = true;
    showMessage("join-message", "Joining…");
    try {
      const result = await postJSON("/api/join", {
        code: document.getElementById("join-code").value,
        name: document.getElementById("join-name").value,
      });
      if (result.csrf_token) csrfToken = result.csrf_token;
      controlState.session = result.cluster || { joined: true };
      const link = `${window.location.origin}${result.owner_link}`;
      text("owner-link", link);
      document.getElementById("join-result").hidden = false;
      showMessage("join-message", `Welcome, ${result.owner.name}.`, "success");
      renderTerminalPanel(result.cluster || {});
      controlState.session = result.cluster || { joined: true };
      controlState.mode = "cluster";
      controlState.hydrated = true;
      await refreshPortfolio().catch(() => {});
      // Stay on this page: the instruction and token are what they need next.
    } catch (error) {
      showMessage("join-message", error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
  const copyFrom = (sourceId, okMessage) => async () => {
    try {
      await navigator.clipboard.writeText(document.getElementById(sourceId).textContent);
      showMessage("join-message", okMessage, "success");
    } catch (error) {
      showMessage("join-message", "Copy failed; select the text and copy it by hand.", "error");
    }
  };
  document.getElementById("copy-terminal-instruction").addEventListener("click", copyFrom("terminal-instruction", "Instruction copied."));
  document.getElementById("copy-network-token").addEventListener("click", copyFrom("network-token", "Token copied."));
  document.getElementById("copy-owner-link").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(document.getElementById("owner-link").textContent);
      showMessage("join-message", "Owner link copied.", "success");
    } catch (error) {
      showMessage("join-message", "Copy failed; select the link and copy it by hand.", "error");
    }
  });
}

function renderTerminalPanel(session) {
  const panel = document.getElementById("terminal-panel");
  if (!session || !session.network_token) {
    panel.hidden = true;
    return;
  }
  text("terminal-instruction", `Read ${window.location.origin}/intake.md and follow it`);
  text("network-token", session.network_token);
  panel.hidden = false;
}

// --- hosted cluster: intake dialogue ------------------------------------------

let intakeState = { sessionId: null, payload: null, loaded: false, busy: false, trackId: null };

async function ensureIntakeLoaded() {
  if (!isCluster() || !isJoined() || intakeState.loaded || intakeState.busy) return;
  intakeState.loaded = true;
  try {
    const sessions = await getJSON("/api/intake/sessions");
    renderIntakeSessions(sessions);
    const open = sessions.filter((s) => !["created", "abandoned"].includes(s.state));
    if (open.length) await loadIntakeSession(open[open.length - 1].session_id);
    else renderIntake(null);
  } catch (error) {
    showMessage("intake-message", error.message, "error");
  }
}

function renderIntakeSessions(sessions) {
  const box = document.getElementById("intake-sessions");
  const list = Array.isArray(sessions) ? sessions : [];
  box.innerHTML = list.map((s) =>
    `<button type="button" class="compact-button${s.session_id === intakeState.sessionId ? " active" : ""}" ` +
    `data-intake-session="${esc(s.session_id)}">${esc(s.draft_slug || s.session_id)} · ${esc(s.state)}</button>`
  ).join("") +
  `<button type="button" class="compact-button" data-intake-new>+ new intake</button>`;
  box.querySelectorAll("[data-intake-session]").forEach((b) => {
    b.addEventListener("click", () => loadIntakeSession(b.dataset.intakeSession));
  });
  box.querySelector("[data-intake-new]").addEventListener("click", async () => {
    intakeState.sessionId = null;
    renderIntake(null);
  });
}

async function loadIntakeSession(sessionId) {
  intakeState.sessionId = sessionId;
  renderIntake(await getJSON(`/api/intake/sessions/${encodeURIComponent(sessionId)}`));
}

async function ensureIntakeSession() {
  if (intakeState.sessionId) return intakeState.sessionId;
  const payload = await postJSON("/api/intake/sessions", {});
  intakeState.sessionId = payload.session.session_id;
  renderIntake(payload);
  renderIntakeSessions(await getJSON("/api/intake/sessions"));
  return intakeState.sessionId;
}

function renderIntake(payload) {
  intakeState.payload = payload;
  const session = payload ? payload.session : null;
  const state = session ? session.state : "new";
  text("intake-session-state", session ? `${state} · ${session.user_turns} turns · $${Number(session.spend_usd || 0).toFixed(2)}` : "no session");
  const chat = document.getElementById("intake-chat");
  const turns = payload ? payload.transcript : [];
  chat.innerHTML = turns.length
    ? turns.map((t) => `<div class="chat-turn ${esc(t.role)}"><span class="chat-who">${esc(t.role === "assistant" ? "probe" : t.role === "user" ? "you" : "note")}</span>${esc(t.text)}</div>`).join("")
    : '<div class="empty-state">Describe the claim you want to test.</div>';
  chat.scrollTop = chat.scrollHeight;
  const closed = ["approved", "bound", "created", "abandoned"].includes(state);
  document.getElementById("intake-form").hidden = closed;

  const draft = payload ? payload.draft : null;
  const hasDraft = Boolean(draft && draft.valid);
  document.getElementById("intake-draft").textContent = hasDraft ? draft.text : (draft && draft.text ? draft.text : "");
  const errors = document.getElementById("intake-draft-errors");
  errors.hidden = !(draft && draft.errors);
  errors.textContent = draft && draft.errors ? draft.errors : "";
  text("intake-gate", hasDraft ? `gate ${draft.gate}` : (draft && draft.errors ? "draft has validator errors" : "no draft yet"));
  const approve = document.getElementById("intake-approve");
  approve.disabled = !(hasDraft && draft.gate === "passed" && state === "drafted");
  approve.textContent = ["approved", "bound", "created"].includes(state) ? "Hypothesis approved" : "Approve hypothesis";

  const trackPanel = document.getElementById("track-panel");
  trackPanel.hidden = !["approved", "bound", "created"].includes(state);
  if (!trackPanel.hidden) renderTrackPicker(payload.tracks || [], session.track_id);
  document.getElementById("intake-bind").disabled = !intakeState.trackId || state === "created";

  const bindingPanel = document.getElementById("binding-panel");
  bindingPanel.hidden = !(["bound", "created"].includes(state) && payload.binding);
  if (!bindingPanel.hidden) renderBinding(payload.binding, session);
}

function renderTrackPicker(tracks, chosen) {
  if (chosen && !intakeState.trackId) intakeState.trackId = chosen;
  const picker = document.getElementById("track-picker");
  picker.innerHTML = tracks.length ? tracks.map((t) =>
    `<label class="track-option${intakeState.trackId === t.id ? " selected" : ""}">` +
    `<input type="radio" name="track" value="${esc(t.id)}"${intakeState.trackId === t.id ? " checked" : ""}>` +
    `<span><strong>${esc(t.title)}</strong><br><small>${esc(t.summary)}</small><br>` +
    `<small>${(t.columns || []).map((c) => esc(c.name)).join(" · ")}</small></span></label>`
  ).join("") : '<div class="empty-state">No tracks are configured.</div>';
  picker.querySelectorAll('input[name="track"]').forEach((input) => {
    input.addEventListener("change", () => {
      intakeState.trackId = input.value;
      renderTrackPicker(tracks, null);
      document.getElementById("intake-bind").disabled = false;
    });
  });
}

function renderBinding(binding, session) {
  text("binding-rationale", binding.rationale || "");
  const rules = document.getElementById("binding-rules");
  const list = binding.falsifiers || [];
  rules.innerHTML = list.length ? list.map((rule, i) =>
    `<label><input type="checkbox" name="rule" value="${esc(rule.id)}" checked>` +
    `<span><strong>${esc(rule.id)}</strong> ${esc(rule.description || "")}<br>` +
    `<small>${esc((binding.rules_text || [])[i] || "")}</small></span></label>`
  ).join("") : "";
  const note = document.getElementById("binding-note");
  note.hidden = !binding.note;
  note.textContent = binding.note || "";
  const labId = document.getElementById("intake-lab-id");
  if (!labId.value) labId.value = session.lab_id || binding.lab_id_suggestion || (session.draft ? session.draft.slug : "") || "";
  const create = document.getElementById("intake-create");
  create.disabled = session.state === "created";
  create.textContent = session.state === "created"
    ? `Lab ${session.lab_id} created`
    : (controlState.session && controlState.session.auto_start ? "Create and start lab" : "Create lab");
}

function initIntakeView() {
  const form = document.getElementById("intake-form");
  const input = document.getElementById("intake-input");
  input.addEventListener("input", () => text("intake-count", input.value.length));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (intakeState.busy) return;
    intakeState.busy = true;
    document.getElementById("intake-send").disabled = true;
    document.getElementById("intake-thinking").hidden = false;
    showMessage("intake-message");
    try {
      const sid = await ensureIntakeSession();
      const payload = await postJSON(`/api/intake/sessions/${encodeURIComponent(sid)}/messages`, { text: input.value });
      input.value = "";
      text("intake-count", "0");
      renderIntake(payload);
      renderIntakeSessions(await getJSON("/api/intake/sessions"));
    } catch (error) {
      showMessage("intake-message", error.message, "error");
      if (intakeState.sessionId) {
        try { await loadIntakeSession(intakeState.sessionId); } catch (_) { /* keep the error */ }
      }
    } finally {
      intakeState.busy = false;
      document.getElementById("intake-send").disabled = false;
      document.getElementById("intake-thinking").hidden = true;
    }
  });
  document.getElementById("intake-approve").addEventListener("click", async () => {
    try {
      renderIntake(await postJSON(`/api/intake/sessions/${encodeURIComponent(intakeState.sessionId)}/approve`, {}));
    } catch (error) {
      showMessage("intake-message", error.message, "error");
    }
  });
  document.getElementById("intake-bind").addEventListener("click", async () => {
    const button = document.getElementById("intake-bind");
    button.disabled = true;
    showMessage("intake-message", "Mapping the falsifier onto the track…");
    try {
      renderIntake(await postJSON(`/api/intake/sessions/${encodeURIComponent(intakeState.sessionId)}/bind`, { track_id: intakeState.trackId }));
      showMessage("intake-message");
    } catch (error) {
      showMessage("intake-message", error.message, "error");
      button.disabled = false;
    }
  });
  document.getElementById("intake-create").addEventListener("click", async () => {
    const button = document.getElementById("intake-create");
    button.disabled = true;
    showMessage("intake-create-message", "Creating the lab…");
    try {
      const kept = Array.from(document.querySelectorAll('#binding-rules input[name="rule"]:checked')).map((el) => el.value);
      const result = await postJSON(`/api/intake/sessions/${encodeURIComponent(intakeState.sessionId)}/create`, {
        lab_id: document.getElementById("intake-lab-id").value.trim() || null,
        falsifiers: kept,
      });
      showMessage("intake-create-message", result.started ? `Lab ${result.lab_id} created and started.` : `Lab ${result.lab_id} created.${result.start_error ? ` ${result.start_error}` : ""}`, result.start_error ? "error" : "success");
      intakeState.loaded = false;
      intakeState.sessionId = null;
      await refresh();
      await openLabTab(result.lab_id);
    } catch (error) {
      showMessage("intake-create-message", error.message, "error");
      button.disabled = false;
    }
  });
}

initRouting();
initPanelToggles();
initIntakeTabs();
initConnectForm();
initSteeringForm();
initRuntimeControls();
initJoinForm();
initIntakeView();
refresh();
setInterval(refresh, 4000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
