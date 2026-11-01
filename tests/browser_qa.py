from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=Path('/mnt/data')
html=(ROOT/'public/index.html').read_text(encoding='utf-8')
html=html.replace('<link rel="stylesheet" href="./styles.css">', '<style>'+ (ROOT/'public/styles.css').read_text(encoding='utf-8') +'</style>')
html=html.replace('<script src="./data/site-data.js" defer></script>', '')
html=html.replace('<script src="./app.js" defer></script>', '')
html=html.replace('</body>', '<script>'+ (ROOT/'public/data/site-data.js').read_text(encoding='utf-8') +'</script><script>'+ (ROOT/'public/app.js').read_text(encoding='utf-8') +'</script></body>')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    desktop=browser.new_page(viewport={'width':1440,'height':950},device_scale_factor=1)
    errors=[]
    desktop.on('pageerror',lambda error:errors.append(str(error)))
    desktop.set_content(html,wait_until='load')
    print('Title:',desktop.title())
    print('Stats:',[desktop.locator('#'+v).inner_text() for v in ('stat-papers','stat-trials','stat-japan')])
    assert desktop.locator('#stat-papers').inner_text()=='10'
    assert desktop.locator('#stat-trials').inner_text()=='9'
    assert desktop.locator('#stat-japan').inner_text()=='3'
    assert desktop.locator('#research-type-select').input_value()=='all'
    assert desktop.locator('#result-total').inner_text()=='10 件'
    assert desktop.locator('.record-card').count()==8
    assert desktop.locator('#studytype-filter').is_visible()
    assert 'IF 10' not in desktop.locator('body').inner_text()
    desktop.screenshot(path=str(OUT/'Dementia_Atlas_v3_Desktop.png'),full_page=True)
    print('Desktop x overflow:',desktop.evaluate('document.documentElement.scrollWidth - window.innerWidth'))
    desktop.locator('[data-tab="trials"]').click()
    assert desktop.locator('#result-total').inner_text()=='9 件'
    assert not desktop.locator('#studytype-filter').is_visible()
    desktop.locator('#japan-only').check()
    assert desktop.locator('#result-total').inner_text()=='3 件'
    desktop.locator('#status-select').select_option('RECRUITING')
    assert desktop.locator('#result-total').inner_text()=='3 件'
    desktop.locator('[data-tab="articles"]').click()
    assert desktop.locator('#result-total').inner_text()=='10 件'
    desktop.locator('#topic-select').select_option('試験対策')
    assert desktop.locator('#result-total').inner_text()=='2 件'
    desktop.locator('#clear-filters').click()
    desktop.screenshot(path=str(OUT/'Dementia_Atlas_v3_Notes.png'),full_page=True)
    print('JS errors:',errors)
    assert not errors
    mobile=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True)
    mobile_errors=[]
    mobile.on('pageerror',lambda e:mobile_errors.append(str(e)))
    mobile.set_content(html,wait_until='load')
    mobile.screenshot(path=str(OUT/'Dementia_Atlas_v3_Mobile.png'),full_page=True)
    print('Mobile x overflow:',mobile.evaluate('document.documentElement.scrollWidth-window.innerWidth'))
    mobile.locator('#mobile-menu-button').click()
    assert mobile.locator('#mobile-menu').is_visible()
    mobile.locator('#mobile-menu [data-nav="trials"]').click()
    assert mobile.locator('#results-title').inner_text()=='臨床試験・治験'
    assert not mobile_errors
    browser.close()
print('BROWSER QA PASSED')
