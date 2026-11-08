#!/usr/bin/env python3
"""Run the real GTA Heist browser game in wanted mode and capture its card."""
from __future__ import annotations
import argparse, asyncio, json, os, re, time
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright
from planner import choose_target, steering

SITE = os.getenv("GTAHEIST_SITE_URL", "https://www.gtaheist.fun/game/")
API = os.getenv("GTAHEIST_API_URL", "https://api.gtaheist.fun")

CONTROLLER_JS = r"""
({targetScore, timeLimit}) => {
  const d = window.__dc;
  const keys = d.keys;
  const started = performance.now();
  const clean = () => { for (const k of ['up','down','left','right','drift','boost']) keys[k] = 0; };
  const point = x => x && Number.isFinite(x.x) && Number.isFinite(x.z) ? {x:x.x,z:x.z} : null;
  const snapshot = () => {
    const s = d.S || {}, p = s.p || {};
    const coins = (d.coins || []).map(c => ({...(point(c.position)||{}), userData:c.userData||{}})).filter(c=>Number.isFinite(c.x));
    const stashes = (d.stashes || []).map(x => ({x:x.x,z:x.z})).filter(x=>Number.isFinite(x.x));
    const mission = point(d.marker && d.marker.position);
    const vault = Number.isFinite(d.HX) && Number.isFinite(d.HZ) ? {x:d.HX,z:d.HZ} : null;
    const rugHeist = Number.isFinite(d.GX) && Number.isFinite(d.GZ) ? {x:d.GX,z:d.GZ} : null;
    const cops = (d.cops || []).map(c => ({x:c.x,z:c.z})).filter(c=>Number.isFinite(c.x));
    const threat = cops.reduce((m,c)=>Math.max(m, Math.max(0, 1-Math.hypot(c.x-p.x,c.z-p.z)/90)), 0);
    return {running:!!s.run, over:!!s.over, bag:Math.round(s.bag||0), time:s.time||0, want:s.want||0, stars:s.stars||0, mission: s.mission && mission ? mission : null, player:{x:p.x,z:p.z,h:p.h}, coins, stashes, vault, rugHeist, cops, threat, code:s.code || (s.srv&&s.srv.code) || null, nonce:(s.srv&&s.srv.nonce)||null, bank:Math.round(s.bank||0), picks:s.picks||0, heist:!!s.heist, rugDone:!!s.rugDone};
  };
  let last = snapshot(), lastTarget = null, history = [];
  const tick = () => {
    const s = snapshot(); last = s;
    const elapsed = (performance.now()-started)/1000;
    history.push({t:elapsed,bag:s.bag,want:s.want,picks:s.picks,bank:s.bank,heist:s.heist});
    if (!s.running || s.over) { clean(); return; }
    if (s.bag >= targetScore) { clean(); d.finish(); return; }
    if (elapsed >= timeLimit) { clean(); d.wasted('time limit'); return; }
    // Keep the real game in its normal PRO input path.
    let target = null;
    if (s.mission) target = {kind:'mission',x:s.mission.x,z:s.mission.z,priority:1000};
    else if (s.bag >= 5000 && s.stashes.length) {
      const q = s.stashes.slice().sort((a,b)=>Math.hypot(a.x-s.player.x,a.z-s.player.z)-Math.hypot(b.x-s.player.x,b.z-s.player.z))[0];
      target = {kind:'stash',x:q.x,z:q.z,priority:900};
    } else if (s.coins.length) {
      const q = s.coins.slice().sort((a,b)=>Math.hypot(a.x-s.player.x,a.z-s.player.z)-Math.hypot(b.x-s.player.x,b.z-s.player.z))[0];
      target = {kind:'coin',x:q.x,z:q.z,priority:100};
    } else if (s.vault) target = {kind:'vault',x:s.vault.x,z:s.vault.z,priority:80};
    else if (s.rugHeist) target = {kind:'rug_heist',x:s.rugHeist.x,z:s.rugHeist.z,priority:70};
    if (target) lastTarget = target;
    const t = lastTarget;
    if (!t) { keys.up=1; keys.boost=1; return; }
    const desired = Math.atan2(t.x-s.player.x, t.z-s.player.z);
    const delta = (desired-s.player.h+Math.PI)%(2*Math.PI)-Math.PI;
    keys.up=1; keys.down=(s.threat>.86 && Math.abs(delta)>1.25)?1:0;
    keys.left=delta < -.12 ? 1 : 0; keys.right=delta > .12 ? 1 : 0;
    keys.drift=Math.abs(delta)>1.0 ? 1 : 0;
    keys.boost=(s.threat<.65 && Math.abs(delta)<.5) ? 1 : 0;
  };
  const timer = setInterval(tick, 50); tick();
  return new Promise(resolve => {
    const finish = () => { clearInterval(timer); clean(); resolve({last, history:history.slice(-120)}); };
    const wait = () => { const s=snapshot(); if(!s.running || s.over) finish(); else setTimeout(wait,100); };
    wait();
  });
}
"""

