// Read from the page, not interpolated in: keeps this file static and cacheable.
const cfg = JSON.parse(document.getElementById("config").textContent);

// A loopback detector is only loopback from the Pi, so a remote browser follows
// this page's own host on its port; anything else is linked as configured.
document.getElementById("birdnet").href = cfg.birdnetPort
  ? location.protocol + "//" + location.hostname + ":" + cfg.birdnetPort + "/"
  : cfg.birdnetUrl;

// Every button posts and redirects, so a save reloads: the tab and the scroll
// position have to be carried across by hand.
let saving = false;
for (const f of document.querySelectorAll("form")) {
  f.addEventListener("submit", () => {
    saving = true;
    sessionStorage.setItem("scroll", String(window.scrollY));
  });
}
const scrolled = sessionStorage.getItem("scroll");
sessionStorage.removeItem("scroll");

// The install reloads the page as a new version, so the tab is what remembers
// the old one - long enough to say the update landed.
const was = sessionStorage.getItem("version");
const state = document.getElementById("state");
sessionStorage.setItem("version", cfg.version);
if (state && was && was !== cfg.version) state.textContent = "已更新至 v" + cfg.version;

const tabs = document.querySelectorAll("nav.tabs button");
function showTab(name) {
  for (const tab of tabs) {
    const on = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", on);
    document.getElementById("tab-" + tab.dataset.tab).hidden = !on;
  }
  localStorage.setItem("tab", name);
}
for (const tab of tabs) tab.addEventListener("click", () => showTab(tab.dataset.tab));
showTab(localStorage.getItem("tab") === "system" ? "system" : "settings");

// A setting one tab cannot offer, pointing at the tab that fixes it: open that
// one first, then the href's fragment scrolls to the field itself.
for (const link of document.querySelectorAll("a[data-tab]")) {
  link.addEventListener("click", () => showTab(link.dataset.tab));
}

// A hint is a span inside its <label>, so a touch has no hover to open the bubble
// with and the label passes the tap on to its select. Cancelling the click stops that.
let openHint = null;
function closeHint() {
  if (openHint) openHint.classList.remove("open");
  openHint = null;
}
for (const hint of document.querySelectorAll(".hint")) {
  hint.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const opening = hint !== openHint;
    closeHint();
    if (opening) {
      hint.classList.add("open");
      openHint = hint;
    }
  });
}
document.addEventListener("click", closeHint);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeHint(); });

// The check runs inside its own POST, so the spinner only has to outlive the navigation.
const check = document.querySelector("dd.update form.check");
if (check) {
  check.addEventListener("submit", () => {
    check.insertAdjacentHTML("beforebegin", '<span class="spinner inline"></span>');
    check.querySelector("button").disabled = true;
  });
}

// An install ends with systemd restarting us, so the poll rides out a dead
// server and reloads once one answers with the work done - or failed.
if (document.getElementById("bar")) {
  const phase = document.getElementById("phase");
  const bar = document.getElementById("bar");
  (function poll() {
    setTimeout(async () => {
      try {
        const state = await (await fetch("/update", {cache: "no-store"})).json();
        if (!state.updating) {
          location.reload();
          return;
        }
        if (state.phase) {
          phase.textContent = state.phase + (state.percent === null ? "" : " " + state.percent + "%");
        }
        if (state.percent === null) bar.removeAttribute("value");
        else bar.value = state.percent;
      } catch (e) {}
      poll();
    }, 1000);
  })();
}

// Tests the values in the form, not the saved ones, so a fix can be tried first.
const test = document.getElementById("test");
if (test) {
  const detectorForm = document.getElementById("detector");
  const outcome = document.getElementById("test-result");
  const row = document.getElementById("detector-state");
  const creds = document.getElementById("credentials");
  test.addEventListener("click", async () => {
    test.disabled = true;
    outcome.className = "";
    outcome.textContent = "测试中…";
    try {
      const body = new URLSearchParams(new FormData(detectorForm));
      const answer = await fetch("/detector", {method: "POST", body});
      const result = await answer.json();
      // "names" is a working detector holding back one thing, so it warns
      // rather than fails - but it is fixed in the same box as "auth".
      outcome.className = {ok: "ok", names: "warn"}[result.state] || "bad";
      outcome.textContent = result.text;
      if (result.state === "auth" || result.state === "names") creds.open = true;
      // The row is about the detector the frame reads from, so only a test of
      // the saved values speaks for it - edited ones may never be saved.
      if (!changed.get(detectorForm)()) row.innerHTML = result.status;
    } catch (e) {
      outcome.className = "bad";
      outcome.textContent = "服务未响应";
    }
    test.disabled = false;
  });
}

