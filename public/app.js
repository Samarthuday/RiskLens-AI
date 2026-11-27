"use strict";
const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const paths = {
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  arrows: "M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4",
  briefcase: "M9 6V4h6v2M3 7h18v13H3zM3 12c5 4 13 4 18 0M10 13h4v3h-4z",
  sliders: "M4 6h16M4 12h16M4 18h16M8 3v6m8 0v6m-7 0v6",
  pulse: "M2 12h5l3-8 4 16 3-8h5",
  book: "M12 5c-3-2-7-2-10-1v15c4-1 7-1 10 1 3-2 7-2 10-1V4c-3-1-7-1-10 1zm0 0v15",
  layers: "m12 3 10 5-10 5L2 8zm-9 9 9 5 9-5M3 16l9 5 9-5",
  shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6",
  external: "M14 3h7v7m0-7L10 14M10 3H3v18h18v-7",
  lock: "M5 10h14v11H5zM8 10V6a4 4 0 0 1 8 0v4",
  menu: "M3 6h18M3 12h18M3 18h18",
  search: "M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  refresh: "M20 7a9 9 0 0 0-15-1L2 9m0-6v6h6M4 17a9 9 0 0 0 15 1l3-3m0 6v-6h-6",
  x: "m6 6 12 12M6 18 18 6",
  download: "M12 3v12m-5-5 5 5 5-5M4 15v6h16v-6",
  play: "m8 4 12 8-12 8z",
  pause: "M7 4v16M17 4v16",
  chevron: "m9 5 7 7-7 7",
  left: "m15 5-7 7 7 7",
  down: "m6 9 6 6 6-6",
  clock: "M12 7v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  check: "m5 12 4 4 10-10",
  info: "M12 11v6m0-11v1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  sort: "m8 4-3 3-3-3m3 3v13m11 0 3-3 3 3m-3-3V4",
  network:
    "M5 7h5m4 0h5M12 9v6M7 18h3m4 0h3M3 5h4v4H3zm7 0h4v4h-4zm9 0h4v4h-4zM3 16h4v4H3zm7 0h4v4h-4zm7 0h4v4h-4z",
  file: "M14 2H5v20h14V7zm0 0v5h5M8 12h8m-8 4h8",
  spark: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z",
  chart: "M4 4v16h17M8 15l4-5 4 2 5-7",
  server: "M3 3h18v7H3zm0 11h18v7H3zM7 6h.1M7 17h.1",
  plus: "M12 5v14M5 12h14",
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;
function hydrateIcons(root = document) {
  root
    .querySelectorAll("[data-icon]")
    .forEach((el) => (el.innerHTML = icon(el.dataset.icon)));
}
const pageNames = {
  overview: "Overview",
  transactions: "Transactions",
  cases: "Case inbox",
  policy: "Policy lab",
  monitoring: "System health",
  research: "Research foundation",
};
const state = {
  page: "overview",
  transactions: [],
  cases: [],
  metrics: {},
  meta: null,
  drift: null,
  simulation: { running: false, scenario: "burst" },
  total: 0,
  query: "",
  currency: "all",
  status: "all",
  payment: "all",
  sort: "timestamp",
  direction: -1,
  tablePage: 1,
  caseQuery: "",
  caseStatus: "all",
  casePage: 1,
  chartCurrency: "",
  drawer: null,
  drawerTab: "evidence",
  drawerRequest: 0,
  streamTimer: null,
  refreshing: false,
  lastUpdated: null,
  policyDraft: null,
  policyResult: null,
};
const numeric = (value) => (Number.isFinite(value) ? value : 0);
const compactNumber = (value) =>
  new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
const number = (value) =>
  new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(
    numeric(value),
  );
const amount = (value) =>
  new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numeric(value));
