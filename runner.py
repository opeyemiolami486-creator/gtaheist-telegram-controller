#!/usr/bin/env python3
"""Run the real GTA Heist browser game in wanted mode and capture its official card."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

SITE = os.getenv("GTAHEIST_SITE_URL", "https://www.gtaheist.fun/game/")
API = os.getenv("GTAHEIST_API_URL", "https://api.gtaheist.fun")

CONTROLLER_JS = r"""
({targetScore, timeLimit}) => {
  const d = window.__dc, keys = d.keys, wallStart = performance.now();
  let simulationStart = null, lastPlayer = null, stuckFrames = 0, lastTarget = null;
  const history = [], frames = [];
  const clean = () => { for (const k of ['up','down','left','right','drift','boost']) keys[k] = 0; };
  const point = x => x && Number.isFinite(x.x) && Number.isFinite(x.z) ? {x:x.x,z:x.z} : null;
  const distance = (a,b) => a && b ? Math.hypot(a.x-b.x,a.z-b.z) : Infinity;
  const snapshot = () => {
    const s=d.S||{}, p=s.p||{}, velocity={x:Number(p.vx||p.dx||0),z:Number(p.vz||p.dz||0)};
    const coins=(d.coins||[]).map(c=>({...point(c.position),userData:c.userData||{}})).filter(c=>Number.isFinite(c.x));
    const stashes=(d.stashes||[]).map(x=>({x:x.x,z:x.z})).filter(x=>Number.isFinite(x.x));
    const mission=point(d.marker&&d.marker.position);
    const cops=(d.cops||[]).map(c=>({x:c.x,z:c.z,vx:c.vx||c.dx||0,vz:c.vz||c.dz||0})).filter(c=>Number.isFinite(c.x));
    const hazards=[...(d.spikes||[]),...(d.roadblocks||[]),...(d.rugs||[]),...(d.hazards||[])].map(x=>point(x.position||x)).filter(Boolean);
    const nearest=cops.map(c=>({c,d:distance(c,p)})).sort((a,b)=>a.d-b.d)[0];
    const threat=nearest?Math.max(0,Math.min(1,1-nearest.d/90)):0;
    return {running:!!s.run,over:!!s.over,bag:Math.round(s.bag||0),time:Number(s.time||0),t:s.t,ts:s.ts,
      paused:!!s.paused, want:s.want||0,stars:s.stars||0, mission:s.mission&&mission?mission:null,
      player:{x:p.x,z:p.z,h:p.h},velocity,speed:Number(p.speed||Math.hypot(velocity.x,velocity.z)||0),coins,stashes,
      vault:Number.isFinite(d.HX)&&Number.isFinite(d.HZ)?{x:d.HX,z:d.HZ}:null,
      rugHeist:Number.isFinite(d.GX)&&Number.isFinite(d.GZ)?{x:d.GX,z:d.GZ}:null,cops,hazards,threat,
      nearestCopDistance:nearest?nearest.d:null,code:s.code||(s.srv&&s.srv.code)||null,nonce:(s.srv&&s.srv.nonce)||null,
      bank:Math.round(s.bank||0),picks:s.picks||0,heist:!!s.heist,rugDone:!!s.rugDone,
      ghP:window.__ghP,visibility:document.visibilityState};
  };
  const safe = (target,s) => target && !s.cops.some(c=>distance(c,target)<45) && !s.hazards.some(h=>distance(h,target)<14);
  const select = s => {
    if (s.want>=3 || s.threat>=.92) return null;
    const candidates=[];
    if(s.mission) candidates.push({kind:'mission',...s.mission,priority:1000});
    if(s.bag>=1000) s.stashes.forEach(x=>candidates.push({kind:'stash',...x,priority:900-distance(x,s.player)}));
    s.coins.forEach(x=>{const tok=x.userData&&x.userData.tok; const bonus={$PUMP:60,$PEPE:50,$WIF:35,$BONK:30}[tok]||10; candidates.push({kind:'coin',x:x.x,z:x.z,priority:bonus-distance(x,s.player)*.05});});
    if(s.vault) candidates.push({kind:'vault',...s.vault,priority:75});
    if(s.rugHeist) candidates.push({kind:'rug_heist',...s.rugHeist,priority:75});
    return candidates.filter(x=>safe(x,s)).sort((a,b)=>b.priority-a.priority)[0]||null;
  };
  const tick = () => {
    const s=snapshot(), wallElapsed=(performance.now()-wallStart)/1000;
    if(simulationStart===null && Number.isFinite(s.time)) simulationStart=s.time;
    const simElapsed=simulationStart===null?0:Math.max(0,simulationStart-s.time);
    if(lastPlayer && distance(lastPlayer,s.player)<2 && s.speed<2) stuckFrames++; else stuckFrames=0;
    lastPlayer={x:s.player.x,z:s.player.z};
    const frame={wallElapsed,simulationElapsed:simElapsed,frameTime:performance.now(),...s,target:lastTarget,stuckFrames};
    history.push(frame); frames.push(frame); if(frames.length>120) frames.shift();
    if(!s.running||s.over){clean();return;}
    if(s.bag>=targetScore){clean();d.finish();return;}
    if(simElapsed>=timeLimit){clean();d.wasted('time limit');return;}
    if(wallElapsed>=Math.max(timeLimit*4,timeLimit+120)){clean();d.wasted('browser safety limit');return;}
    if(!lastTarget || !safe(lastTarget,s) || (lastTarget.kind==='mission'&&!s.mission)) lastTarget=select(s);
    const nearest=s.cops.map(c=>({c,d:distance(c,s.player)})).sort((a,b)=>a.d-b.d)[0];
    let desired=lastTarget?Math.atan2(lastTarget.x-s.player.x,lastTarget.z-s.player.z):s.player.h;
    if(nearest&&nearest.d<62){const away=Math.atan2(s.player.x-nearest.c.x,s.player.z-nearest.c.z); desired=nearest.d<34?away:away*.78+desired*.22;}
    if(stuckFrames>=12){keys.up=0;keys.down=1;keys.left=(Math.floor(stuckFrames/20)%2)===0?1:0;keys.right=keys.left?0:1;keys.drift=1;keys.boost=0;frame.input={...keys};return;}
    const delta=(desired-s.player.h+Math.PI)%(2*Math.PI)-Math.PI;
    keys.up=1;keys.down=(s.threat>.86&&nearest&&nearest.d<28)?1:0;
    keys.left=delta<-.12?1:0;keys.right=delta>.12?1:0;keys.drift=Math.abs(delta)>1?1:0;
    keys.boost=(s.threat<.45&&s.want<2&&Math.abs(delta)<.5)?1:0; frame.input={...keys};
  };
  const timer=setInterval(tick,50); tick();
  return new Promise(resolve=>{const finish=()=>{clearInterval(timer);clean();resolve({last:snapshot(),history:history.slice(-240),frames:frames.slice(-120),wallElapsed:(performance.now()-wallStart)/1000,simulationStart});};
    const wait=()=>{const s=snapshot();if(!s.running||s.over)finish();else setTimeout(wait,100);}; wait();});
}
"""

CAPTURE_JS = r"""
() => {
  window.__ghDiagnostics={startedAt:performance.now(),requests:[],responses:[],visibility:document.visibilityState};
  const original=window.fetch;
  window.fetch=async(...args)=>{
    const input=args[0], init=args[1]||{}, url=typeof input==='string'?input:(input&&input.url)||String(input);
    let payload=init.body;
    if(payload==null && input && input.body) payload=input.body;
    const event={url,method:init.method||(input&&input.method)||'GET',payload:typeof payload==='string'?payload:null,at:performance.now()};
    window.__ghDiagnostics.requests.push(event);
    const response=await original(...args);
    const clone=response.clone(); let body=''; try{body=await clone.text();}catch(e){}
    window.__ghDiagnostics.responses.push({url,status:response.status,body,at:performance.now()});
    return response;
  };
}
"""


def captured_run_events(diagnostics: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the untouched request payloads and response bodies for /api/run."""
    diagnostics = diagnostics or {}
    requests = [item for item in diagnostics.get("requests", []) if "/api/run" in item.get("url", "")]
    responses = [item for item in diagnostics.get("responses", []) if "/api/run" in item.get("url", "")]
    return requests, responses


