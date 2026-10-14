const name = new URLSearchParams(location.search).get("name");
const state = document.getElementById("state");
const LOW = 0.8;

const SCALAR_LABELS = (k) => k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const isField = (v) => v && typeof v === "object" && !Array.isArray(v) && "value" in v;

function evidence(f) {
  if (!f || (!f.source_text && !f.page_number)) return h("span", { class: "muted" }, "—");
  return [f.page_number ? "p." + f.page_number : null, f.source_text].filter(Boolean).join(" · ");
}

function valueCell(v) {
  if (v === null || v === undefined) return chip("missing", "missing");
  if (typeof v === "number") return h("span", { class: v < 0 ? "neg" : "" }, fmtNum(v));
  return String(v);
}

function fieldsTable(data, keys) {
  const rows = keys.map((k) => {
    const f = data[k];
    const missing = f.value === null || f.value === undefined;
    const low = f.confidence !== null && f.confidence !== undefined && f.confidence < LOW;
    return h("tr", { class: missing ? "row-missing" : low ? "row-low" : "" },
      h("td", {}, SCALAR_LABELS(k)), h("td", {}, valueCell(f.value)),
      h("td", {}, missing ? "" : confCell(f.confidence)), h("td", { class: "evidence" }, evidence(f)));
  });
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ...["Field", "Value", "Confidence", "Evidence"].map((t) => h("th", {}, t)))),
    h("tbody", {}, rows)));
}

function simpleTable(headers, rows, numCols = []) {
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, headers.map((t, i) => h("th", { class: numCols.includes(i) ? "num" : "" }, t)))),
    h("tbody", {}, rows)));
}

function renderInvoice(data, root) {
  root.append(h("h2", {}, "Fields"));
  root.append(fieldsTable(data, Object.keys(data).filter((k) => isField(data[k]))));
  const items = data.line_items || [];
  root.append(h("h3", {}, `Line items (${items.length})`));
  if (!items.length) root.append(h("p", { class: "muted" }, "No line items were extracted."));
  else root.append(simpleTable(["#", "Description", "Qty", "Unit price", "Amount", "Tax", "Confidence"],
    items.map((li, i) => h("tr", { class: li.confidence != null && li.confidence < LOW ? "row-low" : "" },
      h("td", {}, i + 1), h("td", {}, li.description ?? ""), h("td", { class: "num" }, valueCell(li.quantity)),
      h("td", { class: "num" }, valueCell(li.unit_price)), h("td", { class: "num" }, valueCell(li.amount)),
      h("td", {}, li.tax_code ?? ""), h("td", {}, confCell(li.confidence)))), [2, 3, 4]));
  renderOther(data, root);
}

function renderOther(data, root) {
  const other = data.other_fields || [];
  if (!other.length) return;
  root.append(h("h3", {}, "Other fields"));
  root.append(simpleTable(["Key", "Value", "Evidence"],
    other.map((kv) => h("tr", {}, h("td", {}, SCALAR_LABELS(kv.key)), h("td", {}, kv.value ?? ""),
      h("td", { class: "evidence" }, evidence(kv))))));
}

function renderStatement(data, root) {
  const periods = data.periods || [];
  root.append(h("h2", {}, "Statement header"));
  root.append(h("div", { class: "kv-grid" }, ["entity_name", "statement_title", "currency", "unit"].map((k) =>
    h("div", { class: "kv" }, h("b", {}, SCALAR_LABELS(k)), valueCell(data[k] && data[k].value)))));
  root.append(h("div", { class: "kv" }, h("b", {}, "Periods"), periods.join("  |  ") || "—"));

  const figs = data.key_figures || {};
  root.append(h("h3", {}, "Key figures"));
  if (!Object.keys(figs).length) root.append(h("p", { class: "muted" }, "No key figures could be identified."));
  else root.append(simpleTable(["Figure", ...periods],
    Object.entries(figs).map(([k, byPeriod]) => h("tr", {}, h("td", {}, SCALAR_LABELS(k)),
      periods.map((p) => h("td", { class: "num" }, valueCell(byPeriod[p] ?? null))))), periods.map((_, i) => i + 1)));

  const items = data.line_items || [];
  root.append(h("h3", {}, `All line items (${items.length})`));
  root.append(simpleTable(["Line item", "Sched.", ...periods, "Confidence"],
    items.map((li) => {
      const unreadable = Object.entries(li.values || {}).some(([p, v]) =>
        v === null && li.raw_values && li.raw_values[p] && !/^[-–—\s]*$/.test(li.raw_values[p]));
      const low = li.confidence != null && li.confidence < LOW;
      return h("tr", { class: `r-${li.row_type} ${unreadable ? "row-missing" : low ? "row-low" : ""}`, title: li.canonical_key ? "key: " + li.canonical_key : null },
        h("td", {}, li.label), h("td", {}, li.schedule_ref ?? ""),
        periods.map((p) => h("td", { class: "num" }, li.row_type === "heading" ? "" : valueCell((li.values || {})[p] ?? null))),
        h("td", {}, li.row_type === "heading" ? "" : confCell(li.confidence)));
    }), periods.map((_, i) => i + 2)));
  renderOther(data, root);
}

