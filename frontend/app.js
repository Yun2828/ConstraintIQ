// ─── Backend URL ─────────────────────────────────────────────────────────────
// Resolved from config.js (window.CONSTRAINT_IQ_CONFIG.backendUrl).
// Falls back to localhost for local development.
function getBackendUrl() {
  return (
    (window.CONSTRAINT_IQ_CONFIG && window.CONSTRAINT_IQ_CONFIG.backendUrl) ||
    "http://localhost:8000"
  );
}

// ─── State ────────────────────────────────────────────────────────────────────
let activeIssueId         = null;
let analysisRun           = false;
let uploadedFileName      = null;
let uploadedFile          = null;   // the actual File object for API upload
let activePage            = "landing"; // "landing" | "dashboard"
let activeProjectFilename = null;
let lastReport            = null;   // last JSON report from the API

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const fileInput          = document.getElementById("fileInput");
const uploadBtn          = document.getElementById("uploadBtn");
const heroUploadBtn      = document.getElementById("heroUploadBtn");
const analyzeBtn         = document.getElementById("analyzeBtn");
const navBrand           = document.getElementById("navBrand");
const backBtn            = document.getElementById("backBtn");
const navDashBtn         = document.getElementById("navDashBtn");
const gotoDashboardBtn   = document.getElementById("gotoDashboardBtn");
const viewAllBtn         = document.getElementById("viewAllBtn");
const dashUploadBtn      = document.getElementById("dashUploadBtn");
const dashEmptyUploadBtn = document.getElementById("dashEmptyUploadBtn");

const landingPage        = document.getElementById("landingPage");
const dashboardPage      = document.getElementById("dashboardPage");

const heroSection        = document.getElementById("heroSection");
const projectsSection    = document.getElementById("projectsSection");
const workspace          = document.getElementById("workspace");
const dashEmptyState     = document.getElementById("dashEmptyState");
const loadingOverlay     = document.getElementById("loadingOverlay");

const viewerFilename     = document.getElementById("viewerFilename");
const overlayContainer   = document.getElementById("overlayContainer");
const panelIssues        = document.getElementById("panelIssues");
const issueCountBadge    = document.getElementById("issueCountBadge");
const scoreValue         = document.getElementById("scoreValue");
const scoreArc           = document.getElementById("scoreArc");
const scoreLabel         = document.getElementById("scoreLabel");
const summaryChips       = document.getElementById("summaryChips");
const partName           = document.getElementById("partName");
const releaseStatus      = document.getElementById("releaseStatus");
const releaseStatusBadge = document.getElementById("releaseStatusBadge");

const projectsList       = document.getElementById("projectsList");
const projectsEmpty      = document.getElementById("projectsEmpty");
const dashProjectList    = document.getElementById("dashProjectList");
const dashProjectEmpty   = document.getElementById("dashProjectEmpty");

// ─── Page routing ─────────────────────────────────────────────────────────────
function showLanding() {
  activePage = "landing";
  landingPage.style.display = "block";
  dashboardPage.style.display = "none";
  backBtn.style.display = "none";
  navDashBtn.classList.remove("nav-active");
  renderLandingProjects();
}

function showDashboard() {
  activePage = "dashboard";
  landingPage.style.display = "none";
  dashboardPage.style.display = "block";
  backBtn.style.display = "none";
  navDashBtn.classList.add("nav-active");
  renderDashSidebar();
}

// ─── Navigation wiring ────────────────────────────────────────────────────────
navBrand.addEventListener("click", (e) => { e.preventDefault(); showLanding(); });
backBtn.addEventListener("click", () => showLanding());
navDashBtn.addEventListener("click", () => showDashboard());
gotoDashboardBtn.addEventListener("click", () => showDashboard());
viewAllBtn.addEventListener("click", () => showDashboard());

// ─── Upload wiring ────────────────────────────────────────────────────────────
function triggerUpload() { fileInput.click(); }

