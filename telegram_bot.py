#!/usr/bin/env python3
"""Telegram wrapper for the GTA Heist wanted-mode controller."""
from __future__ import annotations
import asyncio, logging, os, shlex
from pathlib import Path
from typing import Any
import aiohttp
from dotenv import load_dotenv
from runner import run

load_dotenv(); LOG=logging.getLogger("gtaheist")
HELP=("GTA Heist controller\n\n"
      "/Play <username> <wallet address> [target score] [time limit seconds]\n"
      "Example: /Play anon#9788 5UTJ... 6000000000 90\n"
      "/stop — cancel the active run\n/help")

class Bot:
    def __init__(self, token: str):
        self.base=f"https://api.telegram.org/bot{token}"; self.task: asyncio.Task|None=None; self.chat: str|None=None
    async def call(self,s,method,payload):
        async with s.post(self.base+'/'+method,json=payload) as r:
            data=await r.json(content_type=None)
            if r.status>=400 or not data.get('ok'): raise RuntimeError(data)
            return data.get('result')
    async def send(self,s,chat,text): await self.call(s,'sendMessage',{'chat_id':chat,'text':text})
    async def photo(self,s,chat,path,caption):
        form=aiohttp.FormData(); form.add_field('chat_id',chat); form.add_field('caption',caption)
        form.add_field('photo',open(path,'rb'),filename=Path(path).name,content_type='image/png')
        async with s.post(self.base+'/sendPhoto',data=form) as r:
            if r.status>=400: raise RuntimeError(await r.text())
    def parse(self,arg: str):
        p=shlex.split(arg)
        if len(p)<2 or len(p)>4: raise ValueError('Use /Play <username> <wallet address> [target score] [time limit seconds].')
        target=int(p[2]) if len(p)>=3 else int(os.getenv('GTAHEIST_DEFAULT_TARGET','6000000000'))
        limit=float(p[3]) if len(p)>=4 else float(os.getenv('GTAHEIST_DEFAULT_TIME_LIMIT','90'))
        if not 1<=target<=10**15: raise ValueError('Target score must be between 1 and 1,000,000,000,000,000.')
        if not 1<=limit<=90: raise ValueError('Time limit must be between 1 and 90 seconds.')
        return p[0],p[1],target,limit
    async def handle(self,s,msg):
        text=(msg.get('text') or '').strip(); chat=str(msg.get('chat',{}).get('id',''))
        if not chat: return
        cmd,_,arg=text.partition(' '); cmd=cmd.split('@')[0].lower()
        if cmd in ('/start','/help'): await self.send(s,chat,HELP); return
        if cmd=='/stop':
            if self.task and not self.task.done(): self.task.cancel(); await self.send(s,chat,'Cancellation requested for the active GTA Heist run.')
            else: await self.send(s,chat,'No active run.')
            return
        if cmd!='/play': return
        if self.task and not self.task.done(): await self.send(s,chat,'A run is already active. Use /stop first.'); return
        try: username,wallet,target,limit=self.parse(arg)
        except Exception as e: await self.send(s,chat,str(e)); return
        self.chat=chat
        await self.send(s,chat,f'Starting WANTED mode for {username}. Target: ${target:,}; limit: {limit:g}s. The server will issue and bind the run code.')
        async def job():
            try:
                result=await run(username,wallet,target,limit,False)
                r=result['run']['last']; bind=result['binding']; card=result['card_path']
                verified=bool(bind.get('body',{}).get('verified')) or bind.get('status') == 200
                status='verified' if verified else 'not verified'
                await self.send(s,chat,f"Run finished ({status}). Code: {r.get('code') or 'unknown'}\nBag: ${r.get('bag',0):,}\nWanted: {r.get('want',0)}★\nPicks: {r.get('picks',0)}\nWallet binding: HTTP {bind.get('status')}")
                if verified:
                    await self.photo(s,chat,card,'GTA Heist result card')
            except asyncio.CancelledError: await self.send(s,chat,'Run cancelled. No result was submitted by the controller.')
            except Exception as e: LOG.exception('run failed'); await self.send(s,chat,f'Run failed: {type(e).__name__}: {e}')
        self.task=asyncio.create_task(job())
    async def loop(self):
        async with aiohttp.ClientSession() as s:
            off=0
            while True:
                updates=await self.call(s,'getUpdates',{'timeout':25,'offset':off})
                for u in updates or []:
                    off=max(off,int(u['update_id'])+1); await self.handle(s,u.get('message',{}))

def main():
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token: raise SystemExit('Set TELEGRAM_BOT_TOKEN')
    logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'))
    asyncio.run(Bot(token).loop())
if __name__=='__main__': main()