function renderValidation(result, root) {
  const v = result.validation;
  if (!v) { root.append(h("p", { class: "muted" }, "No financial validation was run for this document.")); return; }
  root.append(h("h2", {}, "Financial validation ", chip(v.overall_status)));
  const rows = v.checks.map((c) => h("tr", { class: c.status === "FAIL" ? "row-fail" : "" },
    h("td", {}, c.name, c.period ? h("div", { class: "evidence" }, c.period) : null), h("td", {}, h("code", {}, c.formula)),
    h("td", { class: "evidence" }, Object.entries(c.operands || {}).map(([k, val]) =>
      `${k}: ${Array.isArray(val) ? "[" + val.join(", ") + "]" : val === null ? "missing" : fmtNum(val)}`).join(" · ")),
    h("td", { class: "num" }, c.calculated_value === null ? "—" : fmtNum(c.calculated_value)),
    h("td", { class: "num" }, c.reported_value === null ? "—" : fmtNum(c.reported_value)),
    h("td", { class: "num" }, c.variance === null ? "—" : fmtNum(c.variance)),
    h("td", {}, chip(c.status), c.note ? h("div", { class: "evidence" }, c.note) : null)));
  root.append(simpleTable(["Check", "Formula", "Operands", "Calculated", "Reported", "Variance", "Status"], rows, [3, 4, 5]));
  root.append(h("p", { class: "muted" }, "A check passes when |calculated − reported| is within the configured tolerance; checks whose inputs are not in the document are NOT_APPLICABLE (nothing is assumed)."));
}

function renderJson(result, root) {
  const text = JSON.stringify(result, null, 2);
  root.append(h("div", { class: "json-actions" },
    h("button", { class: "btn", onclick: async (e) => {
      try { await navigator.clipboard.writeText(text); e.target.textContent = "Copied"; } catch { e.target.textContent = "Copy failed"; }
      setTimeout(() => (e.target.textContent = "Copy JSON"), 1500);
    } }, "Copy JSON"),
    h("a", { class: "btn", download: (result.document_name || "result") + ".json",
      href: URL.createObjectURL(new Blob([text], { type: "application/json" })) }, "Download JSON")));
  root.append(h("pre", {}, text));
}

function renderSummary(r) {
  const m = r.processing_metadata || {}, fv = r.file_validation || {};
  const kv = (k, v) => h("div", { class: "kv" }, h("b", {}, k), v);
  document.getElementById("summary").append(
    h("div", { class: "row-between" }, h("h2", {}, r.document_name), chip(r.processing_status)),
    h("div", { class: "kv-grid" },
      kv("Type", TYPE_LABELS[r.document_type] || r.document_type),
      kv("Overall confidence", confCell(r.overall_confidence)),
      kv("File", `${fv.file_type || "—"} · ${fv.page_count ?? "?"} page(s) · ${fv.status || "—"}`),
      kv("OCR cross-check", m.ocr_used ? "Tesseract (scanned/image)" : m.ocr_engine === "pdf-text-layer" ? "PDF text layer" : "Not available"),
      kv("Model", m.model || "—"),
      kv("Processed", m.processed_at ? fmtDate(m.processed_at) : "—"),
      kv("Time", m.processing_time_ms != null ? (m.processing_time_ms / 1000).toFixed(1) + " s" : "—")));
}

function renderBanners(r) {
  const box = document.getElementById("banners"), v = r.validation;
  if (r.error) box.append(h("div", { class: "banner error" }, `${r.error.code}: ${r.error.message}`));
  if (v && v.issues.length) box.append(h("div", { class: "banner error" }, h("b", {}, "Failed validations: "), v.issues.join(" • ")));
  if (v && v.missing_required_fields.length) box.append(h("div", { class: "banner warn" }, h("b", {}, "Missing fields: "), v.missing_required_fields.join(", ")));
  if (v && v.low_confidence_fields.length) box.append(h("div", { class: "banner warn" }, h("b", {}, "Low-confidence (not corroborated by OCR): "), v.low_confidence_fields.join(", ")));
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    for (const id of ["data", "validation", "json"]) document.getElementById("tab-" + id).hidden = id !== btn.dataset.tab;
  }));
}

(async function init() {
  if (!name) { state.textContent = "No document specified."; return; }
  try {
    const r = await apiJson(`${API}/documents/${encodeURIComponent(name)}`);
    state.hidden = true; document.getElementById("result").hidden = false;
    renderSummary(r); renderBanners(r); setupTabs();
    const dataRoot = document.getElementById("tab-data");
    if (r.extracted_data) (r.extracted_data.periods ? renderStatement : renderInvoice)(r.extracted_data, dataRoot);
    else dataRoot.append(h("p", { class: "muted" }, "No data was extracted for this document."));
    renderValidation(r, document.getElementById("tab-validation"));
    renderJson(r, document.getElementById("tab-json"));
    document.title = r.document_name + " · Document Intelligence";
  } catch (e) {
    state.className = "msg error"; state.textContent = e.message;
  }
})();
