// Draws dashboard tiles and charts from /api/dashboard/summary (plain HTML, no chart library).
function tile(label, value, note) {
  const d = document.createElement("div");
  d.className = "tile";
  d.innerHTML = `<div class="tile-label"></div><div class="tile-value"></div><div class="tile-note"></div>`;
  d.querySelector(".tile-label").textContent = label;
  d.querySelector(".tile-value").textContent = value;
  d.querySelector(".tile-note").textContent = note || "";
  return d;
}

// Horizontal bars: one per risk level, always labelled with name, count and percentage.
function riskBars(container, byLevel) {
  const total = Object.values(byLevel).reduce((a, b) => a + b, 0);
  container.innerHTML = "";
  for (const level of ["LOW", "MODERATE", "HIGH"]) {
    const n = byLevel[level] || 0, pct = total ? Math.round((n / total) * 100) : 0;
    const row = document.createElement("div");
    row.className = "hbar-row";
    row.innerHTML = `<span class="hbar-label"></span><span class="hbar-track"><span class="hbar-fill ${level}"></span></span><span class="hbar-value"></span>`;
    row.querySelector(".hbar-label").textContent = level.charAt(0) + level.slice(1).toLowerCase();
    row.querySelector(".hbar-fill").style.width = `${total ? Math.max(pct, n ? 2 : 0) : 0}%`;
    row.querySelector(".hbar-value").textContent = `${n} (${pct}%)`;
    row.title = `${level}: ${n} assessment${n === 1 ? "" : "s"} (${pct}%)`;
    container.appendChild(row);
  }
}

// Columns: assessments per day; hover shows the exact date and count.
function dailyColumns(container, perDay) {
  const max = Math.max(1, ...perDay.map(d => d.count));
  container.innerHTML = "";
  const chart = document.createElement("div");
  chart.className = "cols";
  for (const d of perDay) {
    const col = document.createElement("div");
    col.className = "col";
    const date = new Date(d.date + "T00:00:00");
    const label = date.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
    col.dataset.tip = `${label}: ${d.count} assessment${d.count === 1 ? "" : "s"}`;
    col.innerHTML = `<span class="col-bar"></span><span class="col-x"></span>`;
    col.querySelector(".col-bar").style.height = `${(d.count / max) * 100}%`;
    col.querySelector(".col-x").textContent = date.getDate();
    chart.appendChild(col);
  }
  const axis = document.createElement("div");
  axis.className = "muted";
  axis.style.fontSize = ".8rem";
  axis.textContent = `Last 14 days · highest day: ${max === 1 && !perDay.some(d => d.count) ? 0 : max}`;
  container.append(chart, axis);
}
