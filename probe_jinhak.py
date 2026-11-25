"""One bounded public-page check on a GitHub-hosted browser; no login or bypass."""
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

result = {'status':'error', 'pages':[]}
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for url in ['https://www.jinhakpro.com/recruit/list', 'https://www.jinhakpro.com/recruit/50107']:
            response = page.goto(url, wait_until='domcontentloaded', timeout=45000)
            info = {'url':url, 'http':response.status, 'title':page.title()}
            result['pages'].append(info)
            if response.status >= 400 or any(s in page.title().lower() for s in ['just a moment','access denied']):
                raise RuntimeError('Site denied cloud browser; no retries')
            if url.endswith('/list'):
                info['list_data'] = page.locator('#__NUXT_DATA__').count() > 0
                if not info['list_data']: raise RuntimeError('Missing listing data')
                time.sleep(15)
            else:
                node=page.locator('.TRU_detail_cont > .TRU_box2').first
                body=node.inner_text(timeout=10000)
                info['body_chars']=len(body)
                info['topic_words']=[w for w in ['패션','연극','영화'] if w in body]
                if not info['topic_words']: raise RuntimeError('No verified recruitment text')
        browser.close()
        result['status']='ok'
except Exception as exc:
    result['error']=str(exc)[:350]
Path('jinhak-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result['status']=='ok' else 1)