const preview = document.getElementById("preview");
const shot = document.getElementById("shot");
const mat = document.getElementById("mat");
const caption = document.querySelector(".rendering");
const captionHTML = caption.innerHTML;
const form = document.querySelector("form.settings");
let shown = null, seq = 0, timer = null;
const queueRender = () => {
  clearTimeout(timer);  // debounced: a render is expensive on the Pi
  timer = setTimeout(loadPreview, 500);
};

function loadPreview() {
  mat.hidden = true;  // the band only stands in until the render starts
  const query = serialize(form);
  if (query === shown && !preview.classList.contains("loading")) return;
  const id = ++seq;
  const [w, h] = cfg.panel;
  // Turned now rather than when the render lands, so the box does not jump.
  preview.style.setProperty("--aspect", form.rotation.value % 180 ? `${h} / ${w}` : `${w} / ${h}`);
  preview.classList.add("loading");
  caption.innerHTML = captionHTML;
  const next = new Image();  // decode off-screen, so the img is never stale or broken
  next.onload = () => {
    if (id !== seq) return;  // a later edit already superseded this render
    shown = query;
    shot.src = next.src;
    preview.classList.remove("loading");
  };
  next.onerror = () => {
    if (id !== seq) return;
    preview.classList.remove("loading");
    caption.textContent = "预览不可用";
  };
  // Cache-buster: upload injects must not reuse a browser-cached collage.
  next.src = "/preview.png?" + query + "&_=" + Date.now();
  loadSpecies(query, id);
}

// The list under the preview is of the page being previewed, not the saved one.
async function loadSpecies(query, id) {
  try {
    const body = await (await fetch("/species?" + query, {cache: "no-store"})).json();
    if (id !== seq) return;
    document.getElementById("count").textContent = body.count;
    document.getElementById("species").innerHTML = body.html;
  } catch (e) {}  // the preview alone is worth showing
}

// Shade the mat band on the page already on screen, so the margin can be judged
// before the render catches up.
const margin = form.querySelector("input[name=margin]");
const readout = document.getElementById("margin-value");
margin.addEventListener("input", () => {
  readout.textContent = margin.value + "%";
  const box = preview.getBoundingClientRect();
  mat.style.borderWidth = Math.min(box.width, box.height) * margin.value / 100 + "px";
  mat.hidden = preview.classList.contains("loading");  // no page on screen to shade
});
margin.addEventListener("change", queueRender);  // on release, or a keyboard step

// Settings the chosen mode ignores go dim and stop being submitted, so the
// saved value survives a trip through a mode that has no use for it.
const lookback = document.getElementById("lookback");
const limit = document.getElementById("limit");
const ranking = document.getElementById("ranking");
const layout = document.getElementById("layout");
function dim(el, on) {
  el.querySelectorAll("select, input").forEach((c) => { c.disabled = !on; });
  el.classList.toggle("off", !on);
}
function syncMode() {
  const mode = form.querySelector("input[name=mode]:checked");
  const on = !mode || cfg.windowedModes.includes(mode.value);
  dim(lookback, on);
  dim(limit, on);
  dim(layout, on);
  // Nothing to rank while every bird the window heard is already on the page.
  const capped = form.querySelector("input[name=limit_mode]:checked")?.value === "some";
  form.querySelector("input[name=species_limit]").disabled = !(on && capped);  // after dim(limit)
  dim(ranking, on && capped);
}

