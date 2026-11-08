// GTA Heist share card in the game: renders the run's card (same drawCard as the server), and shares it.
//  phone : navigator.share({files:[png], text, url})  (the card goes straight into the X app)
//  PC    : copy the PNG to the clipboard + toast, then open the X post. The file downloads only from the Download Card button.
//  both  : the X post links /c/<code>?t=<signed token>, whose big card image is rendered by the server
import { drawCard, cardModel, pickQuote, tierFor, FONT_HEAD, FONT_QUOTE } from "/game/card.mjs";
const A = "/game/assets/", TIERS = ["liquidated", "rekt", "small-rekt", "small-win", "superb-win"];
const imgs = {}, $ = i => document.getElementById(i);
let ready = null, cur = null; // cur: {code, model, blob, png (Promise<Blob>), file, preview}
function load(src) { return new Promise(r => { const i = new Image(); i.decoding = "async"; i.onload = () => r(i); i.onerror = () => r(null); i.src = src; }); }
function assets() {
  if (ready) return ready;
  const fonts = [[FONT_HEAD, "fonts/Anton.woff2", {}], [FONT_QUOTE, "fonts/ArimoBI.woff2", { style: "italic", weight: "700" }]].map(([f, u, o]) => {
    try { const ff = new FontFace(f, "url(" + A + u + ")", o); document.fonts.add(ff); return ff.load().catch(() => null); } catch { return null; }
  });
  const pics = TIERS.flatMap(t => [load(A + "cards/" + t + ".webp").then(i => imgs["a/" + t] = i), load(A + "cards/bg-" + t + ".png").then(i => imgs["b/" + t] = i)]);
  return ready = Promise.all([...fonts, ...pics]);
}
const S = () => window.__dc && __dc.S, D = () => window.__dc || {};
// real events from this run -> card data
function data(l) {
  const d = D(), kind = l.kind || (l.caught ? "wasted" : "passed"), bag = Math.max(0, Math.round(l.bag || 0)), tier = tierFor(bag, kind);
  let swamp = 0;
  try { const p = d.ART && d.ART.pepe; swamp = l.caught && p && l.p && Math.hypot(l.p.x - p.x, l.p.z - p.z) < p.R + 4 ? 1 : 0; } catch {}
  const ev = { kind, cops: l.copsOut | 0, swamp, lev: l.sum && l.sum.lev, hit: l.hitBy, stashNo: l.stashNo | 0, rugs: l.rugN | 0, rugheist: !!l.rugDone,
    heist: !!l.heist, stash: l.sum ? l.sum.bank : 0, scout: !!l.vaultScout, missions: l.dh ? l.dh.missions | 0 : 0 };
  const qn = pickQuote(ev, tier), stars = Math.max(l.maxW | 0, l.want | 0);
  let name = "", tag = "";
  try { name = d.ghName ? d.ghName() : ""; tag = d.ghTag ? d.ghTag() : ""; } catch {}
  return { bag, kind, mode: d.ghMode ? d.ghMode() : "degen", dist: l.rh ? "rh" : "degen", stars, name: name || "anon", tag, code: l.code || "", q: qn.q, n: qn.n };
}
function canvas(m, W, H) { const c = document.createElement("canvas"); c.width = W; c.height = H; drawCard(c.getContext("2d"), W, H, m, { art: imgs["a/" + m.theme.art], bg: imgs["b/" + m.tier] }); return c; }
const okAssets = () => TIERS.every(t => imgs["a/" + t] && imgs["b/" + t]);
// called by the end screen (NT). Sets l.cardMeta for /api/run and paints the end-card image. Returns false if not ready.
function build() {
  const l = S(); if (!l) return false;
  const d = data(l); l.cardMeta = { k: d.kind, s: d.stars, q: d.q, n: d.n };
  if (!okAssets()) { assets().then(() => S() === l && l.code === d.code && paint(l, d) && warmSoon(l)); return false; }
  paint(l, d); warmSoon(l); return true;
}
// pre-warm the link preview: once the server returns the signed /c/ link, fetch the page + card image through the
// public URL (server side via /api/warm, which warms the edge X's crawler hits, and here, which warms the player's edge).
const API = (location.hostname === "localhost" || location.hostname === "127.0.0.1") ? "" : "https://api.gtaheist.fun";
const SITE = API ? "https://gtaheist.fun" : "";
const warmed = new Set();
function warmSoon(l, tries = 0) {
  if (!l || S() !== l || !l.code || warmed.has(l.code)) return;
  const m = /^\/c\/(GH-[A-Z0-9]{6})\?t=([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)$/.exec(l.shareUrl || "");
  if (!m || m[1] !== l.code) { if (tries < 40) setTimeout(() => warmSoon(l, tries + 1), 500); return; }
  warmed.add(l.code);
  try { fetch(API + "/api/warm?code=" + m[1] + "&t=" + m[2], { keepalive: true }).catch(() => {}); } catch {}
  try { const i = new Image(); i.decoding = "async"; i.src = (SITE || "") + "/c/" + m[1] + "/" + m[2] + ".jpg"; } catch {}
}
function paint(l, d) {
  const m = cardModel(d), prev = canvas(m, 1200, 630), url = prev.toDataURL("image/jpeg", 0.9);
  // the 2048px share PNG is heavy (draw + encode can block ~0.5-1s on phones), so it is made after the end screen
  // settles, in an idle slot. Share/Save force it at once if they come first.
  let go, made = false; const png = new Promise(r => { go = r; });
  const make = () => { if (made) return png; made = true; const big = canvas(m, 2048, 1152); big.toBlob(b => go(b), "image/png"); return png; };
  const me = cur = { code: d.code, model: m, png, make, blob: null, preview: url };
  png.then(b => { if (cur === me) cur.blob = b; });
  const idle = window.requestIdleCallback ? f => requestIdleCallback(f, { timeout: 2500 }) : f => setTimeout(f, 50);
  setTimeout(() => idle(() => { if (cur === me) make(); }), 1500);
  const card = $("card"); if (card) card.src = url;
  return true;
}
// refresh after a wallet bind etc.
function show() { const l = S(); if (l && cur && cur.code === l.code) { const c = $("card"); c && (c.src = cur.preview); return true; } return build(); }
const fname = () => "gtaheist-" + ((cur && cur.code) || "run").replace(/[^A-Za-z0-9-]/g, "") + ".png";
async function blob() { if (!cur) build(); return cur ? cur.blob || await (cur.make ? cur.make() : cur.png) : null; }
function download(b) {
  try { const u = URL.createObjectURL(b), a = document.createElement("a"); a.href = u; a.download = fname(); a.rel = "noopener"; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 4e4); return true; } catch { return false; }
}
let tt = 0;
function toast(t) {
  let e = $("ghtoast"); if (!e) { e = document.createElement("div"); e.id = "ghtoast"; e.setAttribute("role", "status"); document.body.appendChild(e); }
  e.textContent = t; e.classList.add("show"); clearTimeout(tt); tt = setTimeout(() => e.classList.remove("show"), 5200);
}
function shareLink() { const l = S(); return l && l.shareUrl && l.code && l.shareUrl.indexOf("/c/" + l.code) === 0 ? (SITE || location.origin) + l.shareUrl : ""; }
const mobile = () => matchMedia("(pointer: coarse)").matches || /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || (navigator.maxTouchPoints > 1 && /Macintosh/.test(navigator.userAgent));
// wait (briefly) for the run submit so the post can carry the signed /c/ link
function waitLink(ms) { const l = S(); if (!l || !l.code || l.off || shareLink() || l.verified === false) return Promise.resolve(); return Promise.race([Promise.resolve(window.__ghSub).catch(() => {}), new Promise(r => setTimeout(r, ms))]); }
// text: the X post text built by ghDoShare; fallbackUrl: the old intent url param (CFG url)
async function share(text, fallbackUrl) {
  if (!cur || cur.code !== (S() || {}).code) build();
  const phone = mobile() && navigator.share && navigator.canShare && window.File;
  // PC: start the clipboard write right inside the click (Safari needs that), before any await
  let clip = null;
  if (!phone) try { if (navigator.clipboard && window.ClipboardItem && cur) clip = navigator.clipboard.write([new ClipboardItem({ "image/png": cur.blob || (cur.make ? cur.make() : cur.png) })]).then(() => true, () => false); } catch { clip = null; }
  if (!shareLink()) await waitLink(phone ? 600 : 900);
  const url = shareLink() || fallbackUrl || "";
  // headline, run code, then the link on its own line (same text on PC and phone)
  const full = url ? text + "\n" + url : text;
  const intent = "https://x.com/intent/post?text=" + encodeURIComponent(full);
  if (phone) {
    try {
      const b = await blob();
      const file = b && new File([b], fname(), { type: "image/png" });
      const pay = { files: [file], text: full };
      if (file && navigator.canShare(pay)) { await navigator.share(pay); window.ghWm && ghWm.close(); return "share"; }
    } catch (e) {
      if (e && e.name === "AbortError") return "cancel";
      // the tap got "used up" while we waited: one more tap shares straight away
      if (e && e.name === "NotAllowedError" && again(text, fallbackUrl)) return "retry";
    }
  }
  const copied = clip ? await Promise.race([clip, new Promise(r => setTimeout(() => r(false), 1500))]) : false;
  toast(copied ? "Card copied, paste it into your post (Ctrl/Cmd+V)" : "Opening your post");
  window.ghOpenX(intent);
  return copied ? "copy" : "intent";
}
function again(text, u) {
  const wm = $("wm"), b = $("wmshare"); if (!wm || !b) return false;
  ["wmin", "wmsave", "wmskip", "wmopen"].forEach(i => $(i) && ($(i).hidden = true));
  const m = $("wmmsg"); m && (m.textContent = "Card ready. Tap to share it.", m.className = "good");
  b.hidden = false; b.onclick = e => { e.preventDefault(); e.stopPropagation(); b.hidden = true; share(text, u); };
  wm.classList.add("show"); return true;
}
async function save() { const b = await blob(); if (b && download(b)) toast("Card saved as " + fname()); }
// the tier the card shows, for the post headline (same tierFor as the card)
function tier() { const l = S(); return l ? tierFor(Math.max(0, Math.round(l.bag || 0)), l.kind || (l.caught ? "wasted" : "passed")) : ""; }
window.ghCard = { build, show, share, save, blob, assets, data, tier, get cur() { return cur; } };
assets();
// the retry button only lives as long as the popup
const wmEl = $("wm"), wsh = $("wmshare");
wmEl && wsh && new MutationObserver(() => { if (!wmEl.classList.contains("show")) wsh.hidden = true; }).observe(wmEl, { attributes: true, attributeFilter: ["class"] });
