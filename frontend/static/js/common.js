/* Shared helpers. DOM is built with textContent (never innerHTML) so document text cannot inject markup. */
const API = "/api/v1";

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const TYPE_LABELS = {
  invoice: "Invoice", balance_sheet: "Balance Sheet",
  profit_and_loss: "Profit & Loss", cash_flow_statement: "Cash Flow Statement",
};

function chip(text, cls) { return h("span", { class: "chip " + (cls || text) }, text); }

function fmtNum(v) {
  if (typeof v !== "number") return v;
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function fmtDate(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString();
}

function confCell(c) {
  if (c === null || c === undefined) return h("span", { class: "muted" }, "—");
  const pct = Math.round(c * 100) + "%";
  return c < 0.8 ? chip(pct + " low", "low") : pct;
}

async function apiJson(url, options) {
  let res;
  try { res = await fetch(url, options); }
  catch (e) { throw new Error("Could not reach the server. Please try again."); }
  let body = null;
  try { body = await res.json(); } catch (e) { /* non-JSON error body */ }
  if (!res.ok) {
    const err = new Error((body && body.error && body.error.message) || `Request failed (${res.status})`);
    err.code = body && body.error && body.error.code;
    throw err;
  }
  return body;
}
