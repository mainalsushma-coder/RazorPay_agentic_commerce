const $ = (selector) => document.querySelector(selector);

const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
})[char]);

async function getJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

function formatMoney(total, currency = "INR") {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 2 }).format(Number(total));
}

async function loadCatalog() {
  const grid = $("#product-grid");
  try {
    const products = await getJson("/products");
    $("#product-count").textContent = `${products.length} products`;
    grid.innerHTML = products.map((product) => `
      <section class="product-card">
        <div class="product-top">
          <div><h3>${escapeHtml(product.name)}</h3><span class="category">${escapeHtml(product.category)}</span></div>
          <span class="price">${escapeHtml(formatMoney(product.price, product.currency))}</span>
        </div>
        <div class="product-meta"><span>SKU · ${escapeHtml(product.sku)}</span><span class="${Number(product.stock) < 10 ? "stock-low" : "stock-ok"}">${escapeHtml(product.stock)} in stock</span></div>
      </section>`).join("");
  } catch (error) {
    grid.innerHTML = `<p class="loading error">Catalog unavailable. ${escapeHtml(error.message)}</p>`;
  }
}

function updateScore(selector, progressSelector, value) {
  $(selector).textContent = `${Number(value).toFixed(1)}%`;
  $(progressSelector).style.width = `${Math.min(100, Math.max(0, Number(value)))}%`;
}

async function loadReadiness() {
  try {
    const report = await getJson("/merchant/readiness");
    updateScore("#original-score", "#original-progress", report.readiness_score);
    $("#issue-count").textContent = report.issue_count;
  } catch (error) {
    $("#original-score").textContent = "Error";
  }
}

async function loadRepairPreview(showDetails = false) {
  const button = $("#repair-button");
  const details = $("#repair-details");
  button.disabled = true;
  button.textContent = "Scanning catalog…";
  try {
    const preview = await getJson("/merchant/readiness/repair-preview");
    updateScore("#autopilot-score", "#autopilot-progress", preview.after.readiness_score);
    $("#repair-count").textContent = preview.repairs.length;
    $("#unresolved-count").textContent = preview.unresolved_issues.length;
    if (showDetails) {
      details.hidden = false;
      details.innerHTML = `<p><b>${preview.repairs.length} safe repairs</b> applied in preview (no source data changed).</p>${preview.repairs.map((repair) => `<p>${escapeHtml(repair.sku)} · ${escapeHtml(repair.field)} — ${escapeHtml(repair.reason)}</p>`).join("")}<p><b>${preview.unresolved_issues.length} unresolved issues</b> require merchant input.</p>`;
    }
  } catch (error) {
    details.hidden = false;
    details.innerHTML = `<p class="error">Repair preview unavailable. ${escapeHtml(error.message)}</p>`;
  } finally {
    button.disabled = false;
    button.innerHTML = "Autopilot Repair Preview <span>↗</span>";
  }
}

async function loadAudit() {
  const body = $("#audit-body");
  body.innerHTML = '<tr><td colspan="6" class="loading">Loading decisions…</td></tr>';
  try {
    const entries = await getJson("/audit");
    if (!entries.length) {
      body.innerHTML = '<tr><td colspan="6" class="empty">No policy decisions yet. Audit events will appear here.</td></tr>';
      return;
    }
    body.innerHTML = [...entries].reverse().map((entry) => `
      <tr><td>${escapeHtml(new Date(entry.timestamp).toLocaleString())}</td><td>${escapeHtml(entry.sku)}</td><td>${escapeHtml(entry.quantity)}</td><td>${escapeHtml(formatMoney(entry.total))}</td><td><span class="decision decision-${escapeHtml(entry.decision)}">${escapeHtml(entry.decision.replaceAll("_", " "))}</span></td><td>${escapeHtml(entry.reason)}</td></tr>`).join("");
  } catch (error) {
    body.innerHTML = `<tr><td colspan="6" class="empty error">Audit trail unavailable. ${escapeHtml(error.message)}</td></tr>`;
  }
}

$("#agent-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("#agent-input");
  if (!input.value.trim()) return;
  $("#conversation").insertAdjacentHTML("beforeend", `<div class="message-user">${escapeHtml(input.value.trim())}</div>`);
  input.value = "";
});
$("#repair-button").addEventListener("click", () => loadRepairPreview(true));
$("#refresh-audit").addEventListener("click", loadAudit);

Promise.allSettled([loadCatalog(), loadReadiness(), loadRepairPreview(), loadAudit()]);
