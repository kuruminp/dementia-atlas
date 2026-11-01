#!/usr/bin/env python3
"""Build a sitemap after the public site URL has been decided."""
import sys
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parents[1] / 'public'

def main():
    if len(sys.argv)!=2:
        raise SystemExit('Usage: python scripts/generate_sitemap.py https://your-domain.example')
    domain=sys.argv[1].strip().rstrip('/')
    parsed=urlparse(domain)
    if parsed.scheme!='https' or not parsed.netloc or parsed.path not in ('','/'):
        raise SystemExit('Please supply a valid HTTPS site root URL with no path')
    urls=[domain+'/',domain+'/about.html',domain+'/privacy.html']
    items='\n'.join(f'  <url><loc>{escape(url)}</loc></url>' for url in urls)
    xml='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+items+'\n</urlset>\n'
    (ROOT/'sitemap.xml').write_text(xml,encoding='utf-8')
    (ROOT/'robots.txt').write_text('User-agent: *\nAllow: /\n\nSitemap: '+domain+'/sitemap.xml\n',encoding='utf-8')
    print('Sitemap and robots.txt updated for',domain)

if __name__=='__main__':main()