// Park western / Chinese font panels into the language column that needs them.
const fontWestern = document.getElementById("font-western");
const fontCjk = document.getElementById("font-cjk");
const fontDock = document.getElementById("font-dock");
const fontShared = document.getElementById("font-western-shared");
const primaryCol = document.getElementById("lang-primary");
const secondaryCol = document.getElementById("lang-secondary");
function scriptOf(code) {
  if (!code) return "none";
  return code === "zh" ? "cjk" : "western";
}
function syncLangFonts() {
  if (!fontWestern || !primaryCol) return;
  const primary = form.primary_language.value;
  const secondary = form.secondary_language.value;
  const pScript = scriptOf(primary);
  const sScript = scriptOf(secondary);
  const pSlot = primaryCol.querySelector(".font-slot");
  const sSlot = secondaryCol.querySelector(".font-slot");
  fontDock.append(fontWestern, fontCjk);
  fontShared.hidden = true;
  if (pScript === "cjk") pSlot.append(fontCjk);
  else if (pScript === "western") pSlot.append(fontWestern);
  // Keep the language <select> usable even when the column has no second language;
  // only the font area reads as inactive.
  secondaryCol.classList.toggle("lang-off", sScript === "none");
  if (sScript === "cjk") {
    if (pScript !== "cjk") sSlot.append(fontCjk);
  } else if (sScript === "western") {
    if (pScript !== "western") sSlot.append(fontWestern);
    else fontShared.hidden = false;
  }
}

// Capture, so a mode change settles which fields still submit before the shared
// dirty check reads them - a round trip back to the saved mode is not a change.
form.addEventListener("input", (e) => {
  syncMode();
  syncLangFonts();
  if (e.target === margin) return clearTimeout(timer);  // a drag renders on release only
  queueRender();
}, true);

syncMode();
syncLangFonts();

// Save stays disabled until a form differs from what the server served. An
// untouched password placeholder serializes the same both times, so it needs no
// case of its own. The action forms (Check, Install) are not settings and stay out.
// Snapshot after syncMode - dimmed fields are already out of the form data.
const serialize = (f) => new URLSearchParams(new FormData(f)).toString();
const changed = new Map();
for (const f of document.querySelectorAll("form.settings, form.block")) {
  const button = f.querySelector("button[type=submit]");
  // Upload / action-only forms have no Save button and must not stop the page.
  if (!button) continue;
  const served = serialize(f);
  const dirty = () => serialize(f) !== served;
  changed.set(f, dirty);
  f.addEventListener("input", () => { button.disabled = !dirty(); });
  button.disabled = true;
}

// An untouched form is never dirty, so this only fires over edits the user
// would actually lose - a typed password among them.
window.addEventListener("beforeunload", (e) => {
  if (saving || ![...changed.values()].some((dirty) => dirty())) return;
  e.preventDefault();
  e.returnValue = "";
});

// Upload audio → BirdNET-Go file analysis → overlay on preview.
const analyzeBtn = document.getElementById("analyze-btn");
const analyzeResult = document.getElementById("analyze-result");
const audioFile = document.getElementById("audio-file");
if (analyzeBtn && audioFile) {
  analyzeBtn.addEventListener("click", async () => {
    if (!audioFile.files.length) {
      analyzeResult.className = "bad";
      analyzeResult.textContent = "请先选择音频文件";
      return;
    }
    analyzeBtn.disabled = true;
    analyzeResult.className = "warn";
    analyzeResult.textContent = "识别中…";
    const body = new FormData();
    body.append("audio", audioFile.files[0]);
    try {
      const answer = await fetch("/analyze-audio", {method: "POST", body});
      const result = await answer.json();
      if (result.ok) {
        analyzeResult.className = "ok";
        const names = (result.species || []).map((s) => s.name).join("、");
        analyzeResult.textContent = result.message + (names ? "：" + names : "");
        // Collage shows every recognized bird; force a full preview reload.
        const collage = form.querySelector("input[name=mode][value=collage]");
        if (collage) collage.checked = true;
        syncMode();
        shown = null;
        clearTimeout(timer);
        loadPreview();
      } else {
        analyzeResult.className = "bad";
        analyzeResult.textContent = result.message || "无法识别";
      }
    } catch (e) {
      analyzeResult.className = "bad";
      analyzeResult.textContent = "服务未响应";
    }
    analyzeBtn.disabled = false;
  });
}

loadPreview();
if (scrolled !== null) window.scrollTo(0, Number(scrolled));
