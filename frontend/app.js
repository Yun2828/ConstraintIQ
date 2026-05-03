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
const partName           = { textContent: "" }; // stub — title block removed from viewer
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
  navDashBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> Dashboard`;
  renderLandingProjects();
}

function showDashboard() {
  activePage = "dashboard";
  landingPage.style.display = "none";
  dashboardPage.style.display = "block";
  backBtn.style.display = "none";
  navDashBtn.classList.add("nav-active");
  navDashBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg> Landing`;
  renderDashSidebar();
}

// ─── Navigation wiring ────────────────────────────────────────────────────────
navBrand.addEventListener("click", (e) => { e.preventDefault(); showLanding(); });
backBtn.addEventListener("click", () => showLanding());
// Dashboard button toggles between landing and dashboard
navDashBtn.addEventListener("click", () => {
  if (activePage === "dashboard") showLanding();
  else showDashboard();
});
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
  saveProjectPdf(file.name, file);  // cache PDF for history
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
  viewerFilename.textContent = filename;
  partName.textContent = filename.replace(/\.[^.]+$/, "").toUpperCase().replace(/[-_]/g, " ");

  dashEmptyState.style.display = "none";
  workspace.style.display = "grid";

  document.querySelectorAll(".dash-project-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.filename === filename);
  });

  // If we have the actual file object, use it directly
  if (file) {
    uploadedFile = file;
    analysisRun = false;
    lastReport = null;
    clearResults();
    loadFileIntoViewer(file);
    runAnalysis();
    return;
  }

  // Try to restore from cache
  const cachedReport = getProjectReport(filename);
  const cachedFile   = getProjectPdfAsFile(filename);

  if (cachedFile) {
    uploadedFile = cachedFile;
    loadFileIntoViewer(cachedFile);
  } else {
    uploadedFile = null;
    loadFileIntoViewer(null);
  }

  if (cachedReport) {
    // Restore previous analysis results
    analysisRun = true;
    lastReport = cachedReport;
    clearResults();
    renderResults(cachedReport);
  } else {
    // No cached report — show empty state, let user re-analyze
    analysisRun = false;
    lastReport = null;
    clearResults();
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

function saveProjectReport(filename, report) {
  try {
    localStorage.setItem(`ciq_report_${filename}`, JSON.stringify(report));
  } catch (e) {
    // localStorage full — silently skip caching
    console.warn("Could not cache report:", e);
  }
}

function getProjectReport(filename) {
  try {
    const raw = localStorage.getItem(`ciq_report_${filename}`);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function saveProjectPdf(filename, file) {
  // Store PDF as base64 in localStorage (works for files < ~3MB)
  try {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        localStorage.setItem(`ciq_pdf_${filename}`, e.target.result);
      } catch (err) {
        console.warn("PDF too large to cache in localStorage:", err);
      }
    };
    reader.readAsDataURL(file);
  } catch (e) {
    console.warn("Could not cache PDF:", e);
  }
}

function getProjectPdfAsFile(filename) {
  try {
    const dataUrl = localStorage.getItem(`ciq_pdf_${filename}`);
    if (!dataUrl) return null;
    // Convert base64 data URL back to a File object
    const arr = dataUrl.split(",");
    const mime = arr[0].match(/:(.*?);/)[1];
    const bstr = atob(arr[1]);
    let n = bstr.length;
    const u8arr = new Uint8Array(n);
    while (n--) u8arr[n] = bstr.charCodeAt(n);
    return new File([u8arr], filename, { type: mime });
  } catch { return null; }
}

function deleteProject(filename) {
  const projects = getProjects().filter((p) => p.filename !== filename);
  localStorage.setItem("ciq_projects", JSON.stringify(projects));
  // Clean up cached report and PDF
  localStorage.removeItem(`ciq_report_${filename}`);
  localStorage.removeItem(`ciq_pdf_${filename}`);
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

  // Hide analyze button while analyzing
  analyzeBtn.style.display = "none";
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
      analyzeBtn.style.display = "";  // restore button
      analysisRun = true;
      // Cache report and PDF for history
      saveProjectReport(activeProjectFilename, report);
      renderResults(report);
    }, 300);

  } catch (err) {
    clearInterval(stepInterval);
    loadingOverlay.style.display = "none";
    analyzeBtn.style.display = "";  // restore button on error too
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
  // Title-block / drawing-level issue types — no dot on PDF
  const DRAWING_LEVEL_TYPES = new Set([
    "MISSING_TITLE_BLOCK_PART_NUMBER", "MISSING_TITLE_BLOCK_REVISION",
    "MISSING_TITLE_BLOCK_MATERIAL", "MISSING_TITLE_BLOCK_SCALE",
    "MISSING_TITLE_BLOCK_UNITS", "MISSING_DATUM_REFERENCE_FRAME",
    "INCOMPLETE_DATUM_REFERENCE_FRAME", "DATUM_SYMBOL_NO_FEATURE",
    "DATUM_SYMBOL_ON_NON_PHYSICAL_FEATURE", "NO_ORTHOGRAPHIC_VIEWS",
    "INSUFFICIENT_DATA_EXTRACTED", "NOTE_UNIT_SYSTEM_CONTRADICTION",
  ]);

  // Map and filter to only located issues (have coords, not drawing-level)
  const locatedIssues = (report.issues || [])
    .filter(i => i.issue_type !== "ML_UNAVAILABLE")
    .filter(i => !DRAWING_LEVEL_TYPES.has(i.issue_type))
    .filter(i => i.location && i.location.coordinates &&
                 i.location.coordinates.x != null && i.location.coordinates.y != null)
    .map((issue, idx) => ({
      id:           idx + 1,
      title:        formatIssueTitle(issue.issue_type),
      severity:     mapSeverity(issue.severity),
      _rawSeverity: issue.severity,
      _issueType:   issue.issue_type,
      description:  issue.description || "",
      fix:          issue.corrective_action || "Refer to ANSI/ASME Y14.5.",
      _rawCoords:   { x: issue.location.coordinates.x, y: issue.location.coordinates.y },
    }));

  // Store globally so PDF canvas re-render can re-place dots
  _lastIssues = locatedIssues;

  // Score based on all non-ML issues
  const allIssues = (report.issues || []).filter(i => i.issue_type !== "ML_UNAVAILABLE");
  const allHigh = allIssues.filter(i => mapSeverity(i.severity) === "high").length;
  const allMed  = allIssues.filter(i => mapSeverity(i.severity) === "medium").length;
  const allLow  = allIssues.filter(i => mapSeverity(i.severity) === "low").length;

  let score = 100;
  if (allIssues.length > 0) {
    score = Math.max(0, Math.round(100
      - Math.min(allHigh * 12, 65)
      - Math.min(allMed  *  5, 20)
      - Math.min(allLow  *  2,  5)));
  }

  const circumference = 150.8;
  scoreValue.textContent = score + "%";
  scoreArc.style.strokeDashoffset = circumference - (score / 100) * circumference;
  scoreArc.style.stroke = score === 100 ? "#22c55e" : score >= 70 ? "#f59e0b" : "#ef4444";
  scoreLabel.textContent = score === 100 ? "Ready for Release" : score >= 70 ? "Needs Review" : "Critical Issues";

  // Release status
  releaseStatus.style.display = "block";
  if (score === 100) {
    releaseStatusBadge.className = "release-status-badge ready";
    releaseStatusBadge.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> READY FOR RELEASE`;
    setProjectStatus(activeProjectFilename, "ready");
  } else if (score >= 70) {
    releaseStatusBadge.className = "release-status-badge not-ready";
    releaseStatusBadge.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> NEEDS REVIEW`;
    setProjectStatus(activeProjectFilename, "review");
  } else {
    releaseStatusBadge.className = "release-status-badge not-ready";
    releaseStatusBadge.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> NOT READY FOR RELEASE`;
    setProjectStatus(activeProjectFilename, allHigh > 0 ? "blocked" : "review");
  }
  renderDashSidebar();

  // Badge and chips based on located issues
  const n = locatedIssues.length;
  issueCountBadge.textContent = `${n} issue${n !== 1 ? "s" : ""}`;
  const lH = locatedIssues.filter(i => i.severity === "high").length;
  const lM = locatedIssues.filter(i => i.severity === "medium").length;
  const lL = locatedIssues.filter(i => i.severity === "low").length;
  summaryChips.innerHTML = `
    ${lH ? `<span class="chip chip-high">● ${lH} Critical</span>` : ""}
    ${lM ? `<span class="chip chip-medium">● ${lM} Warning</span>` : ""}
    ${lL ? `<span class="chip chip-low">● ${lL} Info</span>` : ""}
  `;

  // Render panel cards immediately (same list as dots)
  renderPanel(locatedIssues);

  // Render overlays (may be deferred if canvas not ready yet)
  renderOverlays(locatedIssues);
}

// ─── Render right panel cards ─────────────────────────────────────
function renderPanel(issues) {
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

  issues.forEach(issue => {
    const card = document.createElement("div");
    card.className = `issue-card severity-${issue.severity}`;
    card.dataset.id = issue.id;
    const costLabel = costImpactFromSeverity(issue._rawSeverity);
    const rfiLabel  = rfiRiskFromSeverity(issue._rawSeverity);
    card.innerHTML = `
      <div class="issue-card-header">
        <div class="issue-number-badge severity-${issue.severity}">${issue.id}</div>
        <div style="flex:1;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <span class="issue-title">${issue.title}</span>
          <span class="issue-severity-tag tag-${issue.severity}">${severityLabel(issue.severity)}</span>
        </div>
      </div>
      <p class="issue-desc">${issue.description}</p>
      <div class="issue-meta-row">
        <span class="issue-meta-item">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          ${costLabel}
        </span>
        <span class="issue-meta-item">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          Supplier RFI Risk: ${rfiLabel}
        </span>
      </div>
      <div class="issue-fix-box">
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
  // Scroll card into view
  const activeCard = document.querySelector(`.issue-card[data-id="${id}"]`);
  if (activeCard) activeCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  // Scroll dot into view in the PDF canvas wrap
  const activeDot = document.querySelector(`.overlay-marker[data-id="${id}"]`);
  if (activeDot) activeDot.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
  // Clean up internal rule names into human-readable titles
  const titleMap = {
    "MISSING_SIZE_DIMENSION": "Missing Size Dimension",
    "MISSING_POSITION_DIMENSION": "Missing Position Dimension",
    "MISSING_ANGULAR_DIMENSION": "Missing Angular Dimension",
    "OVER_DIMENSION": "Redundant Dimension",
    "MISSING_DATUM_REFERENCE_FRAME": "Missing Datum Reference Frame",
    "INCOMPLETE_DATUM_REFERENCE_FRAME": "Incomplete Datum Reference Frame",
    "UNCONSTRAINED_FEATURE_ORIENTATION": "Unconstrained Feature Orientation",
    "UNDEFINED_DATUM_REFERENCE": "Undefined Datum Reference",
    "MISSING_DIMENSION_TOLERANCE": "Missing Dimension Tolerance",
    "MISSING_FCF_TOLERANCE_VALUE": "Incomplete GD&T Control Frame",
    "MISSING_FCF_DATUM_REFERENCE": "Missing Datum in GD&T Frame",
    "TOLERANCE_STACK_UP_VIOLATION": "Tolerance Stack-Up Issue",
    "MISSING_TITLE_BLOCK_PART_NUMBER": "Missing Part Number",
    "MISSING_TITLE_BLOCK_REVISION": "Missing Revision",
    "MISSING_TITLE_BLOCK_MATERIAL": "Missing Material Specification",
    "MISSING_TITLE_BLOCK_SCALE": "Missing Drawing Scale",
    "MISSING_TITLE_BLOCK_UNITS": "Missing Units",
    "MISSING_SURFACE_FINISH_CALLOUT": "Missing Surface Finish",
    "HOLE_MISSING_DIAMETER": "Hole Missing Diameter",
    "HOLE_MISSING_DEPTH": "Hole Missing Depth",
    "HOLE_MISSING_TOLERANCE": "Hole Missing Tolerance",
    "HOLE_MISSING_THREAD_SPEC": "Missing Thread Specification",
    "NO_ORTHOGRAPHIC_VIEWS": "Insufficient Views",
    "FEATURE_NOT_IN_ANY_VIEW": "Feature Not Shown in View",
    "NOTE_DIMENSION_CONTRADICTION": "Note/Dimension Contradiction",
    "NOTE_UNIT_SYSTEM_CONTRADICTION": "Unit System Conflict",
    "NON_STANDARD_GDT_SYMBOL": "Non-Standard GD&T Symbol",
    "COMPOSITE_FCF_INVALID_PLTZF_TOLERANCE": "Invalid Composite Tolerance",
    "DATUM_SYMBOL_NO_FEATURE": "Datum Symbol Placement Issue",
    "INSUFFICIENT_DATA_EXTRACTED": "Drawing Data Extraction Issue",
    "ML_UNAVAILABLE": "Analysis Mode",
  };
  if (titleMap[issueType]) return titleMap[issueType];
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

// Map issue location to a position on the drawing canvas.
// Uses real PDF coordinates when available, otherwise falls back to a grid.
function issueLocation(issue, idx, allIssues) {
  // Try to use real coordinates from the backend
  const coords = issue._rawCoords;
  if (coords && coords.x != null && coords.y != null && issue._pageBounds) {
    const bounds = issue._pageBounds;
    // Clamp to 5%–95% so dots don't sit on the very edge
    const xPct = Math.min(95, Math.max(5, ((coords.x - bounds.minX) / bounds.rangeX) * 90 + 5));
    const yPct = Math.min(95, Math.max(5, ((coords.y - bounds.minY) / bounds.rangeY) * 90 + 5));
    return { x: `${xPct.toFixed(1)}%`, y: `${yPct.toFixed(1)}%` };
  }
  // Fallback: grid for issues without coordinates
  const cols = 4;
  const rows = 4;
  const totalSlots = cols * rows;
  const slotIdx = idx % totalSlots;
  const col = slotIdx % cols;
  const row = Math.floor(slotIdx / cols);
  return {
    x: `${12 + col * 20}%`,
    y: `${15 + row * 18}%`,
  };
}

// ─── PDF.js viewer state ──────────────────────────────────────────
let _lastIssues    = []; // global cache for re-render after PDF loads
let _pdfPageWidth  = 1;
let _pdfPageHeight = 1;
let _canvasOffsetX = 0;
let _canvasOffsetY = 0;
let _canvasScale   = 1;

// ─── Load file into viewer ────────────────────────────────────────
function loadFileIntoViewer(file) {
  const pdfCanvasWrap  = document.getElementById("pdfCanvasWrap");
  const pdfCanvas      = document.getElementById("pdfCanvas");
  const dxfFallback    = document.getElementById("dxfFallback");
  const dxfFallbackName = document.getElementById("dxfFallbackName");

  pdfCanvasWrap.style.display = "none";
  dxfFallback.style.display   = "none";
  overlayContainer.innerHTML  = "";

  if (!file) return;

  const suffix = file.name.split(".").pop().toLowerCase();

  if (suffix === "pdf") {
    pdfCanvasWrap.style.display = "block";
    const reader = new FileReader();
    reader.onload = async (e) => {
      try {
        const typedArray = new Uint8Array(e.target.result);
        const pdf = await pdfjsLib.getDocument({ data: typedArray }).promise;
        const page = await pdf.getPage(1);
        const viewport = page.getViewport({ scale: 1.0 });

        // Scale to fit the viewer width
        const wrapW = pdfCanvasWrap.clientWidth || 700;
        const scale = Math.min((wrapW - 32) / viewport.width, 2.0);
        const scaledViewport = page.getViewport({ scale });

        pdfCanvas.width  = scaledViewport.width;
        pdfCanvas.height = scaledViewport.height;

        // Store for coordinate mapping
        _pdfPageWidth  = viewport.width;
        _pdfPageHeight = viewport.height;
        _canvasScale   = scale;
        // Canvas is centered — compute left offset
        _canvasOffsetX = Math.max(0, (pdfCanvasWrap.clientWidth - scaledViewport.width) / 2);
        _canvasOffsetY = 0;

        const ctx = pdfCanvas.getContext("2d");
        await page.render({ canvasContext: ctx, viewport: scaledViewport }).promise;

        // Re-render overlays now that canvas dimensions are known
        renderOverlays(_lastIssues);
        // Rebuild panel so numbers match dots exactly
        if (_lastIssues.length) renderPanel(_lastIssues);
      } catch (err) {
        console.error("PDF.js render error:", err);
      }
    };
    reader.readAsArrayBuffer(file);
  } else {
    dxfFallbackName.textContent = file.name;
    dxfFallback.style.display   = "flex";
  }
}

// ─── Render overlays on the PDF canvas ───────────────────────────
function renderOverlays(issues) {
  overlayContainer.innerHTML = "";
  const pdfCanvas = document.getElementById("pdfCanvas");
  if (!pdfCanvas || pdfCanvas.width === 0) return;

  const TITLE_BLOCK_TYPES = new Set([
    "MISSING_TITLE_BLOCK_PART_NUMBER", "MISSING_TITLE_BLOCK_REVISION",
    "MISSING_TITLE_BLOCK_MATERIAL", "MISSING_TITLE_BLOCK_SCALE",
    "MISSING_TITLE_BLOCK_UNITS", "MISSING_DATUM_REFERENCE_FRAME",
    "INCOMPLETE_DATUM_REFERENCE_FRAME", "DATUM_SYMBOL_NO_FEATURE",
    "DATUM_SYMBOL_ON_NON_PHYSICAL_FEATURE", "NO_ORTHOGRAPHIC_VIEWS",
    "INSUFFICIENT_DATA_EXTRACTED", "NOTE_UNIT_SYSTEM_CONTRADICTION",
  ]);

  const drawingBodyMaxY = pdfCanvas.height * 0.82;

  // First pass: collect all renderable dots
  const renderable = [];
  issues.forEach(issue => {
    if (TITLE_BLOCK_TYPES.has(issue._issueType)) return;
    const coords = issue._rawCoords;
    if (!coords || coords.x == null || coords.y == null) return;
    const canvasX = coords.x * _canvasScale + _canvasOffsetX;
    const canvasY = (_pdfPageHeight - coords.y) * _canvasScale + _canvasOffsetY;
    if (canvasY > drawingBodyMaxY) return;
    if (canvasX < 0 || canvasY < 0 ||
        canvasX > pdfCanvas.width + _canvasOffsetX ||
        canvasY > pdfCanvas.height + _canvasOffsetY) return;
    renderable.push({ issue, canvasX, canvasY });
  });

  // Second pass: assign sequential numbers 1,2,3... and render
  renderable.forEach(({ issue, canvasX, canvasY }, idx) => {
    const num = idx + 1;
    issue.id = num; // keep in sync with panel

    const dot = document.createElement("div");
    dot.className = "issue-overlay";
    dot.style.left = `${canvasX}px`;
    dot.style.top  = `${canvasY}px`;
    dot.style.pointerEvents = "all";
    dot.innerHTML = `<div class="overlay-marker severity-${issue.severity}" data-id="${num}" title="${issue.title}">${num}</div>`;
    dot.addEventListener("click", () => selectIssue(num));
    overlayContainer.appendChild(dot);
  });

  console.log(`renderOverlays: ${renderable.length} dots`);
  return renderable.length;
}

// ─── Init ─────────────────────────────────────────────────────────────────────
showLanding();