async def run(username: str, wallet: str, target_score: int, time_limit: float, headed: bool = False, out_dir: str = "run-artifacts") -> dict[str, Any]:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed, args=["--disable-gpu", "--use-gl=swiftshader"])
        context = await browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
        page = await context.new_page()
        await page.goto(SITE, wait_until="domcontentloaded", timeout=60000)
        await page.evaluate("([name,wallet]) => { localStorage.setItem('gtd_name',name); localStorage.setItem('gtd_mode','pro'); localStorage.setItem('gth_wallet',wallet); }", [username, wallet])
        await page.reload(wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_function("() => window.__dc && document.querySelector('#start') && !document.querySelector('#start').disabled", timeout=60000)
        await page.evaluate("() => window.__dc && window.__dc.setMode && window.__dc.setMode('pro')")
        await page.locator('#diff button[data-d="wanted"]').click(force=True)
        await page.locator('#start').click()
        await page.wait_for_function("() => window.__dc && window.__dc.S && window.__dc.S.run", timeout=15000)
        await page.wait_for_function("() => window.__dc.S.srv && window.__dc.S.srv.code && window.__dc.S.srv.nonce", timeout=10000)
        await page.wait_for_timeout(100)
        run_result = await page.evaluate(CONTROLLER_JS, {"targetScore": target_score, "timeLimit": time_limit})
        await page.wait_for_timeout(4500)
        binding = await page.evaluate("async ({api}) => { const d=window.__dc, s=d.S; try{ d.bw(); }catch(e){}; const until=Date.now()+6000; while(s.verified==null && Date.now()<until) await new Promise(r=>setTimeout(r,200)); if(s.verified!==true) return {status:409,body:{ok:false,error:'run not verified by game',verified:s.verified}}; const r=await fetch(api+'/api/bind',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({code:s.code || (s.srv&&s.srv.code),nonce:s.nonce || (s.srv&&s.srv.nonce),wallet:localStorage.getItem('gth_wallet')})}); return {status:r.status,body:await r.json().catch(()=>null)}; }", {"api": API})
        await page.evaluate("() => window.__dc && window.__dc.card && window.__dc.card()")
        await page.wait_for_timeout(1200)
        card_path = out / f"{run_result['last'].get('code') or 'run'}-card.png"
        try:
            await page.locator('#card').screenshot(path=str(card_path), timeout=10000)
        except Exception:
            await page.screenshot(path=str(card_path))
        result = {"username":username,"wallet":wallet,"target_score":target_score,"time_limit":time_limit,"binding":binding,"run":run_result,"card_path":str(card_path)}
        (out / "last-result.json").write_text(json.dumps(result, indent=2))
        await browser.close()
        return result

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--username',required=True); ap.add_argument('--wallet',required=True)
    ap.add_argument('--target',type=int,default=int(os.getenv('GTAHEIST_DEFAULT_TARGET','6000000000')))
    ap.add_argument('--time-limit',type=float,default=float(os.getenv('GTAHEIST_DEFAULT_TIME_LIMIT','90')))
    ap.add_argument('--headed',type=lambda x:x.lower()=='true',default=False)
    ap.add_argument('--out-dir',default='run-artifacts')
    args=ap.parse_args(); print(json.dumps(asyncio.run(run(args.username,args.wallet,args.target,args.time_limit,args.headed,args.out_dir)),indent=2))
if __name__=='__main__': main()