uploadBtn.addEventListener("click", triggerUpload);
heroUploadBtn.addEventListener("click", triggerUpload);
dashUploadBtn.addEventListener("click", triggerUpload);
dashEmptyUploadBtn.addEventListener("click", triggerUpload);

fileInput.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  uploadedFileName = file.name;
  uploadedFile = file;
  saveProject(file.name);
  fileInput.value = "";
  showDashboard();
  openProjectInWorkspace(file.name, file);
});

analyzeBtn.addEventListener("click", () => {
  if (!analysisRun && uploadedFile) runAnalysis();
  else if (!uploadedFile) triggerUpload();
});

// ─── Open a project in the workspace ─────────────────────────────────────────
function openProjectInWorkspace(filename, file) {
  activeProjectFilename = filename;
  uploadedFile = file || null;
  viewerFilename.textContent = filename;
  partName.textContent = filename.replace(/\.[^.]+$/, "").toUpperCase().replace(/[-_]/g, " ");

  dashEmptyState.style.display = "none";
  workspace.style.display = "grid";

  analysisRun = false;
  lastReport = null;
  clearResults();

  document.querySelectorAll(".dash-project-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.filename === filename);
  });

  // Auto-run analysis if we have the file object
  if (file) {
    runAnalysis();
  }
}

// ─── localStorage Projects ────────────────────────────────────────────────────
function saveProject(filename) {
  const projects = getProjects();
  const existing = projects.findIndex((p) => p.filename === filename);
  const entry = { filename, timestamp: Date.now(), status: "pending" };
  if (existing >= 0) {
    entry.status = projects[existing].status || "pending";
    projects[existing] = entry;
  } else {
    projects.unshift(entry);
  }
  localStorage.setItem("ciq_projects", JSON.stringify(projects.slice(0, 10)));
}

function deleteProject(filename) {
  const projects = getProjects().filter((p) => p.filename !== filename);
  localStorage.setItem("ciq_projects", JSON.stringify(projects));
  if (activeProjectFilename === filename) {
    activeProjectFilename = null;
    uploadedFile = null;
    workspace.style.display = "none";
    dashEmptyState.style.display = "flex";
    clearResults();
  }
}

function setProjectStatus(filename, status) {
  const projects = getProjects();
  const idx = projects.findIndex((p) => p.filename === filename);
  if (idx >= 0) {
    projects[idx].status = status;
    localStorage.setItem("ciq_projects", JSON.stringify(projects));
  }
}

function getProjects() {
  try { return JSON.parse(localStorage.getItem("ciq_projects") || "[]"); }
  catch { return []; }
}

function statusMeta(status) {
  switch (status) {
    case "ready":   return { label: "Ready for Release",     cls: "proj-status-ready" };
    case "review":  return { label: "Needs Review",          cls: "proj-status-review" };
    case "blocked": return { label: "Blocked",               cls: "proj-status-blocked" };
    default:        return { label: "Not Ready for Release", cls: "proj-status-not-ready" };
  }
}