const money = (value, currency) => `${amount(value)} ${esc(currency)}`;
function dateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "Unavailable"
    : date.toLocaleString("en-GB", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
      }) + " UTC";
}
function timeOnly(value) {
  return new Date(value).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
}
function label(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/^./, (c) => c.toUpperCase());
}
function toast(message, error = false) {
  const el = document.createElement("div");
  el.className = `toast${error ? " error" : ""}`;
  el.innerHTML =
    icon(error ? "info" : "check") + `<span>${esc(message)}</span>`;
  $("toast-region").append(el);
  setTimeout(() => el.remove(), 6500);
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
    signal: options.signal || AbortSignal.timeout(20000),
  });
  const data = await response
    .json()
    .catch(() => ({ detail: "The server returned an unreadable response." }));
  if (!response.ok) {
    let message =
      typeof data.detail === "string"
        ? data.detail
        : response.status === 422
          ? "Check the values you entered."
          : `Request failed (${response.status}).`;
    if (response.status === 429)
      message = "Request limit reached. Please wait a minute, then refresh.";
    throw new Error(message);
  }
  return data;
}
const post = (path, body) =>
  api(path, {
    method: "POST",
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
function badge(text, tone = "neutral") {
  return `<span class="badge ${tone}">${esc(text)}</span>`;
}
function statusBadge(tx) {
  if (tx.review_decision === "escalated") return badge("Escalated", "red");
  if (tx.case_status === "reviewed") return badge("Reviewed", "green");
  if (tx.case_status === "open") return badge("Awaiting review", "amber");
  return badge("Not investigated");
}
function scoreCell(tx) {
  const p = tx.model_probability;
  if (p === null || p === undefined)
    return `<span class="badge neutral">Unscored</span>`;
  return `<span class="score"><span class="score-line"><i style="width:${Math.max(2, p * 100)}%;background:${p >= 0.2 ? "#b87e64" : "#579b75"}"></i></span>${(p * 100).toFixed(2)}%</span>`;
}
function latestCase(transactionId) {
  return state.cases.find((c) => c.transaction_id === transactionId);
}
function empty(title, description, action = "") {
  return `<div class="empty-state"><span data-icon="${action ? "search" : "briefcase"}"></span><h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;
}
function heading(title, description, actions = "") {
  return `<div class="page-heading"><div><div class="eyebrow">RISK OPERATIONS</div><h1>${title}</h1><p>${description}</p></div><div class="heading-actions">${actions}</div></div>`;
}
function stat(title, value, note, name = "chart") {
  return `<article class="card stat"><div class="stat-top"><span>${title}</span><span class="stat-icon">${icon(name)}</span></div><div class="stat-value">${value}</div><div class="stat-note">${note}</div></article>`;
}
function streamControls() {
  return `<select id="scenario-select" aria-label="Demo scenario"><option value="burst" ${state.simulation.scenario === "burst" ? "selected" : ""}>Burst scenario</option><option value="routine" ${state.simulation.scenario === "routine" ? "selected" : ""}>Routine scenario</option></select><button class="button" data-action="reset" title="Reset simulated transactions and their cases">${icon("refresh")}Reset</button><button class="button primary" data-action="stream">${icon(state.streamTimer ? "pause" : "play")}${state.streamTimer ? "Pause stream" : "Start stream"}</button>`;
}
function renderOverview() {
  const m = state.metrics;
  const reviewed = m.reviewed_cases || 0,
    totalCases = m.investigation_count || 0;
  return (
    heading(
      "Risk overview",
      "A complete picture of your transaction surveillance workspace.",
      streamControls(),
    ) +
    `<div class="stats-grid">${stat("Transactions stored", number(m.transaction_count), `${number(state.transactions.length)} in the recent activity window`, "arrows")}${stat("Open investigations", number(m.open_cases), "Cases awaiting an analyst decision", "briefcase")}${stat("Reviews completed", number(reviewed), totalCases ? `<strong>${Math.round((reviewed / totalCases) * 100)}%</strong> of saved investigations` : "Create a case to begin reviewing", "check")}${stat("Model coverage", m.unique_transactions_scored ? `${Math.round((m.unique_transactions_scored / Math.max(m.transaction_count, 1)) * 100)}%` : "—", state.meta?.runtime_model_loaded ? `${number(m.unique_transactions_scored)} unique transactions scored` : "Evidence mode · model not installed", "shield")}</div>` +
    `<div class="chart-grid">${renderVolumeChart()}${renderReviewChart()}</div>` +
    renderTransactionTable(true) +
    `<div class="bottom-grid"><article class="card"><div class="card-head"><div><h2>Recent investigations</h2><p>Your latest saved cases and analyst decisions</p></div><button class="link-button" data-nav="cases">View inbox ${icon("chevron")}</button></div><div class="activity-list">${
      state.cases
        .slice(0, 3)
        .map(
          (c) =>
            `<div class="activity-item"><span class="event-icon">${icon(c.review_decision === "escalated" ? "shield" : c.status === "reviewed" ? "check" : "file")}</span><div><button class="txn-link" data-case="${esc(c.investigation_id)}">${esc(c.transaction_id)}</button><p>${esc(c.status === "reviewed" ? `${label(c.review_decision)} · analyst review recorded` : "Evidence gathered · awaiting review")}</p></div><time>${esc(timeOnly(c.reviewed_at || c.created_at))}</time></div>`,
        )
        .join("") ||
      empty(
        "Your case history starts here",
        "Open a transaction to gather evidence and save your first investigation.",
      )
    }</div></article>${renderModelCard()}</div>`
  );
}
function currencyOptions(selected = "all", all = true) {
  if (!all && !state.transactions.length)
    return `<option value="USD">USD</option>`;
  return (
    (all ? `<option value="all">All currencies</option>` : "") +
    [...new Set(state.transactions.map((t) => t.payment_currency))]
      .sort()
      .map(
        (c) =>
          `<option value="${esc(c)}" ${c === selected ? "selected" : ""}>${esc(c)}</option>`,
      )
      .join("")
  );
}
function renderVolumeChart() {
  const currencies = [
    ...new Set(state.transactions.map((t) => t.payment_currency)),
  ].sort();
  if (!currencies.includes(state.chartCurrency))
    state.chartCurrency = currencies.includes("USD")
      ? "USD"
      : currencies[0] || "USD";
  const rows = state.transactions
    .filter((t) => t.payment_currency === state.chartCurrency)
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  const total = rows.reduce((sum, t) => sum + t.amount, 0);
  let graph = empty(
    "No activity for this currency",
    "Choose another currency or seed a synthetic scenario.",
  );
  if (rows.length) {
    const first = new Date(rows[0].timestamp).valueOf(),
      last = new Date(rows.at(-1).timestamp).valueOf();
    const bins = Array(18).fill(0);
    rows.forEach((t) => {
      const bin = Math.min(
        17,
        Math.floor(
          ((new Date(t.timestamp).valueOf() - first) /
            Math.max(last - first, 1)) *
            17,
        ),
      );
      bins[bin] += t.amount;
    });
    const max = Math.max(...bins, 1),
      points = bins.map((v, i) => [38 + i * 29, 131 - (v / max) * 104]);
    const line = points
      .map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`)
      .join(" ");
    const area = line + ` L531,131 L38,131 Z`;
    graph = `<div class="area-chart"><svg viewBox="0 0 560 164" role="img" aria-label="${esc(state.chartCurrency)} transaction volume over the displayed activity window"><defs><linearGradient id="volume-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#73b69b" stop-opacity=".24"/><stop offset="100%" stop-color="#73b69b" stop-opacity=".015"/></linearGradient></defs>${[27, 79, 131].map((y, i) => `<line class="chart-gridline" x1="38" y1="${y}" x2="537" y2="${y}"/><text class="chart-label" x="0" y="${y + 3}">${compactNumber(max * (1 - i / 2))}</text>`).join("")}<path d="${area}" fill="url(#volume-fill)"/><path d="${line}" fill="none" stroke="#49997a" stroke-width="2.1" stroke-linejoin="round"/>${[0, 5, 11, 17].map((i) => `<text class="chart-label" x="${38 + i * 29}" y="155" text-anchor="${i === 0 ? "start" : i === 17 ? "end" : "middle"}">${timeOnly(new Date(first + ((last - first) * i) / 17).toISOString())}</text>`).join("")}</svg></div>`;
  }
  return `<article class="card"><div class="card-head"><div><h2>Transaction volume</h2><p>Recent stored activity · time shown in UTC</p></div><select id="chart-currency" aria-label="Chart currency">${currencyOptions(state.chartCurrency, false)}</select></div><div class="chart-summary"><strong>${money(total, state.chartCurrency)}</strong><span>${number(rows.length)} transactions</span></div>${graph}<div class="chart-legend"><i class="legend-swatch"></i>Volume by event time · currencies shown separately</div></article>`;
}
function renderReviewChart() {
  const m = state.metrics,
    counts = [
      m.open_cases || 0,
      (m.reviewed_cases || 0) - (m.escalated_cases || 0),
      m.escalated_cases || 0,
    ],
    colors = ["#9ac5b0", "#3c8e6d", "#d9b57c"],
    total = counts.reduce((a, b) => a + b, 0);
  let offset = 0;
  const segments = counts
    .map((n, i) => {
      const length = (n / Math.max(total, 1)) * 314.16;
      const svg = `<circle cx="60" cy="60" r="50" fill="none" stroke="${colors[i]}" stroke-width="11" stroke-dasharray="${length} ${314.16 - length}" stroke-dashoffset="${-offset}"/>`;
      offset += length;
      return svg;
    })
    .join("");
  return `<article class="card"><div class="card-head"><div><h2>Case disposition</h2><p>Recorded analyst workflow</p></div>${badge("All cases")}</div><div class="donut-layout"><div class="donut"><svg viewBox="0 0 120 120" role="img" aria-label="${counts[0]} open, ${counts[1]} reviewed, ${counts[2]} escalated cases"><circle cx="60" cy="60" r="50" fill="none" stroke="#edf2ec" stroke-width="11"/>${segments}</svg><div class="donut-value"><strong>${number(total)}</strong><span>Total cases</span></div></div><div class="legend-list">${["Awaiting review", "Reviewed", "Escalated"].map((text, i) => `<div class="legend-row"><i style="background:${colors[i]}"></i>${text}<strong>${number(counts[i])}</strong></div>`).join("")}</div></div><div class="card-foot">${icon("info")}A review disposition is not a confirmed outcome label.</div></article>`;
}
function filteredTransactions() {
  let rows = state.transactions.filter((t) => {
    const q = state.query.toLowerCase();
    return (
      (!q ||
        [t.transaction_id, t.sender_id, t.receiver_id, t.payment_type].some(
          (v) => String(v).toLowerCase().includes(q),
        )) &&
      (state.currency === "all" || t.payment_currency === state.currency) &&
      (state.payment === "all" || t.payment_type === state.payment) &&
      (state.status === "all" ||
        (state.status === "uninvestigated" && !t.investigation_id) ||
        (state.status === "open" && t.case_status === "open") ||
        (state.status === "reviewed" && t.case_status === "reviewed") ||
        (state.status === "escalated" && t.review_decision === "escalated"))
    );
  });
  return rows.sort((a, b) => {
    const va = state.sort === "amount" ? a.amount : a.timestamp;
    const vb = state.sort === "amount" ? b.amount : b.timestamp;
    return (
      (va < vb
        ? -1
        : va > vb
          ? 1
          : a.transaction_id.localeCompare(b.transaction_id)) * state.direction
    );
  });
}
function renderTransactionTable(compact = false) {
  const rows = filteredTransactions(),
    pageSize = compact ? 6 : 12,
    maxPage = Math.max(1, Math.ceil(rows.length / pageSize));
  state.tablePage = Math.min(state.tablePage, maxPage);
  const displayed = rows.slice(
    (state.tablePage - 1) * pageSize,
    state.tablePage * pageSize,
  );
  return `<article class="card table-card"><div class="table-heading"><h2>${compact ? "Recent transactions" : "Transaction queue"}<span class="count-chip">${number(rows.length)}</span></h2><button class="${compact ? "link-button" : "button"}" ${compact ? 'data-nav="transactions"' : 'data-action="export"'}>${compact ? `View all ${icon("chevron")}` : `${icon("download")} Export CSV`}</button></div><div class="toolbar"><div class="search-input"><span data-icon="search"></span><label class="screen-reader" for="transaction-search">Search transactions</label><input id="transaction-search" type="search" placeholder="Search ID, sender, receiver…" value="${esc(state.query)}" autocomplete="off"></div><select id="filter-status" aria-label="Filter by case status">${[
    ["all", "All statuses"],
    ["uninvestigated", "Not investigated"],
    ["open", "Awaiting review"],
    ["reviewed", "Reviewed"],
    ["escalated", "Escalated"],
  ]
    .map(
      ([v, l]) =>
        `<option value="${v}" ${state.status === v ? "selected" : ""}>${l}</option>`,
    )
    .join(
      "",
    )}</select><select id="filter-currency" aria-label="Filter by currency">${currencyOptions(state.currency)}</select>${
    !compact
      ? `<select id="filter-payment" aria-label="Filter by payment method"><option value="all">All methods</option>${[
          ...new Set(state.transactions.map((t) => t.payment_type)),
        ]
          .sort()
          .map(
            (v) =>
              `<option value="${esc(v)}" ${v === state.payment ? "selected" : ""}>${esc(v)}</option>`,
          )
          .join("")}</select>`
      : ""
  }</div><div class="table-scroll"><table><thead><tr><th scope="col">Transaction ID</th><th scope="col"><button data-sort="timestamp">Event time ${icon("sort")}</button></th><th scope="col">Sender / Receiver</th><th scope="col"><button data-sort="amount">Amount ${icon("sort")}</button></th><th scope="col">Model probability</th><th scope="col">Case status</th><th scope="col"><span class="screen-reader">Actions</span></th></tr></thead><tbody>${displayed.map((t) => `<tr><td><button class="txn-link" data-transaction="${esc(t.transaction_id)}">${esc(t.transaction_id)}</button><span class="cell-secondary">${esc(t.payment_type)}</span></td><td>${esc(timeOnly(t.timestamp))}<span class="cell-secondary">${esc(new Date(t.timestamp).toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" }))} · UTC</span></td><td><div class="party-cell"><span class="party-avatar">${esc(t.sender_id.slice(-2))}</span><div><span class="party-name">${esc(t.sender_id)}</span><span class="cell-secondary">to ${esc(t.receiver_id)}</span></div></div></td><td class="amount-cell">${amount(t.amount)}<span class="currency-text">${esc(t.payment_currency)}</span></td><td>${scoreCell(t)}</td><td>${statusBadge(t)}</td><td><button class="icon-button" data-transaction="${esc(t.transaction_id)}" aria-label="Investigate ${esc(t.transaction_id)}">${icon("chevron")}</button></td></tr>`).join("") || `<tr><td colspan="7">${state.transactions.length ? empty("No matching transactions", "Try another search or clear your filters.", `<button class="button" data-action="clear-filters">Clear filters</button>`) : empty("Ready for your first transaction", "Load a reproducible synthetic scenario to explore the workspace.", `<button class="button primary" data-action="seed">Load sample activity</button>`)}</td></tr>`}</tbody></table></div><div class="table-pagination"><span>${rows.length ? `${(state.tablePage - 1) * pageSize + 1}–${Math.min(state.tablePage * pageSize, rows.length)} of ${number(rows.length)} transactions` : "0 transactions"}${state.total > state.transactions.length ? ` · latest ${state.transactions.length} of ${number(state.total)} stored` : ""}</span><div class="pagination-buttons"><button class="icon-button" data-table-page="-1" aria-label="Previous page" ${state.tablePage === 1 ? "disabled" : ""}>${icon("left")}</button><span>${state.tablePage} / ${maxPage}</span><button class="icon-button" data-table-page="1" aria-label="Next page" ${state.tablePage === maxPage ? "disabled" : ""}>${icon("chevron")}</button></div></div></article>`;
}
function renderModelCard() {
  const loaded = state.meta?.runtime_model_loaded;
  return `<article class="card"><div class="card-head"><div><h2>Model readiness</h2><p>Transparent by design</p></div>${badge(loaded ? "Model loaded" : "Evidence mode", loaded ? "green" : "neutral")}</div><div class="model-callout"><span data-icon="${loaded ? "shield" : "layers"}"></span><div><h3>${loaded ? "Research model connected" : "Start with the evidence"}</h3><p>${loaded ? "Scores are generated by the installed research model. Inspect its version, provenance, and limitations before interpreting predictions." : "Investigate activity, inspect historical signals, and record analyst reviews. Model probabilities and SHAP become available when a compatible artifact is installed."}</p><button class="button small" data-nav="research">View research foundation ${icon("book")}</button></div></div></article>`;
}
function renderCases() {
  const rows = state.cases.filter(
    (c) =>
      (state.caseStatus === "all" ||
        (state.caseStatus === "escalated"
          ? c.review_decision === "escalated"
          : c.status === state.caseStatus)) &&
      (!state.caseQuery ||
        [c.investigation_id, c.transaction_id, c.analyst_note || ""].some((v) =>
          v.toLowerCase().includes(state.caseQuery.toLowerCase()),
        )),
  );
  const maxPage = Math.max(1, Math.ceil(rows.length / 12));
  state.casePage = Math.min(state.casePage, maxPage);
  return (
    heading(
      "Case inbox",
      "Evidence, decisions, and context — kept together.",
      `<button class="button" data-nav="transactions">${icon("plus")}Investigate a transaction</button>`,
    ) +
    `<div class="stats-grid">${stat("Saved investigations", number(state.metrics.investigation_count), "Persisted evidence reports", "briefcase")}${stat("Awaiting review", number(state.metrics.open_cases), "Ready for an analyst decision", "clock")}${stat("Reviewed", number(state.metrics.reviewed_cases), "Includes escalated cases", "check")}${stat("Escalated", number(state.metrics.escalated_cases), "Flagged for further investigation", "shield")}</div><article class="card table-card"><div class="table-heading"><h2>All investigations <span class="count-chip">${rows.length}</span></h2></div><div class="toolbar"><div class="search-input"><span data-icon="search"></span><label for="case-search" class="screen-reader">Search cases</label><input id="case-search" type="search" placeholder="Search cases or analyst notes…" value="${esc(state.caseQuery)}"></div><select id="case-filter" aria-label="Filter cases">${[
      ["all", "All cases"],
      ["open", "Awaiting review"],
      ["reviewed", "Reviewed"],
      ["escalated", "Escalated"],
    ]
      .map(
        ([v, l]) =>
          `<option value="${v}" ${state.caseStatus === v ? "selected" : ""}>${l}</option>`,
      )
      .join(
        "",
      )}</select></div><div class="table-scroll"><table><thead><tr><th>Case / Transaction</th><th>Created</th><th>Report type</th><th>Evidence</th><th>Disposition</th><th>Action</th></tr></thead><tbody>${
      rows
        .slice((state.casePage - 1) * 12, state.casePage * 12)
        .map(
          (c) =>
            `<tr><td><button class="txn-link" data-case="${esc(c.investigation_id)}">${esc(c.investigation_id)}</button><span class="cell-secondary">${esc(c.transaction_id)}</span></td><td>${esc(dateTime(c.created_at))}</td><td>${badge(c.report_mode === "llm_assisted" ? "AI assisted" : "Evidence report", c.report_mode === "llm_assisted" ? "blue" : "neutral")}</td><td>${c.evidence.length} sources</td><td>${c.review_decision ? badge(label(c.review_decision), c.review_decision === "escalated" ? "red" : "green") : badge("Awaiting review", "amber")}</td><td><button class="button small" data-case="${esc(c.investigation_id)}">Open case</button></td></tr>`,
        )
        .join("") ||
      `<tr><td colspan="6">${empty("No cases here yet", "Open a transaction to start an investigation, or change your search.")}</td></tr>`
    }</tbody></table></div><div class="table-pagination"><span>${number(rows.length)} matching cases · latest ${state.cases.length} loaded</span><div class="pagination-buttons"><button class="icon-button" data-case-page="-1" ${state.casePage === 1 ? "disabled" : ""} aria-label="Previous cases">${icon("left")}</button><span>${state.casePage} / ${maxPage}</span><button class="icon-button" data-case-page="1" ${state.casePage === maxPage ? "disabled" : ""} aria-label="Next cases">${icon("chevron")}</button></div></div></article>`
  );
}
function renderPolicy() {
  const draft = state.policyDraft || {
    probabilities: "",
    alert_budget: "0.05",
    missed_fraud_cost: "100",
    false_positive_cost: "1",
    manual_review_cost: "0.25",
  };
  return (
    heading(
      "Policy lab",
      "Explore review capacity and expected costs under explicit assumptions.",
      badge("Hypothetical analysis", "amber"),
    ) +
    `<div class="section-grid"><article class="card"><div class="card-head"><div><h2>Configure your scenario</h2><p>Probabilities are inputs, not outcome labels.</p></div></div><form id="policy-form" class="padded"><div class="form-grid"><label class="field full">Probabilities<textarea name="probabilities" required placeholder="Paste probabilities between 0 and 1, separated by commas">${esc(draft.probabilities)}</textarea><small>Use saved model scores or enter your own hypothetical values.</small></label><div class="field full"><button type="button" class="button" id="use-scores" ${state.transactions.some((t) => t.model_probability !== null && t.model_probability !== undefined) ? "" : "disabled"}>${icon("layers")}Use stored model scores</button></div>${[
      ["alert_budget", "Review capacity (fraction)", "0.001", "1"],
      ["missed_fraud_cost", "Missed-event cost", "0.01", "1000000000"],
      ["false_positive_cost", "False-positive cost", "0.01", "1000000000"],
      ["manual_review_cost", "Cost per review", "0.01", "1000000000"],
    ]
      .map(
        ([name, text, step, max]) =>
          `<label class="field">${text}<input type="number" name="${name}" value="${esc(draft[name])}" min="${name === "alert_budget" ? ".000001" : "0"}" max="${max}" step="any" required></label>`,
      )
      .join(
        "",
      )}</div><div class="assumption">All costs use the same arbitrary unit. Review effectiveness is assumed to be 80%. This estimates expected costs; it does not measure financial savings.</div><div class="button-row"><button type="submit" class="button primary">${icon("sliders")}Compare policy costs</button></div></form></article><article class="card"><div class="card-head"><div><h2>Policy comparison</h2><p>Your assumptions, made visible</p></div></div><div id="policy-result" class="policy-result">${renderPolicyResult()}</div></article></div>`
  );
}
function renderPolicyResult() {
  const r = state.policyResult;
  return r
    ? `<div class="cost-comparison"><div class="cost-box"><span>Without review</span><strong>${amount(r.expected_cost_without_review)}</strong><span>Expected cost units</span></div><div class="cost-box"><span>With review policy</span><strong>${amount(r.expected_cost_with_policy)}</strong><span>Expected cost units</span></div></div><div class="status-list"><div class="status-row"><span>Transactions reviewed</span><strong>${r.review_count} / ${r.population}</strong></div><div class="status-row"><span>Available review slots</span><strong>${r.alert_capacity}</strong></div><div class="status-row"><span>Break-even probability</span><strong>${(r.cost_optimal_threshold * 100).toFixed(3)}%</strong></div><div class="status-row"><span>Expected cost difference</span><strong>${amount(r.estimated_cost_difference)}</strong></div></div><div class="assumption">${esc(r.scope_note)} Capacity rounds up to a whole transaction; a small batch can exceed the requested percentage.</div>`
    : empty(
        "Make the trade-off visible",
        "Configure probabilities, costs, and capacity to compare a hypothetical review policy.",
      );
}
function renderMonitoring() {
  const m = state.metrics,
    loaded = state.meta?.runtime_model_loaded,
    d = state.drift;
  return (
    heading(
      "System health",
      "Measured application activity, with clear availability boundaries.",
      `<button class="button" data-action="refresh">${icon("refresh")}Refresh checks</button>`,
    ) +
    `<div class="stats-grid">${stat("Inference calls", number(m.predictions_recorded), `${number(m.unique_transactions_scored)} unique transactions`, "pulse")}${stat("Inference p50", m.latency_p50_ms === null ? "—" : `${numeric(m.latency_p50_ms).toFixed(1)} ms`, "Model inference only", "clock")}${stat("Inference p95", m.latency_p95_ms === null ? "—" : `${numeric(m.latency_p95_ms).toFixed(1)} ms`, "Not full investigation latency", "chart")}${stat("Audit events", number(m.audit_event_count), "Recorded workflow activity", "file")}</div><div class="section-grid"><article class="card"><div class="card-head"><div><h2>Service readiness</h2><p>Current runtime state</p></div></div><div class="status-list"><div class="status-row"><span>Application API</span>${badge("Connected", "green")}</div><div class="status-row"><span>Transaction storage</span>${badge("Available", "green")}</div><div class="status-row"><span>Model inference</span>${badge(loaded ? "Available" : "Not configured", loaded ? "green" : "neutral")}</div><div class="status-row"><span>Outcome labels</span>${badge("Not available")}</div><div class="status-row"><span>Simulation</span>${badge(state.streamTimer ? "Streaming" : "Paused", state.streamTimer ? "green" : "neutral")}</div></div></article><article class="card"><div class="card-head"><div><h2>Score-distribution drift</h2><p>Shift is a signal, not proof of model degradation.</p></div></div><div class="padded">${d?.status === "measured" ? `<div class="stat-value">${d.population_stability_index.toFixed(3)}</div><p class="prose">Population Stability Index across ${d.observations} inference observations.</p>${badge(d.drift_alert ? "Shift threshold exceeded" : "Below shift threshold", d.drift_alert ? "amber" : "green")}` : empty(d?.status === "insufficient_sample" ? "More observations needed" : "Drift comparison unavailable", d?.detail || `At least ${d?.minimum_observations || 20} observations and a compatible model baseline are required.`)}<div class="assumption">No fraud accuracy or loss-reduction metrics are inferred from an unlabeled synthetic stream.</div></div></article></div><div class="bottom-grid">${renderModelCard()}<article class="card padded prose"><h3 style="margin-top:0">Operational scope</h3><p>This workspace is a single-instance research demonstration. Synthetic reset controls affect this instance. It is not a multi-tenant payment control system.</p><a class="button" href="/api/docs" target="_blank" rel="noopener">${icon("file")}Open API documentation</a></article></div>`
  );
}
function renderResearch() {
  const r = state.meta?.research_metrics;
  if (!r)
    return empty(
      "Research metadata unavailable",
      "Refresh the workspace to retrieve source provenance.",
    );
  return (
    heading(
      "Research foundation",
      "The science behind the application, with its provenance intact.",
      `<a class="button" href="https://github.com/Samarthuday/Quantitative-Transaction-Risk-Modeling" target="_blank" rel="noopener">${icon("book")}Source repository</a>`,
    ) +
    `<div class="section-grid"><article class="card"><div class="card-head"><div><h2>Historical held-out performance</h2><p>Synthetic SAML-D · source research results</p></div>${badge("Historical")}</div><div class="padded">${[
      ["PR-AUC", r.test_metrics.pr_auc.toFixed(4)],
      ["ROC-AUC", r.test_metrics.roc_auc.toFixed(4)],
      [
        "Recall at 0.1% alert budget",
        (r.test_metrics["alert_0.100%_recall"] * 100).toFixed(2) + "%",
      ],
      ["Brier score", r.test_metrics.brier_score.toFixed(7)],
    ]
      .map(
        ([k, v]) =>
          `<div class="research-metric"><span>${k}</span><strong>${v}</strong></div>`,
      )
      .join(
        "",
      )}<div class="assumption">These are previously reported research results. They are not RiskLens runtime performance or evidence of effectiveness at a payment processor.</div></div></article><article class="card padded prose"><h3 style="margin-top:0">Model and artifact provenance</h3><p>Research model version <strong>${esc(r.model_version)}</strong><br>Source report <code>${esc(r.source_file)}</code></p><p>Pinned source commit<br><code>${esc(r.source_commit)}</code></p><p>Runtime artifact<br>${state.meta.runtime_model_loaded ? `<code>${esc(state.meta.artifact_sha256)}</code>` : "No compatible trained artifact is installed."}</p><p>${esc(r.provenance_note)}</p></article></div><div class="bottom-grid"><article class="card padded prose"><h3 style="margin-top:0">What the model estimates</h3><p>The research predicts suspicious events in synthetic anti-money-laundering data. That target is distinct from payment fraud, chargebacks, and realized financial loss.</p><p>New counterparties, sparse account history, category shift, and feature mismatches can affect inference. A model estimate always needs context and analyst judgment.</p></article><article class="card padded prose"><h3 style="margin-top:0">What this application adds</h3><p>Transaction ingestion, historical evidence, saved investigations, a review inbox, analyst notes, tool traces, optional model explanations, and cost-policy exploration.</p><p>Offline reports use a deterministic workflow. Optional AI summaries are labelled separately and cannot set probabilities or approve payments.</p></article></div>${state.meta.compatibility_warnings?.length ? `<div class="assumption">${state.meta.compatibility_warnings.map(esc).join("<br>")}</div>` : ""}`
  );
}
function renderPage() {
  const previous = document.activeElement;
  const focusId = previous?.id;
  const selection =
    previous instanceof HTMLInputElement ? previous.selectionStart : null;
  const renderers = {
    overview: renderOverview,
    transactions: () =>
      heading(
        "Transactions",
        "Search activity, follow the evidence, and open an investigation.",
        streamControls(),
      ) + renderTransactionTable(),
    cases: renderCases,
    policy: renderPolicy,
    monitoring: renderMonitoring,
    research: renderResearch,
  };
  $("page").innerHTML = renderers[state.page]();
  $("breadcrumb-page").textContent = pageNames[state.page];
  document.title = `${pageNames[state.page]} | RiskLens AI`;
  document.querySelectorAll("#navigation a").forEach((a) => {
    a.classList.toggle("active", a.dataset.page === state.page);
    if (a.dataset.page === state.page) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  $("nav-transactions").textContent = number(state.metrics.transaction_count);
  $("nav-cases").textContent = number(state.metrics.open_cases);
  hydrateIcons($("page"));
  if (focusId && $(focusId)) {
    const target = $(focusId);
    target.focus({ preventScroll: true });
    if (selection !== null && target.type === "search")
      target.setSelectionRange(selection, selection);
  }
}
function navigate(page) {
  if (!pageNames[page]) page = "overview";
  if (state.page === "policy") savePolicyDraft();
  state.page = page;
  state.tablePage = 1;
  state.casePage = 1;
  if (location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
  renderPage();
  $("sidebar").classList.remove("visible");
  $("menu-toggle").setAttribute("aria-expanded", "false");
  window.scrollTo({ top: 0 });
}
async function refresh({ initial = false, notify = false } = {}) {
  if (state.refreshing) return;
  state.refreshing = true;
  $("refresh").disabled = true;
  try {
    const [tx, cases, metrics, meta, simulation, drift] = await Promise.all([
      api("/api/v1/transactions?limit=500"),
      api("/api/v1/investigations?limit=500"),
      api("/api/v1/monitoring/metrics"),
      api("/api/v1/model/metadata"),
      api("/api/v1/simulation/status"),
      api("/api/v1/monitoring/drift"),
    ]);
    state.transactions = tx.items;
    state.total = tx.total ?? tx.count;
    state.cases = cases.items;
    state.metrics = metrics;
    state.meta = meta;
    state.simulation = simulation;
    state.drift = drift;
    state.lastUpdated = new Date();
    $("connection-banner").hidden = true;
    if (state.page === "policy") savePolicyDraft();
    renderPage();
    $("last-updated").textContent =
      `Updated ${state.lastUpdated.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} · ${state.transactions.length} recent transactions loaded`;
    if (notify) toast("Workspace refreshed.");
  } catch (error) {
    $("connection-banner").textContent =
      `Could not refresh: ${error.message} ${state.lastUpdated ? "Showing the last successfully loaded data." : ""}`;
    $("connection-banner").hidden = false;
    if (initial) {
      $("page").innerHTML =
        heading(
          "Your workspace is offline",
          "The application could not reach its data service.",
        ) +
        `<article class="card">${empty("Connection unavailable", error.message, `<button class="button primary" data-action="refresh">${icon("refresh")}Try again</button>`)}</article>`;
      hydrateIcons($("page"));
    } else toast(error.message, true);
  } finally {
    state.refreshing = false;
    $("refresh").disabled = false;
  }
}
function downloadFile(name, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function exportCsv() {
  const rows = filteredTransactions();
  const columns = [
    "transaction_id",
    "timestamp",
    "sender_id",
    "receiver_id",
    "amount",
    "payment_currency",
    "payment_type",
    "model_probability",
    "case_status",
    "review_decision",
  ];
  const csv = rows.map((row) =>
    columns
      .map((key) => {
        let value = String(row[key] ?? "");
        if (/^[\s]*[=+@-]/.test(value)) value = "'" + value;
        return '"' + value.replaceAll('"', '""') + '"';
      })
      .join(","),
  );
  downloadFile(
    "risklens-transactions.csv",
    "\uFEFF" + [columns.join(","), ...csv].join("\r\n"),
    "text/csv;charset=utf-8",
  );
  toast(`Exported ${rows.length} filtered transactions.`);
}
const reviewDrafts = new Map();
function drawerMetadata(tx) {
  return `<div class="drawer-topline"><div class="drawer-amount">${amount(tx.amount)}<span>${esc(tx.payment_currency)}</span></div>${statusBadge(tx)}</div><div class="drawer-metadata">${[
    ["Sender account", tx.sender_id],
    ["Receiver account", tx.receiver_id],
    ["Event time", dateTime(tx.timestamp)],
    ["Payment method", tx.payment_type],
    ["Bank locations", `${tx.sender_location} / ${tx.receiver_location}`],
    [
      "Data source",
      tx.source === "simulator" ? "Synthetic simulator" : label(tx.source),
    ],
  ]
    .map(
      ([k, v]) =>
        `<div class="meta-item"><span>${k}</span><strong>${esc(v)}</strong></div>`,
    )
    .join("")}</div>`;
}
async function openTransaction(transactionId, caseId = null) {
  const token = ++state.drawerRequest;
  state.drawerTab = "evidence";
  state.drawer = null;
  $("drawer-title").textContent = transactionId;
  if (!$("investigation-drawer").open) $("investigation-drawer").showModal();
  $("drawer-body").innerHTML =
    '<div class="drawer-loading"><p class="prose">Loading transaction and saved evidence…</p><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>';
  try {
    const tx =
      state.transactions.find((t) => t.transaction_id === transactionId) ||
      (await api(`/api/v1/transactions/${encodeURIComponent(transactionId)}`));
    let report = caseId
      ? await api(`/api/v1/investigations/${encodeURIComponent(caseId)}`)
      : latestCase(transactionId);
    if (!report && tx.investigation_id)
      report = await api(
        `/api/v1/investigations/${encodeURIComponent(tx.investigation_id)}`,
      );
    if (token !== state.drawerRequest) return;
    state.drawer = { tx, report, trace: null, history: null };
    renderDrawer();
  } catch (error) {
    if (token !== state.drawerRequest) return;
    $("drawer-body").innerHTML = empty(
      "Could not open this transaction",
      error.message,
      `<button class="button" data-retry-transaction="${esc(transactionId)}">Try again</button>`,
    );
    hydrateIcons($("drawer-body"));
  }
}
async function openCase(caseId) {
  const c = state.cases.find((c) => c.investigation_id === caseId);
  if (c) await openTransaction(c.transaction_id, caseId);
  else {
    try {
      const report = await api(
        `/api/v1/investigations/${encodeURIComponent(caseId)}`,
      );
      await openTransaction(report.transaction_id, caseId);
    } catch (error) {
      toast(error.message, true);
    }
  }
}
function renderDrawer() {
  const d = state.drawer;
  if (!d) return;
  const r = d.report;
  $("drawer-title").textContent = d.tx.transaction_id;
  const top = drawerMetadata(
    r ? { ...d.tx, case_status: r.status, review_decision: r.review_decision } : d.tx,
  );
  if (!r) {
    $("drawer-body").innerHTML =
      top +
      `<div class="recommendation"><h3>Begin with a complete evidence trail</h3><p>Gather prior transaction activity, calculate historical indicators, and save a structured investigation for review. ${state.meta?.runtime_model_loaded ? "The connected model will also produce a score and attempt SHAP attribution." : "This workspace is in evidence mode. No model probability will be generated."}</p></div><button class="button primary" data-action="investigate">${icon("search")}Run investigation</button><div class="assumption">The research model estimates suspicious events in synthetic AML data. Historical indicators alone do not establish fraud.</div>`;
    hydrateIcons($("drawer-body"));
    return;
  }
  const tabs = `<div class="drawer-tabs" role="tablist" aria-label="Investigation details">${[
    ["evidence", "Evidence"],
    ["activity", "Account activity"],
    ["trace", "Execution trace"],
  ]
    .map(
      ([v, l]) =>
        `<button type="button" role="tab" id="tab-${v}" aria-controls="panel-${v}" aria-selected="${state.drawerTab === v}" tabindex="${state.drawerTab === v ? "0" : "-1"}" data-drawer-tab="${v}">${l}</button>`,
    )
    .join("")}</div>`;
  const summary = `<div class="status-row" style="padding:12px 0"><span>Model probability</span>${r.model_risk_probability === null ? badge("Unavailable") : badge(`${(r.model_risk_probability * 100).toFixed(3)}%`, "green")}</div><div class="view-note">${r.evidence.length} evidence items · ${r.tool_calls} tool calls · ${r.latency_ms.toFixed(1)} ms reported workflow time<br>${esc(r.investigation_id)} · ${esc(dateTime(r.created_at))}</div>`;
  let content =
    state.drawerTab === "evidence"
      ? renderEvidence(r)
      : state.drawerTab === "trace"
        ? renderTrace(d.trace)
        : renderHistory(d.history);
  $("drawer-body").innerHTML =
    top +
    summary +
    tabs +
    `<div role="tabpanel" id="panel-${state.drawerTab}" aria-labelledby="tab-${state.drawerTab}">${content}</div>` +
    `<div class="button-row" style="justify-content:space-between;margin:20px 0"><button class="button small" data-action="export-case">${icon("download")}Export case JSON</button><button class="link-button" data-action="investigate">${icon("refresh")}Run a new investigation</button></div>` +
    renderReviewForm(r);
  hydrateIcons($("drawer-body"));
}
function renderEvidence(r) {
  const citations = r.cited_evidence_ids || [];
  const ai = r.narrative_summary
    ? `<div class="ai-summary"><h3>${icon("spark")} AI-assisted summary</h3><p>${esc(r.narrative_summary)}</p><div>${citations.map((id) => `<button class="source-id" data-evidence="${esc(id)}">${esc(id)}</button>`).join("")}</div><p>Generated narrative · inspect the cited evidence.</p></div>`
    : "";
  const shap = r.contributions?.length
    ? `<section class="drawer-section"><h3>${icon("chart")}Local model attribution</h3>${r.contributions
        .map((c) => {
          const max = Math.max(
            ...r.contributions.map((v) => Math.abs(v.contribution)),
            0.000001,
          );
          return `<div class="shap-row"><span class="shap-name">${esc(c.feature)}</span><span class="shap-track"><i class="${c.contribution < 0 ? "decreasing" : ""}" style="width:${(Math.abs(c.contribution) / max) * 100}%"></i></span><strong>${c.contribution >= 0 ? "+" : ""}${c.contribution.toFixed(4)}</strong></div>`;
        })
        .join(
          "",
        )}<p class="view-note">SHAP explains the underlying estimator on its model-output scale. Contributions do not add directly to the calibrated probability and are not causal evidence.</p></section>`
    : "";
  const list = (title, items, name) =>
    items?.length
      ? `<section class="drawer-section"><h3>${icon(name)}${title}</h3><ul class="bullet-list">${items.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></section>`
      : "";
  return (
    ai +
    `<div class="recommendation"><h3>Recommendation · ${esc(label(r.recommended_action))}</h3><p>${esc(r.rationale)}</p></div><section class="drawer-section"><h3>${icon("layers")}Retrieved evidence</h3>${r.evidence
      .map(
        (e) =>
          `<details class="evidence-item" id="evidence-${esc(e.evidence_id)}"><summary><span class="evidence-id">${esc(e.evidence_id)}</span><span class="evidence-statement">${esc(e.statement)}</span><span data-icon="down"></span></summary><div class="evidence-source">Tool: <code>${esc(e.tool)}</code><br>${
            e.source_transaction_ids.length
              ? `${e.source_transaction_ids.length} source transactions<br>${e.source_transaction_ids
                  .slice(0, 30)
                  .map(
                    (id) =>
                      `<button class="source-id" data-source="${esc(id)}">${esc(id)}</button>`,
                  )
                  .join(
                    "",
                  )}${e.source_transaction_ids.length > 30 ? "<br>First 30 shown. Export the case for all references." : ""}`
              : "No prior source transactions were retrieved for this item."
          }<div class="source-record" aria-live="polite"></div></div></details>`,
      )
      .join("")}</section>` +
    shap +
    list("Supporting indicators", r.supporting_indicators, "pulse") +
    list("Counter-evidence", r.counter_evidence, "shield") +
    list("Missing information", r.missing_information, "search") +
    list("Unresolved uncertainties", r.unresolved_uncertainties, "info")
  );
}
function renderTrace(events) {
  if (events === null)
    return '<div class="drawer-loading"><p class="prose">Retrieving recorded execution events…</p><div class="skeleton"></div></div>';
  if (events.error)
    return empty(
      "Trace could not be loaded",
      events.error,
      `<button class="button" data-action="retry-detail">Try again</button>`,
    );
  if (!events.length)
    return empty(
      "No trace events recorded",
      "This investigation has no recorded workflow activity.",
    );
  return `<section class="drawer-section"><h3>${icon("pulse")}Recorded execution · ${events.length} events</h3><p class="view-note" style="margin-bottom:20px">Actual persisted events. Tool invocation entries are written after orchestration; this is not a live agent animation.</p>${events.map((e) => `<div class="trace-item"><span class="trace-node">${icon(e.details.success === false || e.event_type === "llm_fallback" ? "info" : e.event_type === "human_review_recorded" ? "briefcase" : "check")}</span><div><strong>${esc(label(e.details.stage || e.details.tool || e.event_type))}</strong><p>${esc(e.event_type === "human_review_recorded" ? `${label(e.details.decision)}${e.details.analyst_note ? " · " + e.details.analyst_note : ""}` : e.details.duration_ms !== undefined ? `${e.details.duration_ms.toFixed(2)} ms · ${e.details.success === false ? "failed" : e.details.status || "completed"}` : e.details.error_type || e.details.status || label(e.event_type))}</p><time>${esc(dateTime(e.created_at))}</time><details><summary>Event details</summary><pre>${esc(JSON.stringify(e.details, null, 2))}</pre></details></div></div>`).join("")}</section>`;
}
function renderHistory(history) {
  if (history === null)
    return '<div class="drawer-loading"><p class="prose">Retrieving prior account activity…</p><div class="skeleton"></div></div>';
  if (history.error)
    return empty(
      "Account activity could not be loaded",
      history.error,
      `<button class="button" data-action="retry-detail">Try again</button>`,
    );
  if (!history.items.length)
    return empty(
      "No prior observed history",
      "No earlier transactions were found for this sender or receiver. Missing history is not evidence of low risk.",
    );
  return `<section class="drawer-section"><h3>${icon("clock")}Prior account activity</h3><p class="view-note" style="margin-bottom:16px">${history.items.length} of ${history.total} earlier sender or receiver records. Only events before the selected transaction are included.</p>${history.items.map((t) => `<div class="activity-item"><span class="event-icon">${icon("arrows")}</span><div><strong>${esc(t.sender_id)} to ${esc(t.receiver_id)}</strong><p>${esc(t.transaction_id)}<br>${money(t.amount, t.payment_currency)}</p></div><time>${esc(timeOnly(t.timestamp))}</time></div>`).join("")}</section>`;
}
function renderReviewForm(r) {
  const draft = reviewDrafts.get(r.investigation_id) || {
    decision: r.review_decision || "escalated",
    note: r.analyst_note || "",
  };
  return `<form id="review-form" class="review-form"><h3>Analyst disposition</h3>${r.review_decision ? `<div class="review-saved">${esc(label(r.review_decision))} · ${esc(dateTime(r.reviewed_at || r.created_at))}${r.analyst_note ? `<br>${esc(r.analyst_note)}` : ""}</div>` : ""}<div class="form-grid"><label class="field full">Decision<select name="decision">${[
    ["escalated", "Escalate for investigation"],
    ["dismissed", "Dismiss this case"],
    ["accepted", "Accept the recommendation"],
  ]
    .map(
      ([v, l]) =>
        `<option value="${v}" ${draft.decision === v ? "selected" : ""}>${l}</option>`,
    )
    .join(
      "",
    )}</select></label><label class="field full">Analyst note<textarea name="analyst_note" maxlength="1000" placeholder="Explain your decision and any follow-up needed…">${esc(draft.note)}</textarea><small>Your note and decision are saved together in the case history.</small></label></div><div class="button-row"><span class="view-note">${r.review_history?.length || 0} recorded reviews</span><button type="submit" class="button primary">${icon("check")}Save review</button></div></form>`;
}
async function loadDrawerDetail() {
  const d = state.drawer;
  if (!d?.report) return;
  const tab = state.drawerTab,
    token = state.drawerRequest;
  try {
    if (tab === "trace") {
      const result = await api(
        `/api/v1/investigations/${encodeURIComponent(d.report.investigation_id)}/trace`,
      );
      if (token !== state.drawerRequest) return;
      d.trace = result.events;
    } else if (tab === "activity") {
      const result = await api(
        `/api/v1/transactions/${encodeURIComponent(d.tx.transaction_id)}/history?limit=50`,
      );
      if (token !== state.drawerRequest) return;
      d.history = result;
    }
  } catch (error) {
    if (token !== state.drawerRequest) return;
    d[tab === "trace" ? "trace" : "history"] = { error: error.message };
  }
  if (token === state.drawerRequest && tab === state.drawerTab) renderDrawer();
}
function saveReviewDraft() {
  const form = $("review-form");
  if (form && state.drawer?.report) {
    const data = new FormData(form);
    reviewDrafts.set(state.drawer.report.investigation_id, {
      decision: data.get("decision"),
      note: data.get("analyst_note"),
    });
  }
}
async function runInvestigation() {
  const d = state.drawer;
  if (!d) return;
  saveReviewDraft();
  const token = state.drawerRequest;
  $("drawer-body").innerHTML =
    drawerMetadata(d.tx) +
    '<div class="drawer-loading"><p class="prose">Gathering time-bounded evidence and validating the report…</p><div class="skeleton"></div><div class="skeleton"></div></div>';
  try {
    const report = await post("/api/v1/investigations", {
      transaction_id: d.tx.transaction_id,
    });
    if (token === state.drawerRequest) {
      d.report = report;
      d.trace = null;
      d.history = null;
      d.tx.case_status = "open";
      d.tx.review_decision = null;
      state.drawerTab = "evidence";
      renderDrawer();
    }
    await refresh();
    toast("Investigation saved. Evidence is ready for review.");
  } catch (error) {
    if (token !== state.drawerRequest) return;
    renderDrawer();
    toast(`Investigation failed: ${error.message}`, true);
  }
}
async function saveReview(event) {
  event.preventDefault();
  const d = state.drawer;
  if (!d?.report) return;
  saveReviewDraft();
  const draft = reviewDrafts.get(d.report.investigation_id),
    token = state.drawerRequest,
    button = event.target.querySelector("[type=submit]");
  button.disabled = true;
  button.textContent = "Saving review…";
  try {
    const report = await post(
      `/api/v1/cases/${encodeURIComponent(d.report.investigation_id)}/review`,
      { decision: draft.decision, analyst_note: draft.note },
    );
    reviewDrafts.delete(report.investigation_id);
    if (token === state.drawerRequest) {
      d.report = report;
      d.trace = null;
      d.tx.case_status = "reviewed";
      d.tx.review_decision = report.review_decision;
      renderDrawer();
      if (state.drawerTab === "trace") await loadDrawerDetail();
    }
    await refresh();
    toast("Decision and analyst note saved.");
  } catch (error) {
    toast(error.message, true);
    if (token === state.drawerRequest) {
      button.disabled = false;
      button.innerHTML = icon("check") + "Save review";
    }
  }
}
function savePolicyDraft() {
  const form = $("policy-form");
  if (form) state.policyDraft = Object.fromEntries(new FormData(form));
}
async function submitPolicy(event) {
  event.preventDefault();
  savePolicyDraft();
  const draft = state.policyDraft,
    probabilities = draft.probabilities
      .split(/[\s,;]+/)
      .filter(Boolean)
      .map(Number);
  if (
    !probabilities.length ||
    probabilities.length > 10000 ||
    probabilities.some((v) => !Number.isFinite(v) || v < 0 || v > 1)
  ) {
    toast("Enter between 1 and 10,000 probabilities from 0 to 1.", true);
    return;
  }
  const button = event.target.querySelector("[type=submit]");
  button.disabled = true;
  button.textContent = "Calculating…";
  try {
    state.policyResult = await post("/api/v1/policies/simulate", {
      probabilities,
      alert_budget: Number(draft.alert_budget),
      missed_fraud_cost: Number(draft.missed_fraud_cost),
      false_positive_cost: Number(draft.false_positive_cost),
      manual_review_cost: Number(draft.manual_review_cost),
    });
    if (state.page === "policy") {
      $("policy-result").innerHTML = renderPolicyResult();
      hydrateIcons($("policy-result"));
    }
    toast("Hypothetical policy comparison calculated.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.innerHTML = icon("sliders") + "Compare policy costs";
  }
}
async function stopStream({ silent = false } = {}) {
  clearTimeout(state.streamTimer);
  state.streamTimer = null;
  try {
    await post("/api/v1/simulation/pause");
    state.simulation.running = false;
  } catch (error) {
    if (!silent) toast(error.message, true);
  }
  if (state.meta) renderPage();
}
async function streamTick() {
  if (!state.streamTimer) return;
  try {
    await post("/api/v1/simulation/step?count=2");
    await refresh();
    if (state.streamTimer) state.streamTimer = setTimeout(streamTick, 6000);
  } catch (error) {
    await stopStream({ silent: true });
    toast(`Stream paused: ${error.message}`, true);
  }
}
async function toggleStream() {
  if (state.streamTimer) {
    await stopStream();
    toast("Simulation paused.");
    return;
  }
  try {
    await post("/api/v1/simulation/start");
    state.simulation.running = true;
    state.streamTimer = setTimeout(streamTick, 6000);
    renderPage();
    toast("Synthetic stream started. Two events arrive every six seconds.");
  } catch (error) {
    toast(error.message, true);
  }
}
let resetScenario = "burst";
function requestReset() {
  resetScenario = $("scenario-select")?.value || state.simulation.scenario;
  $("confirm-dialog").showModal();
}
async function resetDemo() {
  const button = $("confirm-reset");
  button.disabled = true;
  button.textContent = "Resetting…";
  try {
    await stopStream({ silent: true });
    await post(
      `/api/v1/simulation/reset?scenario=${encodeURIComponent(resetScenario)}&count=36`,
    );
    state.tablePage = 1;
    state.policyResult = null;
    state.policyDraft = null;
    reviewDrafts.clear();
    $("confirm-dialog").close();
    await refresh();
    toast("Demo reset with 36 reproducible synthetic transactions.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Reset demo";
  }
}
function filterRender() {
  state.tablePage = 1;
  renderPage();
}
let inputDebounce;
document.addEventListener("input", (event) => {
  if (event.target.id === "transaction-search") {
    state.query = event.target.value;
    clearTimeout(inputDebounce);
    inputDebounce = setTimeout(filterRender, 180);
  }
  if (event.target.id === "case-search") {
    state.caseQuery = event.target.value;
    state.casePage = 1;
    clearTimeout(inputDebounce);
    inputDebounce = setTimeout(renderPage, 180);
  }
  if (event.target.closest("#review-form")) saveReviewDraft();
  if (event.target.closest("#policy-form")) savePolicyDraft();
});
document.addEventListener("change", (event) => {
  const id = event.target.id;
  if (id === "filter-status") {
    state.status = event.target.value;
    filterRender();
  }
  if (id === "filter-currency") {
    state.currency = event.target.value;
    filterRender();
  }
  if (id === "filter-payment") {
    state.payment = event.target.value;
    filterRender();
  }
  if (id === "chart-currency") {
    state.chartCurrency = event.target.value;
    renderPage();
  }
  if (id === "case-filter") {
    state.caseStatus = event.target.value;
    state.casePage = 1;
    renderPage();
  }
  if (event.target.closest("#review-form")) saveReviewDraft();
});
document.addEventListener("click", async (event) => {
  const target = event.target.closest("button,a");
  if (!target) return;
  if (target.dataset.nav) {
    navigate(target.dataset.nav);
    return;
  }
  if (target.dataset.transaction) {
    await openTransaction(target.dataset.transaction);
    return;
  }
  if (target.dataset.case) {
    await openCase(target.dataset.case);
    return;
  }
  if (target.dataset.retryTransaction) {
    await openTransaction(target.dataset.retryTransaction);
    return;
  }
  if (target.dataset.sort) {
    if (state.sort === target.dataset.sort) state.direction *= -1;
    else {
      state.sort = target.dataset.sort;
      state.direction = -1;
    }
    renderPage();
    return;
  }
  if (target.dataset.tablePage) {
    state.tablePage += Number(target.dataset.tablePage);
    renderPage();
    return;
  }
  if (target.dataset.casePage) {
    state.casePage += Number(target.dataset.casePage);
    renderPage();
    return;
  }
  if (target.dataset.drawerTab) {
    saveReviewDraft();
    state.drawerTab = target.dataset.drawerTab;
    renderDrawer();
    $(`tab-${state.drawerTab}`)?.focus();
    if (state.drawerTab !== "evidence") await loadDrawerDetail();
    return;
  }
  if (target.dataset.evidence) {
    const evidence = $(`evidence-${target.dataset.evidence}`);
    if (evidence) {
      evidence.open = true;
      evidence.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    return;
  }
  if (target.dataset.source) {
    const container = target
      .closest(".evidence-source")
      .querySelector(".source-record");
    container.textContent = "Retrieving source transaction…";
    try {
      const tx = await api(
        `/api/v1/transactions/${encodeURIComponent(target.dataset.source)}`,
      );
      container.innerHTML = `<div class="assumption"><strong>${esc(tx.transaction_id)}</strong><br>${esc(tx.sender_id)} to ${esc(tx.receiver_id)}<br>${money(tx.amount, tx.payment_currency)} · ${esc(dateTime(tx.timestamp))}</div>`;
    } catch (error) {
      container.textContent = error.message;
    }
    return;
  }
  if (target.id === "use-scores") {
    const values = state.transactions
      .filter(
        (t) =>
          t.model_probability !== null && t.model_probability !== undefined,
      )
      .map((t) => t.model_probability);
    $("policy-form").elements.probabilities.value = values.join(", ");
    savePolicyDraft();
    toast(`Loaded ${values.length} stored probabilities.`);
    return;
  }
  const action = target.dataset.action;
  if (action === "refresh")
    await refresh({ initial: !state.meta, notify: true });
  if (action === "export") exportCsv();
  if (action === "clear-filters") {
    state.query = "";
    state.currency = "all";
    state.status = "all";
    state.payment = "all";
    filterRender();
  }
  if (action === "seed") {
    target.disabled = true;
    try {
      await post("/api/v1/simulation/reset?scenario=burst&count=36");
      await refresh();
      toast("Loaded 36 synthetic transactions.");
    } catch (error) {
      toast(error.message, true);
      if (target.isConnected) target.disabled = false;
    }
  }
  if (action === "reset") requestReset();
  if (action === "stream") {
    target.disabled = true;
    try {
      await toggleStream();
    } finally {
      if (target.isConnected) target.disabled = false;
    }
  }
  if (action === "investigate") await runInvestigation();
  if (action === "export-case" && state.drawer?.report)
    downloadFile(
      `risklens-${state.drawer.report.investigation_id}.json`,
      JSON.stringify(state.drawer.report, null, 2),
      "application/json",
    );
  if (action === "retry-detail") await loadDrawerDetail();
});
document.addEventListener("submit", (event) => {
  if (event.target.id === "review-form") saveReview(event);
  if (event.target.id === "policy-form") submitPolicy(event);
});
$("refresh").addEventListener("click", () =>
  refresh({ initial: !state.meta, notify: true }),
);
$("global-search").addEventListener("click", () => {
  navigate("transactions");
  $("transaction-search").focus();
});
$("close-drawer").addEventListener("click", () => {
  saveReviewDraft();
  $("investigation-drawer").close();
});
$("investigation-drawer").addEventListener("cancel", saveReviewDraft);
$("investigation-drawer").addEventListener("close", () => {
  state.drawerRequest++;
  state.drawer = null;
});
$("investigation-drawer").addEventListener("click", (event) => {
  if (event.target === $("investigation-drawer")) {
    const r = event.target.getBoundingClientRect();
    if (event.clientX < r.left) {
      saveReviewDraft();
      event.target.close();
    }
  }
});
$("cancel-reset").addEventListener("click", () => $("confirm-dialog").close());
$("confirm-reset").addEventListener("click", resetDemo);
$("menu-toggle").addEventListener("click", () => {
  const open = $("sidebar").classList.toggle("visible");
  $("menu-toggle").setAttribute("aria-expanded", String(open));
});
document.addEventListener("click", (event) => {
  if (
    window.innerWidth <= 760 &&
    !event.target.closest("#sidebar,#menu-toggle")
  ) {
    $("sidebar").classList.remove("visible");
    $("menu-toggle").setAttribute("aria-expanded", "false");
  }
});
document.addEventListener("keydown", (event) => {
  if (
    event.key === "/" &&
    !event.metaKey &&
    !event.ctrlKey &&
    !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) &&
    !$("investigation-drawer").open &&
    !$("confirm-dialog").open
  ) {
    event.preventDefault();
    navigate("transactions");
    $("transaction-search").focus();
  }
  if (
    event.target.matches("[role=tab]") &&
    ["ArrowLeft", "ArrowRight"].includes(event.key)
  ) {
    event.preventDefault();
    const tabs = ["evidence", "activity", "trace"],
      next =
        (tabs.indexOf(state.drawerTab) + (event.key === "ArrowRight" ? 1 : 2)) %
        3;
    $(`tab-${tabs[next]}`).click();
  }
});
window.addEventListener("hashchange", () => {
  const destination = location.hash.slice(1);
  if (pageNames[destination]) navigate(destination);
  else if (destination === "main") $("main").focus();
});
window.addEventListener("pagehide", () => {
  if (state.streamTimer) {
    clearTimeout(state.streamTimer);
    state.streamTimer = null;
  }
});
async function init() {
  hydrateIcons();
  state.page = pageNames[location.hash.slice(1)]
    ? location.hash.slice(1)
    : "overview";
  await refresh({ initial: true });
}
init();
