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
  let simulationStart = null, lastPlayer = null, stuckFrames = 0, lastTarget = null, lastPlanAt = 0;
  let escapingFromPolice = false, stopReason = null, lastPicks = null, lastMissions = null, lastCopBand = null;
  let escapeState = 'clear', escapeEnteredAt = null, escapeClearSince = null;
  let lastCopDistance = null, lastCopSampleAt = null, copClosingSpeed = 0, timeToContact = null;
  let recoveryUntil = 0, recoveryAttempts = 0, recoveryPhase = 0;
  let recoveryStartAt = null, recoveryStartPos = null, recoveryCooldownUntil = 0, recoveryFailures = 0;
  const history = [], frames = [], events = [];
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
      missions:Number(s.dh&&s.dh.missions||0),caught:!!s.caught,kind:s.kind||null,
      ghP:window.__ghP,visibility:document.visibilityState};
  };
  const safe = (target,s) => target && !s.cops.some(c=>distance(c,target)<45) && !s.hazards.some(h=>distance(h,target)<14);
  const candidates = s => {
    if(!s.player || s.threat>=.92) return [];
    const candidates=[];
    if(s.mission) candidates.push({kind:'mission',...s.mission});
    if(s.bag>=5000) s.stashes.forEach(x=>candidates.push({kind:'stash',...x}));
    s.coins.forEach(x=>candidates.push({kind:'coin',x:x.x,z:x.z,userData:x.userData||{}}));
    if(s.vault&&!s.heist) candidates.push({kind:'vault',...s.vault});
    if(s.rugHeist&&!s.rugDone) candidates.push({kind:'rug_heist',...s.rugHeist});
    const base={mission:140,stash:165,vault:105,rug_heist:95};
    const tokenBase={$PUMP:120,$PEPE:105,$WIF:90,$BONK:80};
    return candidates.filter(x=>safe(x,s)).map(x=>{
      const value=x.kind==='coin'?(tokenBase[x.userData&&x.userData.tok]||70):(base[x.kind]||0);
      const copDistance=s.cops.length?Math.min(...s.cops.map(c=>distance(c,x))):Infinity;
      const copPenalty=Number.isFinite(copDistance)?Math.max(0,80-copDistance)*.3:0;
      return {...x,priority:value/(1+distance(x,s.player)/100)-s.threat*20-copPenalty};
    }).sort((a,b)=>b.priority-a.priority);
  };
  const present=(target,s)=>{
    const near=(items)=>items.some(x=>distance(x,target)<=8);
    if(target.kind==='coin') return near(s.coins);
    if(target.kind==='mission') return !!s.mission&&distance(s.mission,target)<=8;
    if(target.kind==='stash') return s.bag>=5000&&near(s.stashes);
    if(target.kind==='vault') return !!s.vault&&!s.heist&&distance(s.vault,target)<=8;
    if(target.kind==='rug_heist') return !!s.rugHeist&&!s.rugDone&&distance(s.rugHeist,target)<=8;
    return false;
  };
  const sameTarget=(a,b)=>!!a&&!!b&&a.kind===b.kind&&distance(a,b)<=8;
  const objectiveHeading=(player,target,cops)=>{
    const goal=target?{x:target.x-player.x,z:target.z-player.z}:null;
    const goalLength=goal?Math.hypot(goal.x,goal.z):0;
    const gx=goalLength>1e-9?goal.x/goalLength:0, gz=goalLength>1e-9?goal.z/goalLength:0;
    const immediate=cops.some(c=>distance(player,c)<22);
    let fx=immediate?0:gx, fz=immediate?0:gz, nearestDistance=Infinity, nearestAway=null;
    const span=100-22;
    for(const cop of cops){
      const dx=player.x-cop.x,dz=player.z-cop.z,d=Math.hypot(dx,dz);
      const ax=d>1e-9?dx/d:0,az=d>1e-9?dz/d:-1;
      if(d<nearestDistance){nearestDistance=d;nearestAway={x:ax,z:az};}
      if(d>=100) continue;
      const proximity=Math.max(0,Math.min(1,(100-d)/span)),strength=.85*proximity*proximity;
      const tx=-ax,tz=-az,alignment=goalLength>1e-9?Math.max(0,Math.min(1,gx*tx+gz*tz)):0;
      const cross=gx*tz-gz*tx,side=cross>=0?1:-1;
      const tangentX=-az*side,tangentZ=ax*side;
      fx+=strength*(ax+alignment*tangentX);fz+=strength*(az+alignment*tangentZ);
    }
    if(Math.hypot(fx,fz)<=1e-9){if(!nearestAway||(!immediate&&nearestDistance>=100))return null;fx=nearestAway.x;fz=nearestAway.z;}
    return Math.atan2(fx,fz);
  };
  const plan=(s,now)=>{
    const options=candidates(s), best=options[0]||null;
    const current=lastTarget&&options.find(x=>sameTarget(x,lastTarget));
    if(!current || !present(lastTarget,s) || !safe(lastTarget,s)) lastTarget=best;
    else if(now-lastPlanAt>=500){
      const margin=Math.max(8,Math.abs(current.priority)*.15);
      if(best&&!sameTarget(best,current)&&best.priority>current.priority+margin) lastTarget=best;
      else lastTarget=current;
    } else if(current) lastTarget=current;
    if(now-lastPlanAt>=500||!lastPlanAt) lastPlanAt=now;
    return lastTarget;
  };
  const tick = () => {
    const now=performance.now(), s=snapshot(), wallElapsed=(now-wallStart)/1000;
    if(simulationStart===null && Number.isFinite(s.time)) simulationStart=s.time;
    const simElapsed=simulationStart===null?0:Math.max(0,simulationStart-s.time);
    if(lastPicks===null) lastPicks=s.picks;
    if(s.picks>lastPicks) events.push({type:'pickup',count:s.picks-lastPicks,picks:s.picks,simulationElapsed:simElapsed});
    if(lastMissions===null) lastMissions=s.missions;
    if(s.missions>lastMissions) events.push({type:'mission_progress',count:s.missions-lastMissions,missions:s.missions,simulationElapsed:simElapsed});
    lastPicks=s.picks; lastMissions=s.missions;
    const copBand=s.nearestCopDistance===null?'none':s.nearestCopDistance<28?'critical':s.nearestCopDistance<45?'danger':s.nearestCopDistance<62?'caution':'clear';
    if(copBand!==lastCopBand){events.push({type:'cop_proximity',band:copBand,distance:s.nearestCopDistance,simulationElapsed:simElapsed});lastCopBand=copBand;}
    if(lastCopDistance!==null&&s.nearestCopDistance!==null&&lastCopSampleAt!==null){
      const sampleDt=Math.max(.05,(now-lastCopSampleAt)/1000);
      copClosingSpeed=(lastCopDistance-s.nearestCopDistance)/sampleDt;
      timeToContact=copClosingSpeed>0?s.nearestCopDistance/copClosingSpeed:null;
    } else {copClosingSpeed=0;timeToContact=null;}
    lastCopDistance=s.nearestCopDistance; lastCopSampleAt=now;
    if(lastPlayer && distance(lastPlayer,s.player)<2 && s.speed<2) stuckFrames++; else stuckFrames=0;
    lastPlayer={x:s.player.x,z:s.player.z};
    if(!s.running||s.over){if(!stopReason)stopReason=s.caught?'caught':(s.kind||'official_terminal');clean();}
    else if(s.bag>=targetScore){stopReason='target_score';clean();d.finish();}
    else if(simElapsed>=timeLimit){stopReason='simulation_time_limit';clean();d.wasted('time limit');}
    else if(wallElapsed>=Math.max(timeLimit*4,timeLimit+120)){stopReason='browser_safety_watchdog';clean();d.wasted('browser safety limit');}
    const priorTarget=lastTarget;
    const shouldPrepareEscape=!!(s.nearestCopDistance!==null &&
      (s.nearestCopDistance<55 || copClosingSpeed>8 || (timeToContact!==null&&timeToContact<3)));
    const shouldHardEscape=!!(s.nearestCopDistance!==null &&
      (s.nearestCopDistance<40 ||
       (timeToContact!==null&&timeToContact<2.5) ||
       copClosingSpeed>18 ||
       (copClosingSpeed>10&&s.speed<12)));
    if(shouldHardEscape && escapeState!=='hard_escape'){
      escapeState='hard_escape'; escapeEnteredAt=simElapsed; escapeClearSince=null;
      events.push({type:'escape_state',state:escapeState,reason:'hard-threat',distance:s.nearestCopDistance,timeToContact,simulationElapsed:simElapsed});
    } else if(shouldPrepareEscape && escapeState==='clear'){
      escapeState='escape'; escapeEnteredAt=simElapsed; escapeClearSince=null;
      events.push({type:'escape_state',state:escapeState,reason:'approach-or-distance',distance:s.nearestCopDistance,copClosingSpeed,timeToContact,simulationElapsed:simElapsed});
    } else if(escapeState!=='clear' && (s.nearestCopDistance===null || s.nearestCopDistance>75) && copClosingSpeed<=0){
      if(escapeClearSince===null) escapeClearSince=now;
      if(now-escapeClearSince>=1000){
        escapeState='clear'; escapingFromPolice=false; escapeClearSince=null;
        events.push({type:'escape_state',state:escapeState,reason:'released',distance:s.nearestCopDistance,simulationElapsed:simElapsed});
      }
    } else if(escapeState!=='clear'){escapeClearSince=null;}
    escapingFromPolice=escapeState!=='clear';
    const target=(!s.running||s.over)?lastTarget:(escapingFromPolice?null:plan(s,now));
    if(escapingFromPolice) lastTarget=null;
    if((priorTarget||target)&&!sameTarget(priorTarget,target)) events.push({type:'target_switch',from:priorTarget&&priorTarget.kind||null,to:target&&target.kind||null,simulationElapsed:simElapsed});
    const frame={wallElapsed,simulationElapsed:simElapsed,frameTime:now,...s,target,stuckFrames,
      escapeState,copClosingSpeed,timeToContact,recoveryAttempts,belowSpeed:s.speed<2};
    history.push(frame); frames.push(frame); if(frames.length>120) frames.shift();
    if(!s.running||s.over||stopReason==='target_score'||stopReason==='simulation_time_limit'||stopReason==='browser_safety_watchdog') return;
    const nearest=s.cops.map(c=>({c,d:distance(c,s.player)})).sort((a,b)=>a.d-b.d)[0];
    let desired=objectiveHeading(s.player,escapeState==='clear'?lastTarget:null,s.cops);
    if(desired===null) desired=s.player.h;
    if(recoveryStartAt!==null && now>=recoveryUntil){
      const progress=recoveryStartPos?distance(recoveryStartPos,s.player):0;
      if(progress<4) recoveryFailures++; else recoveryFailures=0;
      events.push({type:'recovery_end',attempt:recoveryAttempts,progress,success:progress>=4,
        failures:recoveryFailures,simulationElapsed:simElapsed});
      recoveryStartAt=null; recoveryStartPos=null; recoveryCooldownUntil=now+Math.min(1800,450*(recoveryFailures+1));
      stuckFrames=0;
    }
    if(stuckFrames>=8 && recoveryStartAt===null && now>=recoveryCooldownUntil){
      recoveryAttempts++; recoveryPhase=recoveryFailures>=2?2:(recoveryAttempts-1)%3;
      recoveryUntil=now+(recoveryPhase===2?700:450); recoveryStartAt=now; recoveryStartPos={x:s.player.x,z:s.player.z};
      events.push({type:'recovery_start',attempt:recoveryAttempts,phase:recoveryPhase,escapeState,
        failures:recoveryFailures,simulationElapsed:simElapsed});
    }
    if(recoveryStartAt!==null && now<recoveryUntil){
      const side=(recoveryAttempts%2===1)?1:0;
      keys.left=side; keys.right=side?0:1; keys.drift=1;
      keys.down=recoveryPhase===0?1:0; keys.up=recoveryPhase===0?0:1;
      keys.boost=((escapeState!=='clear'&&s.nearestCopDistance!==null&&s.nearestCopDistance>3)||recoveryPhase===2)?1:0;
      frame.input={...keys}; return;
    }
    const delta=(desired-s.player.h+Math.PI)%(2*Math.PI)-Math.PI;
    const emergency=!!(nearest&&nearest.d<100);
    keys.up=1;keys.down=0;
    // Official telemetry shows left increases heading and right decreases it.
    keys.left=delta>.12?1:0;keys.right=delta<-.12?1:0;keys.drift=Math.abs(delta)>1?1:0;
    const openEscapeLane=escapeState!=='clear' && (!nearest || nearest.d>3);
    keys.boost=(s.want<2&&Math.abs(delta)<.5&&
      (escapeState==='clear' ? s.threat<.45 : openEscapeLane))?1:0; frame.input={...keys};
  };
  const timer=setInterval(tick,50); tick();
  return new Promise(resolve=>{const finish=()=>{clearInterval(timer);clean();const last=snapshot();last.terminalReason=stopReason||(last.caught?'caught':last.kind||'official_terminal');resolve({last,history:history.slice(-240),frames:frames.slice(-120),events,wallElapsed:(performance.now()-wallStart)/1000,simulationStart});};
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


def summarize_controller_diagnostics(controller: dict[str, Any]) -> dict[str, Any]:
    """Condense observed controller events without inferring unobserved outcomes."""
    events = controller.get("events") or []
    history = controller.get("history") or []
    last = controller.get("last") or {}
    escape_events = [e for e in events if e.get("type") == "escape_state"]
    recovery_events = [e for e in events if e.get("type") == "recovery_start"]
    threat_switches = sum(
        1 for e in events
        if e.get("type") == "target_switch"
        and any(
            (f.get("simulationElapsed") or 0) == e.get("simulationElapsed")
            and (f.get("threat") or 0) >= 0.35
            for f in history
        )
    )
    low_speed = [f for f in history if f.get("belowSpeed") or f.get("speed", 999) < 2]
    closing = [float(f["copClosingSpeed"]) for f in history if f.get("copClosingSpeed") is not None]
    contact_times = [float(f["timeToContact"]) for f in history if f.get("timeToContact") is not None]
    return {
        "pickups_observed": sum(int(e.get("count", 0)) for e in events if e.get("type") == "pickup"),
        "missions_observed": sum(int(e.get("count", 0)) for e in events if e.get("type") == "mission_progress"),
        "target_switches": sum(1 for e in events if e.get("type") == "target_switch"),
        "cop_proximity_transitions": [
            {"band": e.get("band"), "distance": e.get("distance"), "simulationElapsed": e.get("simulationElapsed")}
            for e in events if e.get("type") == "cop_proximity"
        ],
        "minimum_cop_distance": min(
            (float(f["nearestCopDistance"]) for f in history if f.get("nearestCopDistance") is not None),
            default=None,
        ),
        "maximum_threat": max((float(f.get("threat", 0)) for f in history), default=0.0),
        "escape_state_transitions": [
            {"state": e.get("state"), "reason": e.get("reason"),
             "distance": e.get("distance"), "simulationElapsed": e.get("simulationElapsed")}
            for e in escape_events
        ],
        "first_escape_time": next((e.get("simulationElapsed") for e in escape_events), None),
        "recovery_attempts": len(recovery_events),
        "low_speed_frames": len(low_speed),
        "low_speed_fraction": len(low_speed) / len(history) if history else 0.0,
        "maximum_cop_closing_speed": max(closing, default=0.0),
        "minimum_time_to_contact": min(contact_times, default=None),
        "target_switches_during_threat": threat_switches,
        "terminal_reason": last.get("terminalReason"),
        "terminal_kind": last.get("kind"),
        "caught_flag": last.get("caught"),
    }


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