function formatTimeAgo(ts) {
  const diff = Date.now() - ts;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ─── Render landing page project list ────────────────────────────────────────
function renderLandingProjects() {
  const projects = getProjects();
  document.querySelectorAll("#projectsList .project-item").forEach((el) => el.remove());

  if (!projects.length) {
    projectsEmpty.style.display = "flex";
    return;
  }
  projectsEmpty.style.display = "none";

  projects.forEach((p) => {
    const { label, cls } = statusMeta(p.status);
    const item = document.createElement("div");
    item.className = "project-item";
    item.innerHTML = `
      <div class="project-item-left">
        <svg class="project-item-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        <div>
          <div class="project-item-name">${p.filename}</div>
          <div class="project-item-time">Uploaded ${formatTimeAgo(p.timestamp)}</div>
          <span class="proj-status-badge ${cls}">${label}</span>
        </div>
      </div>
      <span class="project-item-arrow">›</span>`;
    item.addEventListener("click", () => {
      showDashboard();
      openProjectInWorkspace(p.filename, null);
    });
    projectsList.appendChild(item);
  });
}

// ─── Render dashboard sidebar ─────────────────────────────────────────────────
function renderDashSidebar() {
  const projects = getProjects();
  document.querySelectorAll("#dashProjectList .dash-project-item").forEach((el) => el.remove());

  if (!projects.length) {
    dashProjectEmpty.style.display = "flex";
    return;
  }
  dashProjectEmpty.style.display = "none";

  projects.forEach((p) => {
    const { label, cls } = statusMeta(p.status);
    const item = document.createElement("div");
    item.className = "dash-project-item";
    item.dataset.filename = p.filename;
    if (p.filename === activeProjectFilename) item.classList.add("active");

    item.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
      </svg>
      <div class="dash-project-item-body">
        <div class="dash-project-item-name">${p.filename}</div>
        <div class="dash-project-item-time">${formatTimeAgo(p.timestamp)}</div>
        <span class="proj-status-badge ${cls}">${label}</span>
      </div>
      <div class="dash-project-item-actions">
        <select class="proj-status-select" title="Change status" data-filename="${p.filename}">
          <option value="pending"  ${p.status === "pending"  ? "selected" : ""}>Not Ready</option>
          <option value="review"   ${p.status === "review"   ? "selected" : ""}>Needs Review</option>
          <option value="ready"    ${p.status === "ready"    ? "selected" : ""}>Ready</option>
          <option value="blocked"  ${p.status === "blocked"  ? "selected" : ""}>Blocked</option>
        </select>
        <button class="dash-delete-btn" title="Delete project" data-filename="${p.filename}">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
            <path d="M10 11v6M14 11v6"/>
            <path d="M9 6V4h6v2"/>
          </svg>
        </button>
      </div>`;

    item.querySelector(".dash-project-item-body").addEventListener("click", () => {
      openProjectInWorkspace(p.filename, null);
    });
    item.querySelector("svg:first-child").addEventListener("click", () => {
      openProjectInWorkspace(p.filename, null);
    });

    item.querySelector(".proj-status-select").addEventListener("change", (e) => {
      e.stopPropagation();
      setProjectStatus(p.filename, e.target.value);
      renderDashSidebar();
      renderLandingProjects();
    });

    item.querySelector(".dash-delete-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      if (confirm(`Delete "${p.filename}"?`)) {
        deleteProject(p.filename);
        renderDashSidebar();
        renderLandingProjects();
      }
    });

    dashProjectList.appendChild(item);
  });
}

// ─── Analysis — calls the real backend API ────────────────────────────────────
async function runAnalysis() {
  if (analysisRun) return;
  if (!uploadedFile) {
    showError("No file selected. Please upload a drawing first.");
    return;
  }

  loadingOverlay.style.display = "flex";

  const steps = [
    document.getElementById("step1"),
    document.getElementById("step2"),
    document.getElementById("step3"),
    document.getElementById("step4"),
    document.getElementById("step5"),
  ];

  steps.forEach((s) => { s.className = "loading-step"; });
  steps[0].classList.add("active");

  // Advance the loading steps visually while the API call runs
  let current = 0;
  const stepInterval = setInterval(() => {
    if (current < steps.length - 1) {
      steps[current].classList.remove("active");
      steps[current].classList.add("done");
      current++;
      steps[current].classList.add("active");
    }
  }, 1200);

  try {
    const formData = new FormData();
    formData.append("file", uploadedFile, uploadedFile.name);

    const response = await fetch(`${getBackendUrl()}/analyze`, {
      method: "POST",
      body: formData,
    });

    clearInterval(stepInterval);

    if (!response.ok) {
      let detail = `Server error ${response.status}`;
      try {
        const err = await response.json();
        detail = err.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }

    const report = await response.json();
    lastReport = report;

    // Mark all steps done
    steps.forEach((s) => { s.className = "loading-step done"; });

    setTimeout(() => {
      loadingOverlay.style.display = "none";
      analysisRun = true;
      renderResults(report);
    }, 300);

  } catch (err) {
    clearInterval(stepInterval);
    loadingOverlay.style.display = "none";
    showError(`Analysis failed: ${err.message}`);
  }
}

// ─── Map backend severity to UI severity ─────────────────────────────────────
function mapSeverity(sev) {
  switch ((sev || "").toLowerCase()) {
    case "critical": return "high";
    case "warning":  return "medium";
    case "info":     return "low";
    default:         return "low";
  }
}

// ─── Render results from the API report ──────────────────────────────────────
function clearResults() {
  overlayContainer.innerHTML = "";
  panelIssues.innerHTML = `
    <div class="issues-placeholder">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#334155" stroke-width="1.5">
        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      <p>Run AI-assisted review to detect manufacturing risks</p>
    </div>`;
  issueCountBadge.textContent = "0 issues";
  scoreValue.textContent = "—";
  scoreLabel.textContent = "Awaiting review";
  summaryChips.innerHTML = "";
  scoreArc.style.strokeDashoffset = "150.8";
  scoreArc.style.stroke = "#f59e0b";
  releaseStatus.style.display = "none";
  activeIssueId = null;
}

function renderResults(report) {
  // Normalise issues into the shape the UI expects
  const issues = (report.issues || []).map((issue, idx) => ({
    id: idx + 1,
    title: formatIssueTitle(issue.issue_type),
    severity: mapSeverity(issue.severity),
    category: issue.rule_id || issue.issue_type,
    location: issueLocation(issue, idx),
    description: issue.description || "",
    fix: issue.corrective_action || "Refer to the applicable ANSI/ASME Y14.5 standard.",
    costImpact: costImpactFromSeverity(issue.severity),
    rfiRisk: rfiRiskFromSeverity(issue.severity),
    standardRef: issue.standard_reference || "",
  }));

  const highCount   = issues.filter((i) => i.severity === "high").length;
  const medCount    = issues.filter((i) => i.severity === "medium").length;
  const lowCount    = issues.filter((i) => i.severity === "low").length;

  const score = Math.max(0, 100 - highCount * 18 - medCount * 8 - lowCount * 3);
  const circumference = 150.8;
  const offset = circumference - (score / 100) * circumference;

  scoreValue.textContent = score;
  scoreArc.style.strokeDashoffset = offset;
  scoreArc.style.stroke = score >= 70 ? "#22c55e" : score >= 45 ? "#f59e0b" : "#ef4444";
  scoreLabel.textContent = score >= 70 ? "Acceptable" : score >= 45 ? "Needs Review" : "Critical Issues";

  issueCountBadge.textContent = `${issues.length} issue${issues.length !== 1 ? "s" : ""}`;

  // Release status
  releaseStatus.style.display = "block";
  if (report.overall_status === "Pass" || (score >= 70 && highCount === 0)) {
    releaseStatusBadge.className = "release-status-badge ready";
    releaseStatusBadge.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> READY FOR RELEASE`;
    setProjectStatus(activeProjectFilename, "ready");
  } else {
    releaseStatusBadge.className = "release-status-badge not-ready";
    releaseStatusBadge.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> NOT READY FOR RELEASE`;
    setProjectStatus(activeProjectFilename, highCount > 0 ? "blocked" : "review");
  }
  renderDashSidebar();

  // Summary chips
  summaryChips.innerHTML = `
    ${highCount ? `<span class="chip chip-high">● ${highCount} Critical</span>` : ""}
    ${medCount  ? `<span class="chip chip-medium">● ${medCount} Warning</span>` : ""}
    ${lowCount  ? `<span class="chip chip-low">● ${lowCount} Info</span>` : ""}
  `;

  // Systemic patterns banner
  if (report.systemic_patterns && report.systemic_patterns.length) {
    const banner = document.createElement("div");
    banner.className = "systemic-banner";
    banner.innerHTML = `<strong>Systemic patterns detected:</strong> ${report.systemic_patterns.join(" · ")}`;
    panelIssues.parentElement.insertBefore(banner, panelIssues);
  }

  // Overlays on drawing (spread evenly since we don't have real coordinates)
  overlayContainer.innerHTML = "";
  issues.forEach((issue, idx) => {
    const dot = document.createElement("div");
    dot.className = "issue-overlay";
    dot.style.left = issue.location.x;
    dot.style.top  = issue.location.y;
    dot.innerHTML = `<div class="overlay-marker severity-${issue.severity}" data-id="${issue.id}">${idx + 1}</div>`;
    dot.addEventListener("click", () => selectIssue(issue.id));
    overlayContainer.appendChild(dot);
  });

  // Issue cards
  panelIssues.innerHTML = "";

  if (!issues.length) {
    panelIssues.innerHTML = `
      <div class="issues-placeholder">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="1.5">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
        <p style="color:#86efac">No issues found — drawing is ready for manufacturing.</p>
      </div>`;
    return;
  }

  issues.forEach((issue, idx) => {
    const card = document.createElement("div");
    card.className = `issue-card severity-${issue.severity}`;
    card.dataset.id = issue.id;
    card.innerHTML = `
      <div class="issue-card-header">
        <span class="issue-title">${idx + 1}. ${issue.title}</span>
        <span class="issue-severity-tag tag-${issue.severity}">${severityLabel(issue.severity)}</span>
      </div>
      <p class="issue-desc">${issue.description}</p>
      <div class="issue-meta">
        <span class="issue-meta-item">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          ${issue.category}
        </span>
        <span class="issue-meta-item">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          ${issue.costImpact}
        </span>
        <span class="issue-meta-item">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          Supplier RFI Risk: ${issue.rfiRisk}
        </span>
        ${issue.standardRef ? `<span class="issue-meta-item">📐 ${issue.standardRef}</span>` : ""}
      </div>
      <div class="issue-fix">
        <strong>Suggested Fix:</strong> ${issue.fix}
      </div>
    `;
    card.addEventListener("click", () => selectIssue(issue.id));
    panelIssues.appendChild(card);
  });

  if (issues.length) setTimeout(() => selectIssue(issues[0].id), 200);
}

// ─── Select issue ─────────────────────────────────────────────────────────────
function selectIssue(id) {
  activeIssueId = id;
  document.querySelectorAll(".issue-card").forEach((c) => {
    c.classList.toggle("active", parseInt(c.dataset.id) === id);
  });
  document.querySelectorAll(".overlay-marker").forEach((m) => {
    m.classList.toggle("active", parseInt(m.dataset.id) === id);
  });
  const activeCard = document.querySelector(`.issue-card[data-id="${id}"]`);
  if (activeCard) activeCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ─── Error display ────────────────────────────────────────────────────────────
function showError(message) {
  panelIssues.innerHTML = `
    <div class="issues-placeholder" style="color:#fca5a5">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <p>${message}</p>
    </div>`;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function formatIssueTitle(issueType) {
  return (issueType || "Issue")
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function severityLabel(sev) {
  switch (sev) {
    case "high":   return "Critical";
    case "medium": return "Warning";
    case "low":    return "Info";
    default:       return sev;
  }
}

function costImpactFromSeverity(sev) {
  switch ((sev || "").toLowerCase()) {
    case "critical": return "High — likely RFI or manufacturing defect";
    case "warning":  return "Medium — may cause ambiguity or rework";
    default:         return "Low — documentation or best-practice gap";
  }
}

function rfiRiskFromSeverity(sev) {
  switch ((sev || "").toLowerCase()) {
    case "critical": return "Very Likely";
    case "warning":  return "Possible";
    default:         return "Unlikely";
  }
}

// Spread issue markers across the drawing canvas in a grid pattern
function issueLocation(issue, idx) {
  const cols = 4;
  const col = idx % cols;
  const row = Math.floor(idx / cols);
  return {
    x: `${15 + col * 20}%`,
    y: `${20 + row * 18}%`,
  };
}

// ─── Init ─────────────────────────────────────────────────────────────────────
showLanding();
