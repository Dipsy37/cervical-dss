// Shared helpers used by every page: API calls, session, navigation.
const Session = {
  save(d) {
    sessionStorage.setItem("token", d.access_token);
    sessionStorage.setItem("role", d.role);
    sessionStorage.setItem("name", d.full_name);
    sessionStorage.setItem("mustChange", d.must_change_password ? "1" : "0");
  },
  get token() { return sessionStorage.getItem("token"); },
  get role() { return sessionStorage.getItem("role"); },
  get name() { return sessionStorage.getItem("name") || ""; },
  get mustChange() { return sessionStorage.getItem("mustChange") === "1"; },
  set mustChange(v) { sessionStorage.setItem("mustChange", v ? "1" : "0"); },
  clear() { sessionStorage.clear(); },
};

function errorText(data, status) {
  if (!data || !data.detail) return `Request failed (${status}).`;
  if (typeof data.detail === "string") return data.detail;
  // Pydantic validation errors: list of {loc, msg}
  return data.detail.map(e => {
    const field = (e.loc || []).filter(x => x !== "body").join(" ").replaceAll("_", " ");
    const msg = (e.msg || "").replace(/^Value error, /, "");
    return field ? `${field}: ${msg}` : msg;
  }).join("\n");
}

async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  if (Session.token) headers.Authorization = `Bearer ${Session.token}`;
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new Error("Cannot reach the server. Check your internet connection and try again.");
  }
  if (res.status === 401 && !path.endsWith("/login")) {
    Session.clear();
    location.href = "index.html?expired=1";
    throw new Error("Session expired.");
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorText(data, res.status));
  return data;
}

// Page guard: send the user to the right place if not allowed here.
function requireLogin(role) {
  if (!Session.token) { location.href = "index.html"; return false; }
  if (Session.mustChange) { location.href = "change-password.html"; return false; }
  if (role && Session.role !== role) { location.href = homeFor(Session.role); return false; }
  return true;
}
function homeFor(role) { return role === "ADMIN" ? "dashboard.html" : "chw.html"; }

function renderNav(active) {
  const links = Session.role === "ADMIN"
    ? [["dashboard.html", "Dashboard"], ["admin.html", "CHW Accounts"], ["admin-assessments.html", "All Assessments"]]
    : [["chw.html", "Dashboard"], ["assess.html", "New Assessment"], ["history.html", "Assessment History"]];
  links.push(["change-password.html", "Change Password"]);
  const bar = document.createElement("header");
  bar.className = "topbar";
  bar.innerHTML = `<div class="inner"><span class="title">Cervical Cancer Risk Assessment</span><nav></nav></div>`;
  const nav = bar.querySelector("nav");
  for (const [href, text] of links) {
    const a = document.createElement("a");
    a.href = href; a.textContent = text;
    if (href === active) a.className = "active";
    nav.appendChild(a);
  }
  const out = document.createElement("a");
  out.href = "#"; out.textContent = "Log Out";
  out.onclick = (e) => { e.preventDefault(); Session.clear(); location.href = "index.html"; };
  nav.appendChild(out);
  document.body.prepend(bar);
}

function showMessage(el, text, kind = "error") {
  el.className = `alert ${kind}`;
  el.textContent = text;
  el.classList.remove("hidden");
}

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB") + " " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function badge(level) {
  const s = document.createElement("span");
  s.className = `badge ${level}`;
  s.textContent = level;
  return s;
}

// Build a table body row safely (text only, never raw HTML from the server)
function cell(content) {
  const td = document.createElement("td");
  if (content instanceof Node) td.appendChild(content); else td.textContent = content ?? "";
  return td;
}

// "Mary Wanjiru (CL-00042)", or just "CL-00042" when no name was recorded.
// The server decides whether the name is shown in full or as initials.
function clientLabel(r) {
  return r.client_name ? `${r.client_name} (${r.client_code})` : r.client_code;
}
