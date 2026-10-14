const body = document.getElementById("docs-body");
const msg = document.getElementById("upload-msg");

function showMsg(text, cls) {
  msg.hidden = false; msg.className = "msg " + cls; msg.textContent = text;
}

async function loadDocs() {
  const params = new URLSearchParams();
  const q = document.getElementById("q").value.trim();
  const t = document.getElementById("f-type").value;
  const s = document.getElementById("f-status").value;
  if (q) params.set("q", q);
  if (t) params.set("document_type", t);
  if (s) params.set("status", s);
  try {
    const data = await apiJson(`${API}/documents?${params}`);
    document.getElementById("total").textContent = `(${data.total})`;
    body.replaceChildren();
    if (!data.items.length) {
      body.append(h("tr", {}, h("td", { colspan: 6, class: "muted" }, "No documents yet. Upload one above.")));
      return;
    }
    for (const d of data.items) {
      const open = () => { location.href = "/view?name=" + encodeURIComponent(d.document_name); };
      body.append(h("tr", { class: "clickable", tabindex: 0, onclick: open, onkeydown: (e) => e.key === "Enter" && open() },
        h("td", {}, h("a", { href: "/view?name=" + encodeURIComponent(d.document_name) }, d.document_name)),
        h("td", {}, TYPE_LABELS[d.document_type] || d.document_type),
        h("td", {}, chip(d.processing_status)),
        h("td", {}, d.validation_status ? chip(d.validation_status) : h("span", { class: "muted" }, "—")),
        h("td", {}, confCell(d.overall_confidence)),
        h("td", {}, fmtDate(d.processed_at))));
    }
  } catch (e) {
    body.replaceChildren(h("tr", {}, h("td", { colspan: 6, class: "msg error" }, e.message)));
  }
}

document.getElementById("upload-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const file = document.getElementById("file").files[0];
  if (!file) return showMsg("Please choose a file.", "error");
  const fd = new FormData();
  fd.append("file", file);
  fd.append("document_type", document.getElementById("doc-type").value);
  const btn = document.getElementById("process-btn");
  btn.disabled = true; btn.textContent = "Processing…";
  showMsg("Processing — extraction can take 10–40 seconds…", "");
  try {
    const result = await apiJson(`${API}/documents/process`, { method: "POST", body: fd });
    location.href = "/view?name=" + encodeURIComponent(result.document_name);
  } catch (e) {
    showMsg(`${e.code ? e.code + ": " : ""}${e.message}`, "error");
    loadDocs();  // failed attempts are recorded too
  } finally {
    btn.disabled = false; btn.textContent = "Process";
  }
});

let timer;
document.getElementById("q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(loadDocs, 250); });
document.getElementById("f-type").addEventListener("change", loadDocs);
document.getElementById("f-status").addEventListener("change", loadDocs);
loadDocs();