async def run(username: str, wallet: str, target_score: int, time_limit: float,
             headed: bool = False, out_dir: str = "run-artifacts") -> dict[str, Any]:
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=not headed,args=["--disable-background-timer-throttling","--disable-backgrounding-occluded-windows","--disable-renderer-backgrounding","--disable-features=CalculateNativeWinOcclusion"])
        context=await browser.new_context(viewport={"width":640,"height":360},device_scale_factor=1)
        page=await context.new_page(); await page.goto(SITE,wait_until="domcontentloaded",timeout=60000)
        await page.evaluate("([wallet])=>{localStorage.removeItem('gtd_name');localStorage.setItem('gtd_mode','pro');localStorage.setItem('gth_low','1');localStorage.setItem('gth_wallet',wallet);}",[wallet])
        await page.reload(wait_until="domcontentloaded",timeout=60000)
        await page.wait_for_function("()=>window.__dc&&document.querySelector('#start')&&!document.querySelector('#start').disabled",timeout=60000)
        await page.evaluate("()=>window.__dc&&window.__dc.setMode&&window.__dc.setMode('pro')")
        # Install capture before /api/start so the complete official request/response chain is retained.
        await page.evaluate(CAPTURE_JS)
        await page.locator('#diff button[data-d="wanted"]').click(force=True); await page.locator('#start').click()
        await page.wait_for_function("()=>window.__dc&&window.__dc.S&&window.__dc.S.run",timeout=15000)
        await page.wait_for_function("()=>window.__dc.S.srv&&window.__dc.S.srv.code&&window.__dc.S.srv.nonce",timeout=10000)
        await page.wait_for_timeout(100)
        controller=await page.evaluate(CONTROLLER_JS,{"targetScore":target_score,"timeLimit":time_limit})
        await page.wait_for_timeout(3000)
        await page.evaluate("(name)=>{localStorage.setItem('gtd_name',name);window.__dc&&window.__dc.bw&&window.__dc.bw();}",username)
        await page.wait_for_timeout(2500)
        binding=await page.evaluate("async({api})=>{const d=window.__dc,s=d.S;try{d.bw();}catch(e){};const until=Date.now()+6000;while(s.verified==null&&Date.now()<until)await new Promise(r=>setTimeout(r,200));if(s.verified!==true)return {status:409,body:{ok:false,error:'run not verified by game',verified:s.verified}};const r=await fetch(api+'/api/bind',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({code:s.code||(s.srv&&s.srv.code),nonce:s.nonce||(s.srv&&s.srv.nonce),wallet:localStorage.getItem('gth_wallet')})});return {status:r.status,body:await r.json().catch(()=>null)};}",{"api":API})
        diagnostics=await page.evaluate("()=>({diag:window.__ghDiagnostics||null,state:(()=>{const s=window.__dc&&window.__dc.S||{};return {time:s.time,t:s.t,ts:s.ts,paused:s.paused,ghP:window.__ghP,visibility:document.visibilityState,verified:s.verified};})()})")
        controller["diagnostics"]=diagnostics
        run_requests,run_responses=captured_run_events(diagnostics.get("diag"))
        controller["run_request_payloads"]=run_requests; controller["run_responses"]=run_responses
        await page.evaluate("()=>window.__dc&&window.__dc.card&&window.__dc.card()"); await page.wait_for_timeout(1200)
        code=controller.get("last",{}).get("code") or "run"; card_path=out/f"{code}-card.png"
        try:
            async with page.expect_download(timeout=10000) as download_info: await page.locator('#savecard').click(force=True)
            download=await download_info.value; card_path=out/(download.suggested_filename or card_path.name); await download.save_as(str(card_path))
        except Exception: await page.screenshot(path=str(card_path))
        result={"username":username,"wallet":wallet,"target_score":target_score,"time_limit":time_limit,"binding":binding,"run":controller,"card_path":str(card_path)}
        (out/"last-result.json").write_text(json.dumps(result,indent=2))
        await browser.close(); return result


def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument('--username',required=True); ap.add_argument('--wallet',required=True)
    ap.add_argument('--target',type=int,default=int(os.getenv('GTAHEIST_DEFAULT_TARGET','6000000000')))
    ap.add_argument('--time-limit',type=float,default=float(os.getenv('GTAHEIST_DEFAULT_TIME_LIMIT','90')))
    ap.add_argument('--headed',type=lambda x:x.lower()=='true',default=False); ap.add_argument('--out-dir',default='run-artifacts')
    args=ap.parse_args(); print(json.dumps(asyncio.run(run(args.username,args.wallet,args.target,args.time_limit,args.headed,args.out_dir)),indent=2))


if __name__=='__main__': main()
