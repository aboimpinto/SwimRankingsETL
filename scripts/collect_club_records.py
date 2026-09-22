#!/usr/bin/env python3
"""Collect official category XLSX files using an operator-opened desktop browser.

Launch normal Chromium with --remote-debugging-port=9334 and a dedicated profile,
complete any verification/login manually, then attach. Never export browser cookies.
"""
import argparse
import base64
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from club_record_baselines import AGES, read_export, source_url


def collect(cdp, output):
    if urlparse(cdp).hostname not in ('127.0.0.1','localhost','::1'):
        raise ValueError('Attach only to the local operator browser')
    from playwright.sync_api import sync_playwright
    output.mkdir(parents=True,exist_ok=True); output.chmod(0o700)
    manifest=output/'manifest.json'
    items=json.loads(manifest.read_text()) if manifest.exists() else []
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp(cdp)
        context=browser.contexts[0]
        page=next((t for t in context.pages if urlparse(t.url).hostname=='www.swimrankings.net'),None) or context.new_page()
        for course in ('LCM','SCM'):
            for gender in ('F','M'):
                for age in AGES:
                    url=source_url(course,gender,age); filename=f'{course}_{gender}_{age}.xlsx'; target=output/filename
                    if target.exists():
                        read_export(target,url)
                    else:
                        response=page.goto(url,wait_until='domcontentloaded',timeout=60000)
                        if not response or response.status!=200 or page.locator('img[src*="icon.xls"]').count()!=1:
                            raise RuntimeError('Export unavailable; complete browser verification/login or retry later. Partial downloads preserved.')
                        # Download through the authenticated browser network stack. Streaming
                        # the response avoids Snap browser filesystem/download restrictions.
                        result=page.evaluate("""async()=>{
                          const url=new URL(document.querySelector('img[src*=\"icon.xls\"]').closest('a').href);
                          if(url.origin!==location.origin || !url.pathname.startsWith('/services/RankingXls/')) throw Error('Unexpected export URL');
                          const r=await fetch(url,{credentials:'include'});
                          const data=new Uint8Array(await r.arrayBuffer());
                          if(!r.ok || data.length>50*1024*1024) throw Error('Export unavailable');
                          let text=''; for(let i=0;i<data.length;i+=8192) text+=String.fromCharCode(...data.subarray(i,i+8192));
                          return btoa(text);
                        }""")
                        part=output/(filename+'.part');part.write_bytes(base64.b64decode(result));part.chmod(0o600)
                        read_export(part,url);part.replace(target)
                        time.sleep(2)
                    item={'file':filename,'source_url':url}
                    items=[i for i in items if i['source_url']!=url]+[item]
                    tmp=manifest.with_suffix('.tmp');tmp.write_text(json.dumps(items,indent=2));tmp.chmod(0o600);tmp.replace(manifest)
                    print(f'{len(items)}/36 validated: {course} {gender} {age}',flush=True)
        # Disconnect; leave the operator's browser available.
        browser.close()

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--cdp',default='http://127.0.0.1:9334');a.add_argument('--output',type=Path,required=True)
    args=a.parse_args();collect(args.cdp,args.output)
