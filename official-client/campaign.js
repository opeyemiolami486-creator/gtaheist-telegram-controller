/* Account UI is optional and never replaces the game. No identity in localStorage. */
(() => {
  "use strict";
  const API =
    (location.hostname === "localhost" || location.hostname === "127.0.0.1"
      ? ""
      : "https://api.gtaheist.fun") + "/api/";
  let state = null,
    csrf = "",
    ready,
    loading = false;
  let checkedState = null,
    checkedOwner = null;
  const bootPreferences = {};
  let bootSettings = {};
  try {
    for (const k of [
      "gtd_mode",
      "gtd_muted",
      "gtd_station",
      "gth_diff",
      "gth_dist",
      "gth_fac",
      "gth_low",
    ]) {
      const v = localStorage.getItem(k);
      if (v !== null) bootPreferences[k] = v;
    }
    bootSettings =
      JSON.parse(localStorage.getItem("gtd_prof") || "{}").settings || {};
  } catch {}
  const nativeFetch = window.fetch.bind(window);
  // Credentialed same-site API calls; never attach CSRF to arbitrary URLs.
  const pending = new Map();
  let refreshPromise = null,
    appliedAccount = null,
    nameDirty = false;
  function runNotice(text, retry = false) {
    const n = document.getElementById("cp-network");
    if (!n) return;
    // No routine footer/status bars: retain only actionable save/connection errors.
    const quiet = !retry && /^(Run ready\.|Run saved\.|Starting your run)/.test(text);
    n.hidden = quiet;
    n.firstChild.textContent = quiet ? "" : text;
    document.getElementById("cp-retry").hidden = !retry;
    if (!retry && !quiet)
      setTimeout(() => {
        if (n.firstChild.textContent === text) n.hidden = true;
      }, 4000);
  }
  function rememberRun(options) {
    try {
      const body = JSON.parse(options.body);
      if (body.code && body.nonce) {
        pending.set(body.code, options.body);
        sessionStorage.setItem("gh_pending_runs", JSON.stringify([...pending]));
      }
    } catch {}
  }
  function forgetRun(options) {
    try {
      pending.delete(JSON.parse(options.body).code);
      sessionStorage.setItem("gh_pending_runs", JSON.stringify([...pending]));
    } catch {}
  }
  let launchAllowed = false,
    preparing = false,
    preparedResponse = null;
  async function prepareStart(body, launch) {
    if (preparing) return;
    const controller = new AbortController(),
      token = { controller };
    preparing = token;
    const button = document.getElementById("start"),
      old = button?.textContent,
      local = document.getElementById("cp-local");
    if (button) {
      button.disabled = true;
      button.textContent = "PREPARING RUN…";
    }
    const localResponse = () =>
      new Response(JSON.stringify({ ok: false }), {
        status: 503,
        headers: { "content-type": "application/json" },
      });
    function begin(response) {
      if (preparing !== token) return;
      preparedResponse = response;
      launchAllowed = true;
      preparing = false;
      if (local) local.hidden = true;
      if (button) {
        button.disabled = false;
        button.textContent = old;
      }
      launch();
    }
    runNotice(
      "Starting your run… You can also play offline.",
    );
    if (local) {
      local.hidden = false;
      local.onclick = () => {
        controller.abort();
        runNotice("Playing offline. This run stays on this device.");
        begin(localResponse());
      };
    }
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await window.fetch(API + "start", {
        signal: controller.signal,
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await response
        .clone()
        .json()
        .catch(() => ({}));
      if (preparing !== token) return;
      if (j.accountUnavailable)
        runNotice("This run won't save to your account.");
      else if (!response.ok)
        runNotice("Playing offline. This run stays on this device.");
      else runNotice("Run ready.");
      begin(response);
    } catch {
      if (preparing === token) {
        runNotice("Playing offline. This run stays on this device.");
        begin(localResponse());
      }
    } finally {
      clearTimeout(timeout);
    }
  }
  function consumeLaunch() {
    if (!launchAllowed) return false;
    launchAllowed = false;
    return true;
  }
  window.fetch = async (input, options = {}) => {
    let url;
    try {
      url = new URL(
        typeof input === "string" ? input : input.url,
        location.href,
      );
    } catch {
      return nativeFetch(input, options);
    }
    const api = new URL(API, location.href),
      game =
        url.origin === api.origin &&
        ["/api/start", "/api/run"].includes(url.pathname),
      post = (options.method || "GET").toUpperCase() === "POST";
    if (!game) return nativeFetch(input, options);
    if (post && url.pathname === "/api/start" && preparedResponse) {
      const cached = preparedResponse;
      preparedResponse = null;
      return cached;
    }
    if (post && url.pathname === "/api/run") rememberRun(options);
    if (post) {
      await ready;
      if (refreshPromise) await refreshPromise;
    }
    const call = () =>
      nativeFetch(input, {
        ...options,
        credentials: "include",
        headers: {
          ...(options.headers || {}),
          ...(csrf ? { "x-gh-csrf": csrf } : {}),
        },
      });
    try {
      let r = await call();
      // 403 is rejected before any route mutation. Refresh then retry at most once.
      if (post && r.status === 403) {
        await refresh();
        r = await call();
      }
      if (post && url.pathname === "/api/run") {
        if (r.ok) {
          const data = await r
            .clone()
            .json()
            .catch(() => ({}));
          if (data.accountSavePending) {
            rememberRun(options);
            runNotice(
              "Score saved online; personal account save needs retry.",
              true,
            );
          } else {
            forgetRun(options);
            runNotice(
              data.accountUnavailable
                ? "Saved on this device, not to an account."
                : "Run saved.",
            );
          }
          setTimeout(async () => {
            await backupLocal().catch(() => {});
            await refresh();
          }, 500);
        } else if ([401, 403, 409, 429].includes(r.status) || r.status >= 500) {
          rememberRun(options);
          runNotice(
            "Score save needs retry. Your result is kept on this tab.",
            true,
          );
        } else {
          forgetRun(options);
          runNotice(
            "This result could not be accepted. Your local score is still saved.",
          );
        }
      } else if (post && !r.ok)
        runNotice(
          "Online score recording is unavailable for this run. Local play still works.",
        );
      return r;
    } catch (e) {
      if (post && url.pathname === "/api/run") rememberRun(options);
      runNotice(
        "Connection lost. Local play continues; retry your pending result here.",
        pending.size > 0,
      );
      throw e;
    }
  };
  async function retryRuns() {
    for (const body of [...pending.values()]) {
      try {
        await window.fetch(API + "run", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body,
        });
      } catch {}
    }
  }
  async function request(action, data = {}) {
    if (
      ![
        "localhost",
        "127.0.0.1",
        "gtaheist.fun",
        "www.gtaheist.fun",
        "api.gtaheist.fun",
      ].includes(location.hostname)
    )
      throw Error(
        "Sign-in is unavailable here. Play still works.",
      );
    const controller = new AbortController(),
      timer = setTimeout(() => controller.abort(), 10000);
    let r;
    try {
      r = await nativeFetch(API + "campaign", {
        signal: controller.signal,
        credentials: "include",
        method: action ? "POST" : "GET",
        headers: {
          "content-type": "application/json",
          ...(csrf ? { "x-gh-csrf": csrf } : {}),
        },
        ...(action ? { body: JSON.stringify({ action, ...data }) } : {}),
      });
    } finally {
      clearTimeout(timer);
    }
    const j = await r.json();
    if (!r.ok) throw Error(j.error || "Service unavailable");
    if (j.csrf) csrf = j.csrf;
    return j;
  }
  async function checkedRequest(action, data = {}, retry = true) {
    const allowed = [
      "localhost",
      "127.0.0.1",
      "gtaheist.fun",
      "www.gtaheist.fun",
      "api.gtaheist.fun",
    ];
    if (!allowed.includes(location.hostname))
      throw Error(
        "Competition is unavailable right now. Play still works.",
      );
    const controller = new AbortController(),
      timer = setTimeout(() => controller.abort(), 8000);
    let response;
    try {
      response = await nativeFetch(API + "checked", {
        method: "POST",
        credentials: "include",
        signal: controller.signal,
        headers: { "content-type": "application/json", "x-gh-csrf": csrf },
        body: JSON.stringify({ action, ...data }),
      });
    } finally {
      clearTimeout(timer);
    }
    const result = await response.json();
    // Origin/CSRF rejects precede mutation. A single retry never bypasses ownership.
    if (response.status === 403 && retry) {
      await refresh();
      return checkedRequest(action, data, false);
    }
    if (!response.ok)
      throw Object.assign(Error(result.error || "Competition unavailable"), {
        status: response.status,
        retryAfterMs: result.retryAfterMs,
      });
    return result;
  }
  const $ = (id) => document.getElementById(id);
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text != null) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
  function keepDisplayName(raw) {
    const name = String(raw || "").trim().replace(/\s+/g, " ").slice(0, 15);
    if (!name || !/^[A-Za-z0-9_ .\-$]+$/.test(name)) return "";
    try { localStorage.setItem("gtd_name", name); } catch {}
    document.querySelectorAll("#dn0 input,#dn1 input,#dn2 input").forEach((n) => { if (!n.matches(":focus") && n.value !== name) n.value = name; });
    return name;
  }
  async function backupLocal() {
    if (!state?.signedIn)
      throw Error(
        "Sign in to save across devices. Otherwise, your save stays here.",
      );
    let backup = {};
    try {
      backup = JSON.parse(localStorage.getItem("gtd_prof") || "{}");
    } catch {}
    const typed = document.querySelector("#cp-name-slot input, #dn0 input")?.value || "";
    const name = keepDisplayName(typed) || (localStorage.getItem("gtd_name") || "").trim();
    await request("sync", {
      ...(name ? { name } : {}),
      backup: {
        best: backup.best,
        runs: backup.runs,
        badges: backup.badges,
        settings: backup.settings,
        dailyPersonal: dailyBackup(),
        preferences: preferenceBackup(),
      },
    });
  }
  function preferenceBackup() {
    const out = {};
    try {
      for (const k of [
        "gtd_mode",
        "gtd_muted",
        "gtd_station",
        "gth_diff",
        "gth_dist",
        "gth_fac",
        "gth_low",
      ]) {
        const v = localStorage.getItem(k);
        if (v !== null) out[k] = v;
      }
    } catch {}
    return out;
  }
  function dailyBackup() {
    const out = {};
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (/^gth_(dh|lev)_\d{4}-\d{2}-\d{2}$/.test(k))
          out[k] = localStorage.getItem(k);
      }
    } catch {}
    return out;
  }
  let messageTimer = 0;
  function message(text) {
    const node = $("cp-message");
    if (!node) return;
    node.textContent = text || "";
    clearTimeout(messageTimer);
    if (text) messageTimer = setTimeout(() => { if (node.textContent === text) node.textContent = ""; }, 2200);
  }
  // Milestones reference v1: Lucide v1.70.0 (ISC) children copied verbatim (see campaign-docs/SIGNIN-BRAND-PROVENANCE.md).
  const MS_LU = {grid:'<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',trophy:'<path d="M10 14.66V17a1 1 0 0 1-1 1 2 2 0 0 0-2 2v2"/><path d="M14 14.66V17a1 1 0 0 0 1 1 2 2 0 0 1 2 2v2"/><path d="M17.916 10H19.5A2.5 2.5 0 0 0 22 7.5V5a1 1 0 0 0-1-1h-3"/><path d="M4 22h16"/><path d="M6 9a6 6 0 0 0 12 0V3a1 1 0 0 0-1-1H7a1 1 0 0 0-1 1z"/><path d="M6.084 10H4.5A2.5 2.5 0 0 1 2 7.5V5a1 1 0 0 1 1-1h3"/>',check:'<path d="M20 6 9 17l-5-5"/>',lock:'<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',coins:'<path d="M13.744 17.736a6 6 0 1 1-7.48-7.48"/><path d="M15 6h1v4"/><path d="m6.134 14.768.866-.5 2 3.464"/><circle cx="16" cy="8" r="6"/>',rocket:'<path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09"/><path d="M9 12a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.4 22.4 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 .05 5 .05"/>',snowflake:'<path d="m10 20-1.25-2.5L6 18"/><path d="M10 4 8.75 6.5 6 6"/><path d="m14 20 1.25-2.5L18 18"/><path d="m14 4 1.25 2.5L18 6"/><path d="m17 21-3-6h-4"/><path d="m17 3-3 6 1.5 3"/><path d="M2 12h6.5L10 9"/><path d="m20 10-1.5 2 1.5 2"/><path d="M22 12h-6.5L14 15"/><path d="m4 10 1.5 2L4 14"/><path d="m7 21 3-6-1.5-3"/><path d="m7 3 3 6h4"/>',star:'<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"/>',info:'<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',arrow:'<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>'};
  const msLu = (name, cls) => `<svg class="cp-lu${cls ? " " + cls : ""}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${MS_LU[name]}</svg>`;
  const LB_LU = {"runs": "<path d=\"M15.6 2.7a10 10 0 1 0 5.7 5.7\"/><circle cx=\"12\" cy=\"12\" r=\"2\"/><path d=\"M13.4 10.6 19 5\"/>", "quests": "<rect width=\"8\" height=\"4\" x=\"8\" y=\"2\" rx=\"1\" ry=\"1\"/><path d=\"M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2\"/><path d=\"M12 11h4\"/><path d=\"M12 16h4\"/><path d=\"M8 11h.01\"/><path d=\"M8 16h.01\"/>", "milestones": "<path d=\"m15.477 12.89 1.515 8.526a.5.5 0 0 1-.81.47l-3.58-2.687a1 1 0 0 0-1.197 0l-3.586 2.686a.5.5 0 0 1-.81-.469l1.514-8.526\"/><circle cx=\"12\" cy=\"8\" r=\"6\"/>", "referrals": "<path d=\"M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2\"/><path d=\"M16 3.128a4 4 0 0 1 0 7.744\"/><path d=\"M22 21v-2a4 4 0 0 0-3-3.87\"/><circle cx=\"9\" cy=\"7\" r=\"4\"/>", "bag": "<path d=\"M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z\"/><path d=\"M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8\"/><path d=\"M12 18V6\"/>", "crown": "<path d=\"M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.734H5.81a1 1 0 0 1-.957-.734L2.02 6.02a.5.5 0 0 1 .798-.519l4.276 3.664a1 1 0 0 0 1.516-.294z\"/><path d=\"M5 21h14\"/>", "info": "<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M12 16v-4\"/><path d=\"M12 8h.01\"/>"};
  const lbLu = name => `<svg class="cp-lu" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${LB_LU[name]}</svg>`;
  const LB_LAUREL = '<svg class="cp-lb-laurel" viewBox="0 0 40 52" aria-hidden="true"><path d="M30 50C14 44 6 30 8 8" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><g fill="currentColor"><ellipse cx="9" cy="10" rx="3.2" ry="7" transform="rotate(-8 9 10)"/><ellipse cx="17" cy="15" rx="3.2" ry="7" transform="rotate(48 17 15)"/><ellipse cx="7" cy="21" rx="3.2" ry="7" transform="rotate(-28 7 21)"/><ellipse cx="18" cy="26" rx="3.2" ry="7" transform="rotate(58 18 26)"/><ellipse cx="9" cy="32" rx="3.2" ry="7" transform="rotate(-48 9 32)"/><ellipse cx="22" cy="36" rx="3.2" ry="7" transform="rotate(66 22 36)"/><ellipse cx="15" cy="42" rx="3.2" ry="7" transform="rotate(-64 15 42)"/></g></svg>';
  let authStep = "email", returnTab = "account", uiBusy = false, questFilter = "all", mileFilter = "all", questFromPause = false, seenMilestones = null;
  function avatarMarkup(i) {
    const id = `avatar-${String(Math.max(0, Math.min(11, i)) + 1).padStart(2, "0")}`;
    return `<img src="/game/assets/avatars/${id}.webp" width="236" height="236" alt="" draggable="false">`;
  }
  function avatarIndex() {
    return /^avatar-(0[1-9]|1[0-2])$/.test(state?.avatarId || "") ? Number(state.avatarId.slice(-2)) - 1 : 0;
  }
  let activeFeature = null, previousFocus = null, pinnedHelp = null, questOp = null, lbKey = null;
  function open(feature = "quests", afterSignIn = feature) {
    if (!document.activeElement?.closest?.(".cp-dialog")) previousFocus = document.activeElement;
    questFromPause = feature === "quests" && window.__ghQuestPause === true;
    window.__ghQuestPause = false;
    if (questFromPause) { questFilter = "all"; const list = $("cp-quests"); if (list) list.dataset.rendered = ""; }
    if (questFromPause) document.getElementById("pz")?.classList.remove("show");
    returnTab = afterSignIn;
    window.ghPause?.pause();
    showFeature(feature);
    message("");
    refresh();
  }
  function close() {
    const backToPause = questFromPause;
    questFromPause = false;
    document.querySelectorAll(".cp-dialog").forEach(n => { n.hidden = true; n.classList.remove("cp-pause-view"); });
    activeFeature = null;
    $("campaign-panel").hidden = true;
    hideHelp();
    previousFocus?.focus?.({preventScroll:true});
    if (backToPause) document.getElementById("pz")?.classList.add("show");
  }
  function showFeature(feature) {
    const target = $("cp-" + feature + "-dialog");
    if (!target) return;
    document.querySelectorAll(".cp-dialog").forEach(n => n.hidden = n !== target);
    activeFeature = feature;
    $("campaign-panel").hidden = false;
    target.querySelector(".cp-feedback").append($("cp-message"));
    hideHelp();
    target.querySelector("h2").focus({preventScroll:true});
  }
  function hideHelp() { const n = $("cp-help"); if (n) n.hidden = true; pinnedHelp=null; document.querySelectorAll(".cp-help-button[aria-describedby]").forEach(b=>b.removeAttribute("aria-describedby")); }
  function help(text, label) {
    const b = el("button", "?", "cp-help-button");
    b.type = "button";
    b.dataset.help = text;
    b.setAttribute("aria-label", label || "About this objective");
    b.setAttribute("aria-description", text);
    return b;
  }
  // Registered while this script is in <head>, before original game hotkeys.
  // Keep normal PLAY hooks byte-identical; an open dialog must not start/resume a game.
  addEventListener("keydown", e => {
    const openMenu = document.querySelector('.cp-sidebar[data-open="true"]');
    if (!activeFeature && openMenu && e.key === "Escape") {
      openMenu.dataset.open = "false";
      const fly = openMenu.querySelector("#cp-navigation"); if (fly) fly.hidden = true;
      const toggle = openMenu.querySelector(".cp-menu-toggle");
      toggle.setAttribute("aria-expanded", "false"); toggle.focus();
      e.preventDefault(); e.stopImmediatePropagation(); return;
    }
    if (!activeFeature) return;
    if (activeFeature === "leaderboard" && lbKey?.(e)) { e.preventDefault(); e.stopImmediatePropagation(); return; }
    if (e.key === "Escape") {
      if (!$("cp-help").hidden) { pinnedHelp=null;hideHelp(); } else close();
      e.preventDefault();e.stopImmediatePropagation();return;
    }
    if (e.key === "Tab") {
      const dialog=$("cp-"+activeFeature+"-dialog");
      const controls=[...dialog.querySelectorAll("button,input,a[href]")].filter(n=>!n.disabled&&n.getClientRects().length);
      const i=controls.indexOf(document.activeElement);
      if(controls.length && e.shiftKey && i<=0){controls.at(-1).focus();e.preventDefault();}
      else if(controls.length && !e.shiftKey && (i<0||i===controls.length-1)){controls[0].focus();e.preventDefault();}
    }
    // Preserve native text-input handlers/defaults; other keys must not reach game hotkeys.
    if (!e.target?.matches?.("input,textarea,select")) e.stopImmediatePropagation();
  }, true);
  function cards(target, items) {
    const root = $(target);
    const signature = JSON.stringify(items);
    if (root.dataset.rendered === signature) return;
    root.dataset.rendered = signature;
    root.replaceChildren();
    if (!items.length) {
      root.append(el("p", "Nothing in this filter yet.", "cp-quest-empty"));
      return;
    }
    for (const q of items) {
      const card = el("article", null, "cp-quest");
      const icon = el("span", null, "cp-quest-icon"); icon.setAttribute("aria-hidden","true"); icon.innerHTML = q.icon;
      const body = el("div", null, "cp-quest-body");
      const title = el("div", null, "cp-card-title");
      title.append(el("h3", q.name), help(q.help, "About " + q.name));
      const status = q.complete ? "DONE" : "IN PROGRESS";
      const meter = el("div", null, "cp-meter");
      meter.setAttribute("role", "progressbar"); meter.setAttribute("aria-label", q.name);
      meter.setAttribute("aria-valuemin", "0"); meter.setAttribute("aria-valuemax", String(q.target));
      meter.setAttribute("aria-valuenow", String(q.available ? q.current : 0));
      const fill = el("span"); fill.style.width = (q.available ? Math.min(100, q.current / q.target * 100) : 0) + "%"; meter.append(fill);
      const row = el("div", null, "cp-quest-row");
      row.append(meter, el("small", `${q.available ? q.current : "—"} / ${q.target}`, "cp-quest-count"));
      const pill = el("button", status, "cp-pill" + (q.complete ? " cp-pill-done" : ""));
      pill.type = "button";
      pill.disabled = true;
      body.append(title, el("p", q.goal), row);
      card.classList.toggle("cp-complete", !!q.complete);
      card.append(icon, body, pill);
      root.append(card);
    }
  }
  function render() {
    if (!state) return;
    if (!state.signedIn || checkedOwner !== state.accountId)
      checkedState = null;
    if ($("start")) $("start").textContent = "PLAY";
    const signed = !!state.signedIn;
    $("cp-account-nav").querySelector("span").textContent = "ACCOUNT";
    $("cp-account-heading").innerHTML = signed ? "YOUR <b>ACCOUNT</b>" : "SIGN <b>IN</b>";
    $("cp-status").textContent = "";
    $("cp-auth-state").textContent = signed ? "" : ($("cp-inviter")?.value ? "A friend invited you. Sign in to join their crew." : "New player or returning? Sign in to save your progress, quests, and avatar.");
    $("cp-account-dialog")?.classList.toggle("cp-signin-view", !signed);
    $("cp-account-dialog")?.classList.toggle("cp-account-view", signed);
    $("cp-login").hidden = signed;
    $("cp-profile").hidden = !signed;
    $("cp-logout").hidden = !signed;
    if ($("cp-logout-all")) $("cp-logout-all").hidden = true;
    $("cp-save").disabled = !signed || uiBusy;
    $("cp-send").disabled = !state.authAvailable || uiBusy;
    $("cp-verify").disabled = !state.authAvailable || uiBusy;
    $("cp-resend").disabled = !state.authAvailable || uiBusy;
    $("cp-email-step").hidden = authStep !== "email";
    $("cp-code-step").hidden = authStep !== "code";
    $("cp-google").disabled = uiBusy || !state.googleClientId;
    $("cp-google").title = state.googleClientId ? "Continue with Google" : "Google sign-in is unavailable.";
    if (!signed && state.googleClientId) window.ghMountGoogle?.(state.googleClientId);
    $("cp-google").querySelectorAll("span")[1].textContent = "CONTINUE WITH GOOGLE";
    $("cp-google-note").hidden = !!state.googleClientId;
    $("cp-wallet").disabled = uiBusy;
    $("cp-providers").hidden = false;
    $("cp-provider").textContent = state.walletSignIn || state.authAvailable ? "" : "Sign-in is unavailable right now. Play still works.";
    $("cp-code-to").textContent = "Enter the 8-digit code from your email.";
    const c = checkedState?.enabled ? checkedState : null;
    const scoreN = c ? c.rawScore : "—", questN = c ? c.completedQuests : "—", mileN = c ? c.milestoneCount : "—", friendN = Number.isSafeInteger(state.crewCount) ? state.crewCount : "—";
    $("cp-counts").hidden = true;
    $("cp-counts").textContent = c ? `Score ${scoreN} · Quests ${questN} · Milestones ${mileN} · Friends ${friendN}` : "";
    const stats = $("cp-stats");
    if (stats) {
      // Lucide v1.70.0 icons (ISC): goal, clipboard-check, award, users.
      const art = {SCORE:'<path d="M12 13V2l8 4-8 4"/><path d="M20.561 10.222a9 9 0 1 1-12.55-5.29"/><path d="M8.002 9.997a5 5 0 1 0 8.9 2.02"/>',QUESTS:'<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',MILESTONES:'<path d="m15.477 12.89 1.515 8.526a.5.5 0 0 1-.81.47l-3.58-2.687a1 1 0 0 0-1.197 0l-3.586 2.686a.5.5 0 0 1-.81-.469l1.514-8.526"/><circle cx="12" cy="8" r="6"/>',FRIENDS:'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><path d="M16 3.128a4 4 0 0 1 0 7.744"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/>'};
      stats.replaceChildren(...[["SCORE",scoreN],["QUESTS",questN],["MILESTONES",mileN],["FRIENDS",friendN]].map(([key,value]) => {
        const tile=el("span"),symbol=el("i");symbol.setAttribute("aria-hidden","true");symbol.innerHTML=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${art[key]}</svg>`;
        tile.append(symbol,el("b",String(value)),el("small",key));return tile;
      }));
    }
    const who = $("cp-login-label");
    if (who) who.textContent = state.loginLabel || "Signed in";
    const kind = $("cp-login-kind");
    if (kind) {
      const kindKey = state.loginKind === "google" ? "google" : state.loginKind === "wallet" ? "wallet" : "email";
      if (kind.dataset.kind !== kindKey) {
        kind.dataset.kind = kindKey;
        // Google: official G (see SIGNIN-BRAND-PROVENANCE.md). Wallet/email: Lucide v1.70.0 (ISC) line icons.
        kind.innerHTML = (kindKey === "google" ? '<img src="/game/assets/brand/google-g.svg" alt="" draggable="false">' : kindKey === "wallet" ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/></svg>' : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7"/><rect x="2" y="4" width="20" height="16" rx="2"/></svg>') + "<span></span>";
        kind.lastChild.textContent = kindKey === "google" ? "GOOGLE ACCOUNT" : kindKey === "wallet" ? "SOLANA WALLET" : "EMAIL ACCOUNT";
      }
    }
    const face = $("cp-avatar");
    if (face && face.dataset.i !== String(avatarIndex())) { face.dataset.i = String(avatarIndex()); face.innerHTML = avatarMarkup(avatarIndex()); }
    $("cp-instruction").textContent = questFromPause ? "These objectives update from the current run." : signed ? "City objectives stay on your record once a run completes them. Daily quests rotate at 00:00 UTC." : "Sign in, then play. Completed objectives are recorded automatically.";
    $("cp-quests-heading").innerHTML = questFromPause ? "QUESTS" : "QUEST <b>BOARD</b>";
    $("cp-quests-dialog")?.classList.toggle("cp-pause-view", questFromPause);
    $("cp-pause-note").hidden = !(window.ghCheckedCity?.active && !window.ghCheckedCity?.finished);
    $("cp-trust").textContent = c?.active?.dayPolicy === "legacy-ist-v1" ? "Older run keeps its original schedule. New cities reset 00:00 UTC." : "Daily quests reset at 00:00 UTC.";
    const descriptions = {
      "beginner/pocket-change": ["Pocket Change", "Grab 3 token pickups in one run. The coins on the road count."],
      "beginner/first-pump": ["First Pump", "Drive into the yellow Pump marker before its timer runs out."],
      "beginner/cold-stash": ["Cold Stash", "Pick up a token, then park inside a Cold Stash vault."]
    };
    const icons = {
      // Quest art: coin disc + Lucide v1.70.0 (ISC) landmark / rocket / snowflake paths, verbatim.
      "beginner/pocket-change": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#ffc21a" stroke="#e08a00" stroke-width="1.2"/><circle cx="12" cy="12" r="8.4" fill="none" stroke="#ffe27a" stroke-width=".8"/><g transform="translate(6.6 6.4) scale(.45)" fill="none" stroke="#9a5a00" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10 18v-7"/><path d="M11.119 2.205a2 2 0 0 1 1.762 0l7.84 3.846A.5.5 0 0 1 20.5 7h-17a.5.5 0 0 1-.22-.949z"/><path d="M14 18v-7"/><path d="M18 18v-7"/><path d="M3 22h18"/><path d="M6 18v-7"/></g></svg>',
      "beginner/first-pump": '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09" fill="#ffb02e" stroke="#ff7a1a"/><path d="M9 12a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.4 22.4 0 0 1-4 2z" fill="#f4f1f8" stroke="#ffffff"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 .05 5 .05" fill="#ff4a6a" stroke="#ff4a6a"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" fill="#ff4a6a" stroke="#ff4a6a"/><circle cx="16" cy="8" r="1.6" fill="#3fb7ff" stroke="none"/></svg>',
      "beginner/cold-stash": '<svg viewBox="0 0 24 24" fill="none" stroke="#f2fbff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m10 20-1.25-2.5L6 18"/><path d="M10 4 8.75 6.5 6 6"/><path d="m14 20 1.25-2.5L18 18"/><path d="m14 4 1.25 2.5L18 6"/><path d="m17 21-3-6h-4"/><path d="m17 3-3 6 1.5 3"/><path d="M2 12h6.5L10 9"/><path d="m20 10-1.5 2 1.5 2"/><path d="M22 12h-6.5L14 15"/><path d="m4 10 1.5 2L4 14"/><path d="m7 21 3-6-1.5-3"/><path d="m7 3 3 6h4"/></svg>'
    };
    const savedQuest = new Map((state?.quests || []).map((q) => [q.key, q]));
    const oneRun = new Set(["beginner/pocket-change", "beginner/first-pump", "beginner/cold-stash", "daily/heat", "daily/stash", "daily/spray", "daily/missions"]);
    const questNow = (key, fallbackTarget) => {
      const saved = savedQuest.get(key);
      const checked = c?.quests?.find((q) => q.key === key);
      const target = saved?.target || fallbackTarget;
      const complete = !!(saved?.completed || checked?.completed);
      const current = oneRun.has(key) ? (complete ? target : 0) : Math.min(target, Math.max(saved?.current || 0, complete ? target : 0));
      return { current, target, complete };
    };
    const built = Object.keys(descriptions).map(key => ({key, ...questNow(key, key === "beginner/pocket-change" ? 3 : 1)})).map(q => ({...q,
      name: descriptions[q.key]?.[0] || q.name,
      goal: descriptions[q.key]?.[1] || q.goal,
      pending: !!c?.active && !q.complete,
      available: true,
      icon: icons[q.key],
      help: {"beginner/pocket-change":"Drive over 3 token pickups before the run ends. Any of the coins on the street count.","beginner/first-pump":"A yellow marker appears on the map. Reach it before the countdown on that marker hits zero.","beginner/cold-stash":"Pick up at least one token, then stop inside a vault marked Cold Stash so the bag is banked."}[q.key]
    }));
    const dailyPool = [
      ["daily/heat", "Heat Check", "Stay at 4 stars for 60 seconds in one run.", "Hold the heat without getting busted. The star meter has to sit at 4 for a full minute."],
      ["daily/stash", "Vault Run", "Bank $10,000 in a Cold Stash.", "Park in a vault until the banked amount reaches $10,000."],
      ["daily/spray", "Pay 'n' Spray", "Use Pay 'n' Spray once at 3 stars or higher.", "Get the heat to 3 stars, then drive into a Pay 'n' Spray."],
      ["daily/lev", "Leverage Day", "Survive 2 Leverage Ups today.", "When the clock ends, take Leverage Up and last the extra minute. Do that twice today."],
      ["daily/missions", "Mission Rush", "Clear 3 missions in one run.", "Finish three mission markers before the run clock ends."]
    ];
    const dayIndex = Math.floor(Date.now() / 86400000);
    for (let i = 0; i < 3; i++) {
      const [key, name, goal, helpText] = dailyPool[(dayIndex + i) % dailyPool.length];
      const now = questNow(key, 1);
      built.push({ key, name, goal, help: helpText + " Today's three change at 00:00 UTC.", current: now.current, target: now.target, pending: false, complete: now.complete, available: true, claimable: false, icon: icons["beginner/first-pump"] });
    }
    const activeN = built.filter(q => !q.complete).length;
    const doneN = built.filter(q => q.complete).length;
    const shown = built.filter(q => questFilter === "completed" ? q.complete : questFilter === "active" ? !q.complete : true);
    // Lucide v1.70.0 (ISC): check, gift.
    const filterArt = {"cp-qf-done":'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',"cp-qf-claim":'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 7v14"/><path d="M20 11v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8"/><path d="M7.5 7a1 1 0 0 1 0-5A4.8 8 0 0 1 12 7a4.8 8 0 0 1 4.5-5 1 1 0 0 1 0 5"/><rect x="3" y="7" width="18" height="4" rx="1"/></svg>'};
    for (const [id, on, label] of [["cp-qf-all", questFilter === "all", `ALL QUESTS (${built.length})`], ["cp-qf-active", questFilter === "active", `ACTIVE (${activeN})`], ["cp-qf-done", questFilter === "completed", `COMPLETED (${doneN})`]]) {
      const b = $(id); if (!b) continue; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on));
      if (!b.querySelector("span")) b.innerHTML = (filterArt[id] || "") + "<span></span>";
      b.querySelector("span").textContent = label;
    }
    cards("cp-quests", shown);
    const more = $("cp-quest-more");
    if (more) more.hidden = true;
    const completed = Object.keys(descriptions).filter((key) => questNow(key, 1).complete).length;
    const trio = completed === 3 || !!c?.earned?.some(q => q.kind === "milestone" && q.key === "milestone/beginner-trio");
    if (signed && seenMilestones !== null && c && c.milestoneCount > seenMilestones) {
      const pop = $("cp-mile-pop");
      if (pop) { pop.hidden = false; pop.textContent = "Milestone complete. Beginner Trio is on your record."; clearTimeout(pop._t); pop._t = setTimeout(() => { pop.hidden = true; }, 4200); }
    }
    if (c) seenMilestones = c.milestoneCount;
    const msDialog = $("cp-milestones-dialog");
    if (msDialog) msDialog.dataset.msState = trio ? "done" : "active";
    $("cp-trio-state").textContent = trio ? "STAMPED" : "IN PROGRESS";
    $("cp-trio-badge").classList.toggle("cp-unlocked",trio);
    $("cp-trio-progress").textContent = `${completed} / 3`;
    $("cp-trio-progress").setAttribute("aria-label", `${completed} of 3 jobs done`);
    const mileItems = Object.entries(descriptions).map(([key, [name, goal]]) => {
      const now = questNow(key, key === "beginner/pocket-change" ? 3 : 1);
      return { key, name, goal, done: now.complete, cur: now.current, target: now.target, locked: false, tip: built.find(b => b.key === key)?.help };
    });
    const mileShown = mileItems;
    const showTrio = mileFilter === "all" || (mileFilter === "completed" ? trio : mileFilter === "active" ? !trio : false);
    $("cp-milestones").hidden = !showTrio;
    $("cp-milestone-empty").hidden = showTrio;
    $("cp-milestone-empty").textContent = mileFilter === "completed" ? "No completed milestone yet." : "No milestones in this filter.";
    for (const [id, on, label] of [["cp-mf-all", mileFilter === "all", "ALL (1)"], ["cp-mf-active", mileFilter === "active", `ACTIVE (${trio ? 0 : 1})`], ["cp-mf-done", mileFilter === "completed", `COMPLETED (${trio ? 1 : 0})`], ["cp-mf-lock", mileFilter === "locked", "LOCKED (0)"]]) {
      const b = $(id); if (!b) continue; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); (b.querySelector("span") || b).textContent = label;
    }
    const steps = $("cp-trio-steps"), stepSig = JSON.stringify(mileShown);
    if (steps.dataset.rendered !== stepSig) {
      steps.dataset.rendered = stepSig; steps.replaceChildren();
      for (const q of mileShown) {
        const row = el("li", null, "cp-ms-row");
        row.dataset.key = q.key.split("/")[1];
        row.dataset.state = q.locked ? "locked" : q.done ? "done" : "active";
        const ico = el("span", null, "cp-m-ico"); ico.setAttribute("aria-hidden", "true");
        ico.innerHTML = msLu({"beginner/pocket-change":"coins","beginner/first-pump":"rocket","beginner/cold-stash":"snowflake"}[q.key] || "star");
        const head = el("span", null, "cp-ms-title"); head.append(el("b", q.name));
        if (q.tip) head.append(help(q.tip, "About " + q.name));
        const copy = el("span", null, "cp-ms-copy"); copy.append(head, el("small", q.goal));
        const box = el("i", null, "cp-check"); box.setAttribute("aria-hidden", "true");
        if (q.done) box.innerHTML = msLu("check");
        row.append(ico, copy, el("em", `${q.locked ? "—" : q.cur} / ${q.target}`, "cp-ms-count"), box, el("span", q.locked ? "Locked" : q.done ? "Done" : "Not done yet", "cp-ms-sr"));
        row.classList.toggle("cp-done", q.done);
        steps.append(row);
      }
    }
    $("cp-milestone-note").textContent = "Stamp is permanent and stays on your crew record. No cash reward.";
    const crew = state.crewCount || 0;
    $("cp-invite-signin").hidden = signed;
    $("cp-copy").hidden = !signed || !state.invite;
    const linkBox = $("cp-link");
    linkBox.value = signed && state.invite ? `${location.origin}/game/?invite=${state.invite}` : "Sign in to get your invite link";
    linkBox.hidden = false;
    $("cp-invite-state").textContent = signed ? "Your crew will appear here once friends join." : "Sign in to start building your crew.";
    $("cp-inv-foot").hidden = signed && crew > 0;
    $("cp-crew-head").hidden = !signed || !crew;
    $("cp-crew-tab-label").textContent = `JOINED (${crew})`;
    $("cp-crew-total").textContent = String(crew);
    const crewList = $("cp-crew");
    if (crewList) {
      crewList.replaceChildren();
      crewList.hidden = !signed || !crew;
      for (const member of (state.crew || [])) {
        const row = el("div", null, "cp-crew-row");
        row.setAttribute("role", "listitem");
        const face = el("span", null, "cp-crew-face"); face.innerHTML = avatarMarkup(/^avatar-(0[1-9]|1[0-2])$/.test(member.avatarId || "") ? Number(member.avatarId.slice(-2)) - 1 : 0);
        row.append(face, el("div", null, "cp-crew-name"));
        row.lastChild.append(el("b", member.name || member.label || "Player"));
        const joined = el("span", null, "cp-joined");
        joined.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg><span>JOINED</span>';
        row.append(joined);
        crewList.append(row);
      }
    }
    $("cp-incoming").hidden = !$("cp-inviter").value;
    $("cp-incoming-note").textContent = state.inviter || state.pendingInvite ? "Invitation saved." : signed ? "A friend invited you. Accept to link your accounts." : "A friend invited you. Sign in to accept.";
    $("cp-consent-label").hidden = !signed || !!state.inviter || !!state.pendingInvite;
    $("cp-apply").hidden = !signed || !!state.inviter || !!state.pendingInvite;
    $("cp-apply").disabled = !$("cp-consent").checked || uiBusy;
    const synced = state.sync?.name;
    if (
      state.signedIn &&
      appliedAccount !== state.accountId &&
      !document.body.classList.contains("running")
    ) {
      try {
        // Hydrate once per account/device session, never on every background refresh.
        if (synced && !nameDirty) {
          localStorage.setItem("gtd_name", synced);
          document
            .querySelectorAll("#dn0 input,#dn1 input,#dn2 input")
            .forEach((n) => {
              if (!n.matches(":focus")) n.value = synced;
            });
        }
        const backup = state.sync?.untrustedLocalBackup;
        if (backup) {
          const p = JSON.parse(localStorage.getItem("gtd_prof") || "{}");
          p.best = Math.max(p.best || 0, backup.best || 0);
          p.runs = Math.max(p.runs || 0, backup.runs || 0);
          p.badges = { ...backup.badges, ...p.badges };
          for (const k of ["vaultScout", "rugPull", "exchangeHeist"])
            p.badges[k] = !!(p.badges[k] || backup.badges?.[k]);
          p.badges.dailyHit = Math.max(
            p.badges.dailyHit || 0,
            backup.badges?.dailyHit || 0,
          );
          p.settings = { ...(backup.settings || {}), ...bootSettings };
          localStorage.setItem("gtd_prof", JSON.stringify(p));
          for (const [k, v] of Object.entries(backup.dailyPersonal || {})) {
            if (
              /^gth_(dh|lev)_\d{4}-\d{2}-\d{2}$/.test(k) &&
              !(k in bootPreferences)
            )
              localStorage.setItem(k, v);
          }
        }
        for (const [k, v] of Object.entries(backup?.preferences || {}))
          if (
            [
              "gtd_mode",
              "gtd_muted",
              "gtd_station",
              "gth_diff",
              "gth_dist",
              "gth_fac",
              "gth_low",
            ].includes(k) &&
            !(k in bootPreferences)
          )
            localStorage.setItem(k, v);
        appliedAccount = state.accountId;
      } catch {}
    }
    const tag = document.getElementById("tagshow");
    if (tag && state.playerId) {
      let h = 2166136261;
      for (const c of state.playerId) {
        h ^= c.charCodeAt(0);
        h = Math.imul(h, 16777619) >>> 0;
      }
      tag.textContent = "#" + (1000 + (h % 9000));
    }

  }
  function refresh() {
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
      try {
        state = await request();
        if (state.needsGuest) {
          csrf = "";
          state = await request("guest");
        }
        if (!state.signedIn || checkedOwner !== state.accountId) {
          checkedState = null;
          checkedOwner = state.signedIn ? state.accountId : null;
        }
        if (state.signedIn)
          try {
            checkedState = await checkedRequest("profile", {}, false);
            checkedOwner = state.accountId;
          } catch {
            checkedState = null;
            checkedOwner = null;
          }
        render();
        dispatchEvent(new CustomEvent("gh-campaign-state"));
      } catch (e) {
        checkedState = null;
        checkedOwner = null;
        state = {
          signedIn: false,
          authAvailable: false,
          quests: [],
          milestones: [],
          referrals: { qualified: 0, pending: 0 },
        };
        render();
        message("");
      } finally {
        refreshPromise = null;
      }
    })();
    return refreshPromise;
  }
  function clearSharedSave(wipe = false) {
    try {
      for (const k of Object.keys(localStorage)) {
        if (
          wipe &&
          (k.startsWith("gtd_") ||
            k.startsWith("gth_") ||
            k.startsWith("gtaheist_") ||
            k.startsWith("gh_"))
        )
          localStorage.removeItem(k);
        else if (
          ["gtd_name", "gtd_prof", "gh_pending_invite"].includes(k) ||
          /^gth_(dh|lev)_/.test(k) ||
          [
            "gtd_mode",
            "gtd_muted",
            "gtd_station",
            "gth_diff",
            "gth_dist",
            "gth_fac",
            "gth_low",
          ].includes(k)
        )
          localStorage.removeItem(k);
      }
      if (wipe) {
        sessionStorage.removeItem("gh_pending_runs");
        pending.clear();
      }
    } catch {}
    document
      .querySelectorAll("#dn0 input,#dn1 input,#dn2 input")
      .forEach((n) => (n.value = ""));
    for (const id of ["cp-email", "cp-code", "cp-inviter", "cp-link"]) {
      const input = document.getElementById(id);
      if (input) input.value = "";
    }
    const displayedTag = document.getElementById("tagshow");
    if (displayedTag) displayedTag.textContent = "#GUEST";
    appliedAccount = null;
    bootSettings = {};
    for (const k of Object.keys(bootPreferences)) delete bootPreferences[k];
    nameDirty = false;
  }
  function exportLegacy() {
    const local = {};
    for (const k of Object.keys(localStorage)) {
      if (
        k.startsWith("gtd_") ||
        k.startsWith("gth_") ||
        k.startsWith("gtaheist_") ||
        k.startsWith("gh_")
      )
        local[k] = localStorage.getItem(k);
    }
    const blob = new Blob(
      [
        JSON.stringify(
          {
            warning:
              "PRIVATE: contains secret run nonces and wallet/history. Never post or share.",
            local,
            pendingRuns: [...pending],
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = "gtaheist-private-device-backup.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
  function mount() {
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = "/game/campaign.css?v=t29-candidate-v3";
    document.head.append(style);
    const menu = document.querySelector(".tcorner");
    menu.classList.add("cp-sidebar");
    menu.dataset.open = "false";
    menu.setAttribute("aria-label", "Game menu");
    const toggle = el("button", "", "ticon cp-menu-toggle");
    toggle.type = "button";
    // Owner hamburger reference (94df): scope class + ids only; native handlers are untouched.
    menu.classList.add("cp-menu-ref");
    toggle.id = "cp-menu-toggle";
    toggle.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>';
    toggle.setAttribute("aria-label", "Menu");
    toggle.setAttribute("aria-expanded", "false");
    toggle.onclick = () => {
      const expanded = menu.dataset.open !== "true";
      menu.dataset.open = String(expanded);
      toggle.setAttribute("aria-expanded", String(expanded));
      fly.hidden = !expanded;
    };
    const originalActions = el("div", null, "cp-original-actions");
    originalActions.append(...Array.from(menu.children));
    const addedActions = el("div", null, "cp-added-actions");
    const fly = el("div", null, "cp-fly");
    fly.append(originalActions, addedActions);
    fly.id = "cp-navigation";
    fly.hidden = true;
    toggle.setAttribute("aria-controls", fly.id);
    menu.append(toggle, fly);
    const closeMenu = () => { menu.dataset.open = "false"; fly.hidden = true; toggle.setAttribute("aria-expanded", "false"); };
    document.addEventListener("pointerdown", e => { if (!menu.contains(e.target)) closeMenu(); });
    document.addEventListener("focusin", e => { if (!menu.contains(e.target)) closeMenu(); });
    originalActions.addEventListener("click", e => { if (e.target.closest("button")) closeMenu(); });
    // Lucide line icons (ISC), 24-grid, rendered at 22px. Gold = gold line art in the reference; others white.
    const icons = {
      howto: '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" transform="translate(-4.2 -5.6) scale(1.35)"/><path d="M12 17h.01" transform="translate(-4.2 -5.6) scale(1.35)"/>',
      prizes: '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
      leaderboard: '<rect x="3.5" y="13" width="4" height="8" rx="1" fill="currentColor"/><rect x="10" y="8" width="4" height="13" rx="1" fill="currentColor"/><rect x="16.5" y="3" width="4" height="18" rx="1" fill="currentColor"/>',
      account: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
      quests: '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
      milestones: '<path d="m15.477 12.89 1.515 8.526a.5.5 0 0 1-.81.47l-3.58-2.687a1 1 0 0 0-1.197 0l-3.586 2.686a.5.5 0 0 1-.81-.469l1.514-8.526"/><circle cx="12" cy="8" r="6"/>',
      invite: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    };
    const gold = new Set(["prizes", "leaderboard", "quests", "milestones"]);
    const iconSvg = k => `<svg class="cp-mi${gold.has(k) ? " cp-mi-gold" : ""}" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[k]}</svg>`;
    // Native buttons keep their element, id/class and engine onclick; only the emoji label becomes icon + text.
    for (const [b, k, text] of [[originalActions.querySelector("#howbtn"), "howto", "HOW TO PLAY"], [originalActions.querySelector("#przbtn"), "prizes", "PRIZES"], [originalActions.querySelector(".lbopen"), "leaderboard", "LEADERBOARD"]]) {
      if (!b) continue;
      b.innerHTML = iconSvg(k) + "<span></span>";
      b.lastChild.textContent = text;
      b.dataset.cpIcon = k;
    }
    for (const [tab, text] of [["account","GUEST · SIGN IN"],["quests","QUESTS"],["milestones","MILESTONES"],["invite","INVITE FRIENDS"]]) {
      const b = el("button", text, "ticon cp-nav");
      b.type = "button";
      b.innerHTML = `${iconSvg(tab)}<span></span>`;
      b.querySelector("span").textContent = tab === "account" ? "ACCOUNT" : text;
      b.dataset.cpNav = tab;
      if (tab === "account") b.id = "cp-account-nav";
      b.onclick = () => {
        closeMenu();
        toggle.setAttribute("aria-expanded", "false");
        returnTab = tab;
        open(tab);
      };
      addedActions.append(b);
    }
    if ($("start")) $("start").textContent = "PLAY";
    // State-only adapter for the reviewed engine keyboard hook. NOT a dialog/container.
    const engineGuard=el("span");engineGuard.id="campaign-panel";engineGuard.hidden=true;engineGuard.style.display="none";engineGuard.setAttribute("aria-hidden","true");document.body.append(engineGuard);
    // Four independent dialogs: shared visual primitives, NEVER cross-feature tabs.
const features = {
      account: `<h2 tabindex="-1" id="cp-account-heading" class="ph">SIGN <b>IN</b></h2><p id="cp-status"></p><p id="cp-counts" hidden></p><div id="cp-login"><p id="cp-auth-state"></p><div id="cp-providers"><div class="cp-google-wrap"><button id="cp-google" type="button"><span class="cp-g" aria-hidden="true"><img src="/game/assets/brand/google-g.svg" alt="" draggable="false"></span><i class="cp-vsep" aria-hidden="true"></i><span>CONTINUE WITH GOOGLE</span><span class="cp-chev" aria-hidden="true"><svg viewBox="0 0 16 26"><path d="M3 3l10 10L3 23" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg></span></button><div id="cp-google-slot"></div></div><small id="cp-google-note" hidden>Google sign-in isn’t available yet.</small><div class="cp-or"><span>OR CONNECT A WALLET</span></div><button id="cp-wallet-backpack" class="cp-wallet-row" type="button"><span class="cp-wico" aria-hidden="true"><img src="/game/assets/brand/backpack.svg" alt="" draggable="false"></span><i class="cp-vsep" aria-hidden="true"></i><b>Backpack</b><span class="cp-chev" aria-hidden="true"><svg viewBox="0 0 16 26"><path d="M3 3l10 10L3 23" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg></span></button><button id="cp-wallet-phantom" class="cp-wallet-row" type="button"><span class="cp-wico" aria-hidden="true"><img src="/game/assets/brand/phantom.svg" alt="" draggable="false"></span><i class="cp-vsep" aria-hidden="true"></i><b>Phantom</b><span class="cp-chev" aria-hidden="true"><svg viewBox="0 0 16 26"><path d="M3 3l10 10L3 23" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg></span></button><button id="cp-wallet-other" class="cp-wallet-row" type="button"><span class="cp-wico" aria-hidden="true"><img src="/game/assets/brand/other-wallet.svg" alt="" draggable="false"></span><i class="cp-vsep" aria-hidden="true"></i><b>Other Wallet</b><small>Solflare, etc.</small><span class="cp-chev" aria-hidden="true"><svg viewBox="0 0 16 26"><path d="M3 3l10 10L3 23" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg></span></button><button id="cp-wallet" type="button" hidden>CONTINUE WITH WALLET</button><div id="cp-wallet-pick" hidden><p id="cp-wallet-note">Wallets in this browser</p><div id="cp-wallet-list"></div><button id="cp-wallet-back" class="cp-text" type="button">BACK</button></div><div class="cp-signin-foot"><button id="cp-signin-back" class="cp-text" type="button"><svg aria-hidden="true" viewBox="0 0 28 22"><path d="M26 11H4M12 2.5 3 11l9 8.5" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg><span>BACK</span></button></div></div><div id="cp-email-legacy"><div id="cp-email-step"><form id="cp-email-form"><label for="cp-email">Email</label><input id="cp-email" type="email" maxlength="254" autocomplete="email" placeholder="you@example.com" required><button id="cp-send" type="submit">SEND CODE</button></form></div><div id="cp-code-step" hidden><button id="cp-login-back" class="cp-text" type="button">← BACK</button><p id="cp-code-to"></p><form id="cp-code-form"><label for="cp-code">Email code</label><input id="cp-code" inputmode="numeric" pattern="[0-9]{8}" maxlength="8" autocomplete="one-time-code" placeholder="8-digit code" required><button id="cp-verify" type="submit">SIGN IN</button></form><button id="cp-resend" class="cp-text" type="button">RESEND CODE</button></div></div><p id="cp-provider"></p></div><div id="cp-profile" hidden><div id="cp-stats"></div><div class="cp-ident"><button type="button" id="cp-avatar" aria-label="Change profile image"></button><div><div id="cp-login-label"></div><span id="cp-login-kind"></span></div></div><div id="cp-avatar-pick" hidden></div><div id="cp-name-slot"></div><button id="cp-save">SAVE PROGRESS</button><p id="cp-save-note" class="cp-note"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg><span>Backs up your stats, progress, and settings to your account.</span></p></div><div class="cp-signout"><button id="cp-logout" type="button" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/></svg><span>SIGN OUT</span></button></div>`,
      quests: `<div class="cp-feature-heading"><button id="cp-quest-back" class="cp-text" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg><span>BACK</span></button><span class="cp-quest-mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/><path d="M8 16h.01"/></svg></span><h2 tabindex="-1" id="cp-quests-heading" class="ph">QUEST <b>BOARD</b></h2><span class="cp-help-slot" data-rule="quest"></span></div><p id="cp-instruction"></p><div id="cp-qfilters" class="cp-filters"><button id="cp-qf-all" type="button" class="on">ALL QUESTS</button><button id="cp-qf-active" type="button">ACTIVE</button><button id="cp-qf-done" type="button">COMPLETED</button></div><div id="cp-quests"></div><button id="cp-quest-more" type="button" hidden>SHOW MORE</button><small id="cp-pause-note" hidden>PAUSED · Close Quests, then tap RESUME. The pause limit still applies.</small><p class="cp-quest-foot"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg><span>A quest is done only when one run meets it.</span></p><div class="cp-competition-entry"><div id="cp-competition"></div><small id="cp-trust"></small></div><button id="cp-quest-return" type="button"><svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/></svg><span>RETURN TO PAUSE MENU</span></button>`,
      milestones: `<div class="cp-ms-head"><h2 tabindex="-1" id="cp-milestones-heading" class="ph">MILES<b>TONES</b></h2><p id="cp-milestone-lead">Complete key goals and earn permanent crew stamps.</p><div id="cp-mfilters" class="cp-filters" role="group" aria-label="Filter milestones"><button id="cp-mf-all" type="button" class="on" aria-pressed="true">${msLu("grid")}<span>ALL</span></button><button id="cp-mf-active" type="button" aria-pressed="false">${msLu("trophy")}<span>ACTIVE</span></button><button id="cp-mf-done" type="button" aria-pressed="false">${msLu("check")}<span>COMPLETED</span></button><button id="cp-mf-lock" type="button" aria-pressed="false">${msLu("lock")}<span>LOCKED</span></button></div></div><div class="cp-ms-scroll"><div id="cp-milestones"><div class="cp-stamp"><div id="cp-trio-badge" class="cp-medallion cp-ms-stamp" aria-hidden="true">${msLu("star")}</div><div class="cp-stamp-copy"><span class="cp-featured">FEATURED</span><div class="cp-card-title"><h3>CREW STAMP SET</h3><span class="cp-help-slot" data-rule="trio"></span></div><p>Finish the three city quests to earn the Beginner Trio stamp.</p><strong id="cp-trio-state"></strong></div><div class="cp-ms-progress"><small>PROGRESS</small><div id="cp-trio-progress" class="cp-trio-progress"></div></div></div><ol id="cp-trio-steps"></ol><div class="cp-reward"><span class="cp-reward-mark" aria-hidden="true">${msLu("star")}</span><i class="cp-ms-vsep" aria-hidden="true"></i><div><small>REWARD</small><h3>BEGINNER TRIO</h3></div><span class="cp-ms-stamp cp-ms-stamp-big" aria-hidden="true">${msLu("star")}</span></div><p class="cp-ms-note">${msLu("info")}<span id="cp-milestone-note"></span></p></div><p id="cp-milestone-empty" hidden></p></div><div class="cp-ms-foot"><button id="cp-view-quests" type="button"><span>VIEW QUESTS</span>${msLu("arrow")}</button></div>`,
      invite: `<header class="cp-inv-hero"><h2 tabindex="-1" id="cp-invite-heading" class="ph">INVITE <b>FRIENDS</b></h2><p class="cp-invite-lead">BRING YOUR CREW. HIT THE CITY.</p><div class="cp-inv-badge" aria-hidden="true"><svg class="cp-inv-burst" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 160" preserveAspectRatio="xMidYMid meet"><path d="M122 60L86.6 34.5" stroke="#ff2fc0" stroke-width="7" stroke-linecap="round"/><path d="M72 24 L94.7 26.8 L81.8 44.6Z" fill="#ff2fc0"/><path d="M238 60L273.9 31.2" stroke="#ff2fc0" stroke-width="7" stroke-linecap="round"/><path d="M288 20 L279.3 41.1 L265.5 23.9Z" fill="#ff2fc0"/><path d="M118 98L73.6 87.6" stroke="#fcc40c" stroke-width="6" stroke-linecap="round"/><path d="M58 84 L77.8 78.4 L73.3 97.8Z" fill="#fcc40c"/><path d="M242 96L289.4 74.6" stroke="#fcc40c" stroke-width="6" stroke-linecap="round"/><path d="M304 68 L291.7 84.5 L283.5 66.3Z" fill="#fcc40c"/><path d="M122 132L88 129.2" stroke="#ff2fc0" stroke-width="5" stroke-linecap="round"/><path d="M74 128 L90.7 120.4 L89.2 138.3Z" fill="#ff2fc0"/><path d="M238 132L272.2 137.7" stroke="#ff2fc0" stroke-width="5" stroke-linecap="round"/><path d="M286 140 L268.7 146.2 L271.7 128.5Z" fill="#ff2fc0"/></svg><span class="cp-inv-tile"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6"/><path d="M22 11h-6"/></svg></span></div></header><div class="cp-perks"><div><i aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/></svg></i><span><b>SHARE YOUR LINK</b><small>Send your personal invite link to a friend.</small></span></div><div><i aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m16 11 2 2 4-4"/><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg></i><span><b>FRIEND ACCEPTS</b><small>They sign in and choose to accept your invite.</small></span></div><div><i aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></i><span><b>BUILD YOUR CREW</b><small>Friends who accept appear in your crew list.</small></span></div></div><section class="cp-inv-linkcard"><div class="cp-inv-labelrow"><label class="cp-link-label" for="cp-link">YOUR INVITE LINK</label><span class="cp-help-slot" data-rule="invite"></span></div><div class="cp-link-row"><span class="cp-inv-chain" aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg></span><input id="cp-link" readonly aria-label="Your invite link"><button id="cp-copy" type="button"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg><span>COPY</span></button><button id="cp-invite-signin" type="button"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><path d="m10 17 5-5-5-5"/><path d="M15 12H3"/></svg><span>SIGN IN</span></button></div><p id="cp-invite-toast" class="cp-inv-toast" role="status" aria-live="polite" hidden></p></section><div id="cp-crew-head" class="cp-crew-head" hidden><span class="cp-crew-tab"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg><span id="cp-crew-tab-label">JOINED (0)</span></span><span class="cp-crew-total">TOTAL JOINED <b id="cp-crew-total">0</b></span></div><div id="cp-crew" role="list" aria-label="Your crew" hidden></div><div id="cp-inv-foot" class="cp-inv-foot"><span class="cp-inv-foot-ico" aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></span><p id="cp-invite-state"></p></div><div id="cp-incoming" class="cp-incoming" hidden><h3>YOU'RE INVITED</h3><p id="cp-incoming-note"></p><input id="cp-inviter" type="hidden" maxlength="16"><label id="cp-consent-label" class="cp-consent"><input id="cp-consent" type="checkbox">Link my account to this friend.</label><button id="cp-apply" disabled>ACCEPT INVITE</button></div>`,
      leaderboard: `<header class="cp-lb-head">${LB_LAUREL}<h2 tabindex="-1" id="cp-leaderboard-heading" class="ph">LEADERBOARD</h2>${LB_LAUREL.replace('class="cp-lb-laurel"', 'class="cp-lb-laurel cp-lb-laurel-r"')}</header><div class="cp-lb-tabs" role="tablist" aria-label="Leaderboard period"><button type="button" role="tab" id="cp-lbt-today" data-lb="today" aria-controls="cp-lb-panel">TODAY</button><button type="button" role="tab" id="cp-lbt-week" data-lb="week" aria-controls="cp-lb-panel">WEEK</button><button type="button" role="tab" id="cp-lbt-all" data-lb="all" aria-controls="cp-lb-panel">ALL TIME</button><button type="button" role="tab" id="cp-lbt-holder" data-lb="holder" aria-controls="cp-lb-panel">HOLDERS</button></div><div id="cp-lb-panel" class="cp-lb-scroll" role="tabpanel" tabindex="0" aria-live="polite"></div><p class="cp-lb-note">${lbLu("info")}<span id="cp-lb-note"></span></p>`
    };
    const feedback = el("p");feedback.id="cp-message";feedback.setAttribute("role","status");feedback.setAttribute("aria-live","polite");
    for(const [feature,markup] of Object.entries(features)) {
      const dialog=el("div",null,"ov mdl cp-dialog cp-"+feature);dialog.id="cp-"+feature+"-dialog";dialog.hidden=true;
      dialog.setAttribute("role","dialog");dialog.setAttribute("aria-modal","true");dialog.setAttribute("aria-labelledby","cp-"+feature+"-heading");
      dialog.innerHTML=`<div class="pbox cp-box"><button class="pclose cp-close" aria-label="Close" type="button">×</button>${markup}<div class="cp-feedback"></div></div>`;
      dialog.querySelector(".cp-close").onclick=close;
      dialog.onclick=e=>{if(e.target===dialog)close();};
      document.body.append(dialog);
    }
    $("cp-account-dialog").querySelector(".cp-feedback").append(feedback);
    $("cp-account-dialog").classList.add("cp-signin-view");
    $("cp-invite-dialog").classList.add("cp-invite-view");
    $("cp-invite-dialog").querySelector(".cp-close").innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
    $("cp-milestones-dialog").classList.add("cp-milestones-view");
    const lbDialog = $("cp-leaderboard-dialog");
    lbDialog.classList.add("cp-lb-view");
    lbDialog.querySelector(".cp-close").innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
    const LB_NOTE = {today: "Best bag since 00:00 UTC today. Runs are verified runs in that window.", week: "Best bag since Monday 00:00 UTC. Runs are verified runs this week.", holder: "Best bag per 500K+ token wallet in the current weekend window (UTC).", all: "Best verified bag on record."};
    const lbTabs = [...lbDialog.querySelectorAll(".cp-lb-tabs button")];
    let lbTab = "today", lbData = null, lbSeq = 0;
    const lbFmt = n => "$" + Math.round(Number(n) || 0).toLocaleString("en-US");
    const lbFace = key => { let h = 0; for (const ch of String(key || "")) h = (h * 31 + ch.codePointAt(0)) >>> 0; return h % 12; };
    const lbState = text => { const p = el("div", null, "cp-lb-state"); p.append(el("p", text)); return p; };
    function lbAllRows() {
      if (Array.isArray(lbData.allTime)) return lbData.allTime;
      const map = new Map();
      for (const x of [...(lbData.thisWeek || []), ...(lbData.today || [])]) {
        const k = x.g || x.n;
        const prev = map.get(k);
        if (!prev || Number(x.b) > Number(prev.b)) map.set(k, x);
      }
      return [...map.values()].sort((a, b) => Number(b.b) - Number(a.b)).map((x, i) => ({ ...x, r: i + 1 }));
    }
    function lbRows() {
      if (lbTab === "holder") return (lbData.holder || []).slice(0, 50).map((x, i) => ({r: i + 1, n: x.name || "anon", b: x.bag, g: x.g || "", key: x.wallet || x.name}));
      const src = lbTab === "today" ? lbData.today : lbTab === "week" ? lbData.thisWeek : lbAllRows();
      return (src || []).slice(0, 50).map((x, i) => ({r: Number(x.r) || i + 1, n: x.n || "anon", b: x.b, g: x.g || "", key: x.g || x.n}));
    }
    function lbRender() {
      for (const b of lbTabs) { const on = b.dataset.lb === lbTab; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1; }
      const panel = $("cp-lb-panel");
      panel.setAttribute("aria-labelledby", "cp-lbt-" + lbTab);
      $("cp-lb-note").textContent = LB_NOTE[lbTab] + " Quests and milestones are completed / total. BAG is in-game loot, not a payout.";
      panel.setAttribute("aria-busy", String(!lbData || !!lbData.loading));
      if (!lbData || lbData.loading) return panel.replaceChildren(lbState("Loading leaderboard…"));
      if (lbData.err) {
        const s = lbState("Leaderboard unavailable right now. Try again in a bit.");
        const retry = el("button", "RETRY", "cp-lb-retry"); retry.type = "button"; retry.onclick = lbLoad; s.append(retry);
        return panel.replaceChildren(s);
      }
      const rows = lbRows();
      if (!rows.length) return panel.replaceChildren(lbState(lbTab === "holder" ? "No holder runs this weekend yet." : lbTab === "all" ? "No verified runs yet." : "No runs yet " + (lbTab === "today" ? "today" : "this week") + ". Be first."));
      const table = el("table", null, "cp-lb-table");
      table.innerHTML = '<colgroup><col class="c-rank"><col class="c-player"><col class="c-runs"><col class="c-quests"><col class="c-ms"><col class="c-ref"><col class="c-bag"></colgroup><thead><tr><th scope="col" class="cp-lb-rank">#</th><th scope="col" class="cp-lb-player">PLAYER</th>'
        + ["runs:RUNS", "quests:QUESTS", "milestones:MILESTONES", "referrals:REFERRALS"].map(s => { const [k, t] = s.split(":"); return `<th scope="col" class="cp-lb-num">${lbLu(k)}<span>${t}</span></th>`; }).join("")
        + `<th scope="col" class="cp-lb-bag">${lbLu("bag")}<span>BAG</span></th></tr></thead><tbody></tbody>`;
      const body = table.tBodies[0];
      const statOf = x => {
        const all = lbData.stats || {};
        const st = all[x.g] || all[String(x.n || "").toLowerCase()] || {};
        const runs = lbTab === "holder" ? st.runsWeekend : lbTab === "week" ? st.runsWeek : lbTab === "all" ? (st.runsAll || Math.max(Number(st.runsWeek) || 0, Number(st.runsToday) || 0)) : st.runsToday;
        return { runs: Math.max(1, Number(runs) || 0), quests: (st.quests || 0) + "/" + (st.questTotal || 6), milestones: (st.milestones || 0) + "/" + (st.milestoneTotal || 1), referrals: st.referrals || 0 };
      };
      const num = (text, pill) => { const td = el("td", null, "cp-lb-num"); td.append(el("span", String(text), pill ? "cp-lb-pill" : "")); return td; };
      for (const x of rows) {
        const tr = el("tr", null, x.r <= 3 ? "cp-lb-top" + x.r : "");
        const rank = el("td", null, "cp-lb-rank");
        if (x.r <= 3) { const m = el("span", String(x.r), "cp-lb-medal"); if (x.r === 1) m.insertAdjacentHTML("afterbegin", `<i class="cp-lb-crown">${lbLu("crown")}</i>`); rank.append(m); }
        else rank.textContent = String(x.r);
        const who = el("td", null, "cp-lb-player"); const face = el("span", null, "cp-lb-face"); face.innerHTML = avatarMarkup(lbFace(x.key));
        who.append(face, el("span", String(x.n), "cp-lb-name"));
        const st = statOf(x);
        tr.append(rank, who, num(st.runs, false), num(st.quests, true), num(st.milestones, true), num(st.referrals, false), el("td", lbFmt(x.b), "cp-lb-bag"));
        body.append(tr);
      }
      table.prepend(el("caption", (LB_NOTE[lbTab] || "") + " BAG is in-game loot, not cash.", "cp-lb-sr"));
      panel.replaceChildren(table);
    }
    async function lbLoad() {
      const seq = ++lbSeq; lbData = {loading: 1}; lbRender();
      let next = {err: 1};
      try {
        const ctl = window.AbortController ? new AbortController() : null, to = setTimeout(() => ctl?.abort(), 6000);
        const r = await nativeFetch(API + "leaderboard", {signal: ctl?.signal});
        clearTimeout(to);
        const j = r.ok ? await r.json() : null;
        if (j && j.ok) next = j;
      } catch {}
      if (seq === lbSeq) { lbData = next; lbRender(); }
    }
    const lbSelect = (b, focus) => { lbTab = b.dataset.lb; lbRender(); if (focus) b.focus(); };
    lbTabs.forEach(b => { b.onclick = () => lbSelect(b); });
    lbKey = e => {
      const i = lbTabs.indexOf(document.activeElement);
      if (i < 0) return false;
      const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      const n = d ? lbTabs[(i + d + lbTabs.length) % lbTabs.length] : e.key === "Home" ? lbTabs[0] : e.key === "End" ? lbTabs.at(-1) : null;
      if (!n) return false;
      lbSelect(n, true); return true;
    };
    document.addEventListener("click", e => {
      if (!e.target?.closest?.(".lbopen")) return;
      e.preventDefault(); e.stopImmediatePropagation();
      closeMenu();
      open("leaderboard", returnTab);
      lbLoad();
    }, true);
    $("cp-view-quests").onclick = () => showFeature("quests");
    for (const [id, key] of [["cp-qf-all","all"],["cp-qf-active","active"],["cp-qf-done","completed"]])
      $(id).onclick = () => { questFilter = key; $("cp-quests").dataset.rendered = ""; render(); };
    for (const [id, key] of [["cp-mf-all","all"],["cp-mf-active","active"],["cp-mf-done","completed"],["cp-mf-lock","locked"]])
      $(id).onclick = () => { mileFilter = key; render(); };
    $("cp-quest-back").onclick = close;
    $("cp-quest-return").onclick = close;
    const city = $("cp-competition");
    if (city && !city.querySelector("button")) {
      const play = el("button", "ENTER THE CITY");
      play.type = "button";
      play.id = "cp-enter-city";
      play.onclick = () => {
        close();
        document.getElementById("start")?.click();
      };
      city.append(play);
    }
    const faces = $("cp-avatar-pick");
    Array.from({length:12}).forEach((_, i) => {
      const b = el("button", "", "cp-avatar-choice");
      b.type = "button";
      b.innerHTML = avatarMarkup(i);
      b.setAttribute("aria-label", `Choose avatar ${i + 1}`);
      b.onclick = () => op(async () => {
        state = await request("avatar", { avatarId: `avatar-${String(i + 1).padStart(2, "0")}` });
        faces.hidden = true;
        render();
      });
      faces.append(b);
    });
    $("cp-avatar").onclick = () => { faces.hidden = !faces.hidden; };
    const pauseQuests = document.getElementById("pquest");
    if (pauseQuests) pauseQuests.addEventListener("click", (e) => {
      e.stopPropagation();
      window.__ghQuestPause = true;
      open("quests");
    });
    const rules={quest:["Only competition runs save these objectives. Regular PLAY remains unchanged. City resets at 00:00 UTC; completed quests never reset.","About competition quests"],trio:["Claim Pocket Change, First Pump and Cold Stash. They may be earned in different city runs. The Beginner Trio stamp is added after all three claims. No cash reward.","How to unlock Beginner Trio"],invite:["Accepting a friend's invite needs your permission. Referral credit and rewards are off. Invitations do not prove unique people.","How invitations work"]};
    document.querySelectorAll(".cp-help-slot").forEach(n=>n.append(help(...rules[n.dataset.rule])));
    const tooltip=el("div",null,"cp-tooltip");tooltip.id="cp-help";tooltip.hidden=true;tooltip.setAttribute("role","tooltip");document.body.append(tooltip);

    function showHelp(b,pinned=false){if(!b?.dataset.help)return;document.querySelectorAll(".cp-help-button[aria-describedby]").forEach(n=>n.removeAttribute("aria-describedby"));b.setAttribute("aria-describedby","cp-help");tooltip.textContent=b.dataset.help;tooltip.hidden=false;pinnedHelp=pinned?b:null;const r=b.getBoundingClientRect(),t=tooltip.getBoundingClientRect();tooltip.style.left=Math.max(12,Math.min(innerWidth-t.width-12,r.left+r.width/2-t.width/2))+"px";tooltip.style.top=Math.max(12,Math.min(innerHeight-t.height-12,r.bottom+8))+"px";}
    document.addEventListener("pointerover",e=>{const b=e.target.closest?.(".cp-help-button");if(b)showHelp(b);});
    document.addEventListener("pointerout",e=>{if(e.target.closest?.(".cp-help-button")&&!pinnedHelp)hideHelp();});
    document.addEventListener("focusin",e=>{if(e.target.matches?.(".cp-help-button"))showHelp(e.target);});
    document.addEventListener("focusout",e=>{if(e.target.matches?.(".cp-help-button")&&!pinnedHelp)hideHelp();});
    document.addEventListener("click",e=>{const b=e.target.closest?.(".cp-help-button");if(b){if(pinnedHelp===b){pinnedHelp=null;hideHelp();}else showHelp(b,true);}else{pinnedHelp=null;hideHelp();}});
    addEventListener("resize",hideHelp);document.addEventListener("scroll",hideHelp,true);
    // Keep the original engine input and its handlers; only move it out of the hero.
    const name = $("dn0");
    if (name) {
      name.querySelector("label").textContent = "Display name";
      name.querySelector("small")?.remove();
      name.querySelector("input").placeholder = "Optional name";
      $("cp-name-slot").append(name);
    }
    $("cp-login-back").onclick = () => { authStep = "email"; $("cp-code").value = ""; message(""); render(); $("cp-email").focus(); };
    $("cp-invite-signin").onclick = () => { returnTab = "invite"; showFeature("account"); message(""); };
    $("cp-consent").onchange = render;
    $("cp-copy").onclick = async () => {
      const link = $("cp-link").value;
      if (!state?.signedIn || !link) return;
      const toast = (text, ok) => {
        const t = $("cp-invite-toast");
        t.innerHTML = ok ? '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>' : "";
        t.append(el("span", text));
        t.classList.toggle("cp-inv-toast-ok", !!ok);
        t.hidden = false;
        clearTimeout(t.cpHide);
        t.cpHide = setTimeout(() => { t.hidden = true; }, 1800);
      };
      try { await navigator.clipboard.writeText(link); toast("Link copied", true); }
      catch { $("cp-link").hidden = false; $("cp-link").focus(); $("cp-link").select(); toast("Link selected — copy it", false); }
    };
    const notice = el("div", null, "cp-network");
    notice.id = "cp-network";
    notice.hidden = true;
    notice.append(el("span", ""));
    const retry = el("button", "RETRY SAVE");
    retry.id = "cp-retry";
    retry.hidden = true;
    retry.onclick = retryRuns;
    notice.append(retry);
    const localPlay = el("button", "PLAY OFFLINE");
    localPlay.id = "cp-local";
    localPlay.hidden = true;
    notice.append(localPlay);
    document.body.append(notice);
    const milePop = el("div", "", "");
    milePop.id = "cp-mile-pop";
    milePop.hidden = true;
    milePop.setAttribute("role", "status");
    document.body.append(milePop);
    try {
      for (const [k, v] of JSON.parse(
        sessionStorage.getItem("gh_pending_runs") || "[]",
      ))
        pending.set(k, v);
      if (pending.size)
        runNotice("An unfinished score save is kept on this tab.", true);
    } catch {}
    document.querySelectorAll("#dn0 input,#dn1 input,#dn2 input").forEach((n) =>
      n.addEventListener("input", () => {
        nameDirty = true;
        keepDisplayName(n.value);
      }),
    );
    document.addEventListener("pointerdown", (e) => {
      if (e.target.closest?.("#cp-message")) return;
      if ($("cp-message")?.textContent) message("");
    }, true);
    const end = $("endov");
    if (end) new MutationObserver(() => {
      if (end.classList.contains("show") && window.__ghSub && end._ghQuest !== window.__ghSub) {
        end._ghQuest = window.__ghSub;
        Promise.resolve(window.__ghSub).then(() => refresh()).catch(() => {});
      }
      if (!end.classList.contains("show") || !state?.signedIn) return;
      const name = (document.querySelector("#dn0 input")?.value || state.sync?.name || localStorage.getItem("gtd_name") || "").trim();
      if (!name) return;
      try { localStorage.setItem("gtd_name", name); } catch {}
      document.querySelectorAll("#dn2 input").forEach((n) => { n.value = name; });
      $("dn2")?.classList.remove("ask");
    }).observe(end, { attributes: true, attributeFilter: ["class"] });
    const op = async (fn) => {
      if (uiBusy) return;
      uiBusy = true;
      render();
      try {
        await ready;
        if (refreshPromise) await refreshPromise;
        await fn();
        await refresh();
      } catch (e) {
        const text = e.message || "";
        message(/reject|declin|cancel|closed/i.test(text) ? "Sign-in cancelled. Nothing changed." : /wallet|google|client id|name:/i.test(text) ? text : /code|attempt|expired|throttl/i.test(text) ? "Check your code, or try again later." : /email/i.test(text) && !/unavailable|configur/i.test(text) ? "Enter one email address." : "This service is unavailable. Please try again later.");
      } finally { uiBusy = false; render(); }
    };
    questOp = op; // claim pills render outside mount(); reuse the same busy/error wrapper.
    $("cp-email-form").onsubmit = (e) => { e.preventDefault(); return op(async () => {
        const j = await request("request", { email: $("cp-email").value });
        authStep = "code";
        message("Code sent. Check your inbox.");
        render();
        $("cp-code").focus();
      }); };
    $("cp-resend").onclick = () => op(async () => {
      const j = await request("request", { email: $("cp-email").value });
      message(j.message?.includes("already") ? "Use the code already sent. It expires after 10 minutes." : "Code sent. Check your inbox.");
    });
    const knownWallets = [];
    function rememberWallet(name, provider) {
      const raw = String(name || "Wallet").trim();
      const label = /backpack/i.test(raw) ? "Backpack" : /phantom/i.test(raw) ? "Phantom" : raw;
      if (!(provider?.features?.["solana:signIn"] || provider?.features?.["solana:signMessage"]) || !provider.chains?.some(c => c.startsWith("solana:")) || knownWallets.some((w) => w.provider === provider || w.name.toLowerCase() === label.toLowerCase())) return;
      knownWallets.push({ name: label, provider });
    }
    const walletAPI = Object.freeze({register: (...wallets) => {
      wallets.forEach(w => rememberWallet(w.name || "Wallet", w));
      return () => { for (const w of wallets) { const i = knownWallets.findIndex(e => e.provider === w); if (i >= 0) knownWallets.splice(i,1); } };
    }});
    window.addEventListener("wallet-standard:register-wallet", (event) => {
      try {
        event.detail?.(walletAPI);
      } catch {}
    });
    try {
      window.dispatchEvent(new CustomEvent("wallet-standard:app-ready", { detail: walletAPI }));
    } catch {}
    function browserWallets() {
      const list = knownWallets.slice();
      const add = (name, provider) => {
        const raw = String(name || "Wallet").trim();
      const label = /backpack/i.test(raw) ? "Backpack" : /phantom/i.test(raw) ? "Phantom" : raw;
        if (typeof provider?.connect === "function" && (typeof provider?.signIn === "function" || typeof provider?.signMessage === "function") && !list.some((w) => w.provider === provider || w.name.toLowerCase() === label.toLowerCase())) list.push({ name: label, provider });
      };
      if (window.phantom?.solana?.isPhantom) add("Phantom", window.phantom.solana);
      if (window.solflare?.isSolflare) add("Solflare", window.solflare);
      if (window.backpack) add("Backpack", window.backpack);
      if (window.coinbaseSolana) add("Coinbase Wallet", window.coinbaseSolana);
      const injected = window.solana;
      if (injected) add(injected.isPhantom ? "Phantom" : injected.isSolflare ? "Solflare" : injected.isBackpack ? "Backpack" : "Browser wallet", injected);
      return list;
    }
    function bytesToB64(raw) {
      const bytes = raw instanceof Uint8Array ? raw : new Uint8Array(raw);
      let s = "";
      for (const b of bytes) s += String.fromCharCode(b);
      return btoa(s);
    }
    async function signInWithWallet(entry) {
      const provider = entry.provider;
      const standard = provider.features?.["solana:signIn"];
      if (!standard?.signIn && typeof provider.signIn !== "function")
        throw Error("This wallet does not support secure Solana sign-in. Update it or choose another wallet.");
      const challenge = await request("wallet-challenge");
      const signed = standard?.signIn
        ? (await standard.signIn(challenge.input))?.[0]
        : await provider.signIn(challenge.input);
      if (!signed?.account?.address || !signed.signedMessage || !signed.signature ||
          signed.signedMessageFormat?.kind === "offchainMessage")
        throw Error("This wallet's sign-in format is not supported. Choose another wallet.");
      state = await request("wallet-verify", {
        address: signed.account.address,
        signature: bytesToB64(signed.signature),
        signedMessage: bytesToB64(signed.signedMessage),
        signatureType: signed.signatureType || "ed25519",
      });
      message("Signed in.");
      if (returnTab !== "account") showFeature(returnTab);
    }
    function showWallets(list = browserWallets()) {
      const box = $("cp-wallet-list");
      box.replaceChildren();
      $("cp-wallet-pick").hidden = false;
      if (!list.length) {
        $("cp-wallet-note").textContent = "No Solana wallet in this browser. Add Phantom, Solflare, or Backpack, then try again.";
        return;
      }
      $("cp-wallet-note").textContent = "Wallets in this browser";
      for (const entry of list) {
        const b = el("button", entry.name, "cp-wallet-choice");
        b.type = "button";
        b.onclick = () => op(() => signInWithWallet(entry));
        box.append(b);
      }
    }
    function walletNamed(part) {
      return browserWallets().find((w) => w.name.toLowerCase().includes(part));
    }
    $("cp-wallet").onclick = () => { message(""); showWallets(); };
    $("cp-wallet-backpack").onclick = () => {
      const w = walletNamed("backpack");
      message("");
      if (!w) message("Backpack is not in this browser. Add it, then try again.");
      else op(() => signInWithWallet(w));
    };
    $("cp-wallet-phantom").onclick = () => {
      const w = walletNamed("phantom");
      message("");
      if (!w) message("Phantom is not in this browser. Add it, then try again.");
      else op(() => signInWithWallet(w));
    };
    $("cp-wallet-other").onclick = () => {
      const rest = browserWallets().filter((w) => !/backpack|phantom/i.test(w.name));
      message("");
      if (!rest.length) message("No other Solana wallet in this browser.");
      else if (rest.length === 1) op(() => signInWithWallet(rest[0]));
      else showWallets(rest);
    };
    $("cp-signin-back").onclick = () => close();
    $("cp-wallet-back").onclick = () => { $("cp-wallet-pick").hidden = true; message(""); };
    let googleReady = "";
    function mountGoogle(id) {
      if (!id || googleReady === id || googleReady === "loading") return;
      const start = async () => {
        if (!window.google?.accounts?.id || googleReady === id) return;
        googleReady = "loading";
        try {
          const challenge = await request("google-challenge");
          google.accounts.id.initialize({
            client_id: id,
            nonce: challenge.nonce,
            auto_select: false,
            callback: (resp) => op(async () => {
              state = await request("google", { credential: resp.credential });
              googleReady = "";
              message("Signed in.");
              if (returnTab !== "account") showFeature(returnTab);
            }),
          });
          const slot = $("cp-google-slot");
          slot.replaceChildren();
          google.accounts.id.renderButton(slot, {
            type: "standard",
            theme: "filled_black",
            size: "large",
            text: "continue_with",
            shape: "rectangular",
            width: Math.max(280, Math.round($("cp-google").clientWidth || slot.parentElement?.clientWidth || 360)),
            logo_alignment: "left",
          });
          googleReady = id;
        } catch (e) {
          googleReady = "";
          message(e?.message || "Google sign-in could not start.");
        }
      };
      if (window.google?.accounts?.id) start();
      else if (!document.querySelector("script[data-gh-google]")) {
        const s = document.createElement("script");
        s.src = "https://accounts.google.com/gsi/client";
        s.async = true;
        s.dataset.ghGoogle = "1";
        s.onload = () => start();
        s.onerror = () => message("Google could not be reached. Try again later.");
        document.head.append(s);
      }
    }
    window.ghMountGoogle = mountGoogle;
    $("cp-google").onclick = () => {
      if (!state?.googleClientId) message("Google sign-in is not configured on this server.");
      else mountGoogle(state.googleClientId);
    };
    $("cp-code-form").onsubmit = (e) => { e.preventDefault(); return op(async () => {
        state = await request("verify", {
          email: $("cp-email").value,
          code: $("cp-code").value,
        });
        $("cp-code").value = "";
        render();
        authStep = "email";
        $("cp-consent").checked = false;
        if (returnTab !== "account") showFeature(returnTab);
        message("Signed in.");
      }); };
    $("cp-save").onclick = () =>
      op(async () => {
        await backupLocal();
        message("Progress saved.");
      });
    let logoutAll = false;
    async function signout(wipe) {
      const departure = window.ghCheckedCity?.beforeSignout?.();
      if (departure === false) return;
      if (
        wipe &&
        !window.confirm(
          "Permanently remove legacy prize codes, wallet, local history and pending results? These are not fully cloud-synced. Cancel unless your private backup is saved.",
        )
      )
        return;
      await request("logout", { all: logoutAll });
      window.ghCheckedCity?.afterSignout?.();
      csrf = "";
      googleReady = "";
      $("cp-google-slot").replaceChildren();
      state = null;
      $("cp-profile").hidden = true; $("cp-login").hidden = false;
      $("cp-logout").hidden = true; if ($("cp-logout-all")) $("cp-logout-all").hidden = true;
      $("cp-login-label").textContent = ""; $("cp-stats").replaceChildren();
      $("cp-crew").replaceChildren(); $("cp-avatar-pick").hidden = true;
      $("cp-email").value = ""; $("cp-code").value = "";
      checkedState = null;
      checkedOwner = null;
      clearSharedSave(wipe);
      if ($("cp-logout-choice")) $("cp-logout-choice").hidden = true;
      message("Signed out.");
    }
    $("cp-logout").onclick = () => { logoutAll = false; op(() => signout(false)); };
    $("cp-apply").onclick = () =>
      op(async () => {
        if (!state?.signedIn || !$("cp-consent").checked) return;
        await request("pending-invite", {
          invite: $("cp-inviter").value,
          consent: true,
        });
        try {
          localStorage.removeItem("gh_pending_invite");
        } catch {}
        message(
          "Invitation saved. Referral credit is currently off.",
        );
      });
    const inv = new URLSearchParams(location.search).get("invite");
    if (inv && /^[\w-]{16}$/.test(inv)) {
      try {
        localStorage.setItem(
          "gh_pending_invite",
          JSON.stringify({ code: inv, expires: Date.now() + 7 * 86400000 }),
        );
      } catch {}
      $("cp-inviter").value = inv;
    } else {
      try {
        const v = JSON.parse(
          localStorage.getItem("gh_pending_invite") || "null",
        );
        if (v && v.expires > Date.now()) $("cp-inviter").value = v.code;
      } catch {}
    }
    // Optional shortcuts in settings/end screens. Never auto-open or block a run.
    for (const id of ["set"]) {
      const target = $(id)?.querySelector(".sbox,.endbox") || $(id);
      if (target) {
        const b = el("button", "ACCOUNT", "cp-shortcut");
        b.onclick = (e) => {
          e.stopPropagation();
          open("account");
        };
        target.append(b);
      }
    }
    const openedFromInvite = new URLSearchParams(location.search).get("invite");
    ready = refresh().then(() => {
      if (!openedFromInvite || openedFromInvite !== $("cp-inviter").value) return;
      if (!state?.signedIn) open("account", "invite");
      else if (!state.inviter) open("invite");
    });
    window.ghCampaign = {
      open,
      close,
      refresh,
      prepareStart,
      consumeLaunch,
      playerId: () => state?.playerId || null,
      accountId: () => state?.accountId || null,
      signedIn: () => !!state?.signedIn,
      checkedProfile: () =>
        state?.signedIn && checkedOwner === state.accountId
          ? checkedState
          : null,
      checked: async (action, data = {}) => {
        await ready;
        if (refreshPromise) await refreshPromise;
        return checkedRequest(action, data);
      },
    };
    dispatchEvent(new Event("gh-campaign-mounted"));
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
