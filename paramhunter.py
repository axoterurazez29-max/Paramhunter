#!/usr/bin/env python3
"""
============================================================
  KYORAKU PARAMHUNTER 
  Creator: Kyoraku
 
============================================================
"""

import requests
import urllib3
import re
import sys
import time
import json
import argparse
import threading
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BANNER = r"""
\033[95m
██╗  ██╗██╗   ██╗ ██████╗ ██████╗  █████╗ ██╗  ██╗██╗   ██╗
██║ ██╔╝╚██╗ ██╔╝██╔═══██╗██╔══██╗██╔══██║██║ ██╔╝██║   ██║
█████╔╝  ╚████╔╝ ██║   ██║██████╔╝███████║█████╔╝ ██║   ██║
██╔═██╗   ╚██╔╝  ██║   ██║██╔══██╗██╔══██║██╔═██╗ ██║   ██║
██║  ██╗   ██║   ╚██████╔╝██║  ██║██║  ██║██║  ██║╚██████╔╝
╚═════╝ ╚═╝  ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝


   ==============================================   
 Creator: Kyoraku
"""

G = "\033[92m"
Y = "\033[93m"
C = "\033[96m"
R = "\033[91m"
M = "\033[95m"
D = "\033[90m"
W = "\033[97m"
BOLD = "\033[1m"
RESET = "\033[0m"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

SKIP_EXT = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
    '.woff', '.woff2', '.ttf', '.eot', '.otf', '.css',
    '.pdf', '.mp4', '.mp3', '.avi', '.mov',
    '.zip', '.rar', '.tar', '.gz', '.7z',
    '.doc', '.docx', '.xls', '.xlsx',
}

LIVE_CODES = {200, 201, 202, 204, 301, 302, 303, 307, 308, 401, 403, 405, 500, 501}

TRACKING_BLACKLIST = {
    '_ga', '_gid', '_gl', 'gclid', 'fbclid',
    'utm_source', 'utm_medium', 'utm_campaign',
    'utm_content', 'utm_term', '__cf_chl_jschl_tk__',
    '_hsenc', '_hsmi', 'mc_eid', 'mc_cid', 'yclid', 'msclkid'
}

# FIX-BUG-A: Added \[\] to param name pattern — catches ?filter[]=, ?user[name]=
JS_URL_PATTERNS = [
    re.compile(r'["\'`]([^"\'`]*\?[a-zA-Z_][a-zA-Z0-9_\[\]]*=[^"\'`]*)["\'`]'),
    re.compile(r'(?:fetch|axios|get|post|put|ajax)\(["\']([^"\']*\?[^"\']*)["\']', re.IGNORECASE),
    re.compile(r'\.(?:get|post|put|delete)\(["\']([^"\']*\?[^"\']*)["\']', re.IGNORECASE),
    re.compile(r'url\s*:\s*["\']([^"\']*\?[^"\']*)["\']', re.IGNORECASE),
    re.compile(r'action\s*:\s*["\']([^"\']*\?[^"\']*)["\']', re.IGNORECASE),
]

JSON_URL_RE = re.compile(r'\?[a-zA-Z_][a-zA-Z0-9_\-]*=')

JS_GARBAGE_RE = re.compile(
    r'(?:\.html\(|\.find\(|\.floor\(|unescape\(|Math\.|'
    r'itemsPerPage|currentGalleryPage|settings\.|pp_titles|'
    r'\$\(|:30;|:0;|\$\w+\.)',
    re.IGNORECASE
)

print_lock = threading.Lock()
_tls = threading.local()

def get_session():
    if not hasattr(_tls, "s"):
        _tls.s = requests.Session()
        _tls.s.headers.update({"User-Agent": UA})
        _tls.s.verify = False
    return _tls.s

def safe_print(msg):
    with print_lock:
        try:
            print(msg)
        except (BlockingIOError, UnicodeEncodeError):
            print(msg.encode('utf-8', errors='replace').decode('utf-8', errors='replace'))


class KyorakuHunter:
    def __init__(self, target_url, threads=10, delay=0.5, timeout=20,
                 max_depth=3, js_depth=3, max_pages=300, output_file=None):
        self.base_url = target_url
        self.base_host = urlparse(target_url).hostname or ""
        # FIX-BUG-C: Use _clean_host instead of replace("www.", "")
        self.base_host_clean = self._clean_host(self.base_host)
        self.threads = threads
        self.delay = delay
        self.timeout = timeout
        self.max_depth = max_depth
        self.js_depth = js_depth
        self.max_pages = max_pages
        self.output_file = output_file
        self.visited = set()
        self.visited_paths = set()
        self.queued = set()
        self.all_urls = set()
        self.live_urls = {}
        self.param_urls = set()
        self.url_params = set()
        self.form_fields = {}
        self.js_files = set()
        self.js_params = set()
        self.pages_crawled = 0

    # FIX-BUG-C: Helper to strip only the "www." prefix, not mid-string
    def _clean_host(self, h):
        h = h.lower()
        if h.startswith("www."):
            return h[4:]
        return h

    def is_same_host(self, url):
        try:
            host = urlparse(url).hostname
            if not host:
                return False
            # FIX-BUG-C: Use _clean_host
            hc = self._clean_host(host)
            return hc == self.base_host_clean or hc.endswith("." + self.base_host_clean)
        except Exception:
            return False

    def fetch(self, url, retries=2):
        s = get_session()
        for a in range(retries + 1):
            try:
                r = s.get(url, timeout=self.timeout, allow_redirects=True)
                rh = urlparse(r.url).hostname or ""
                # FIX-BUG-C: Use _clean_host
                rc = self._clean_host(rh)
                if not (rc == self.base_host_clean or rc.endswith("." + self.base_host_clean)):
                    return None, "REDIRECT_OFFSITE", ""
                return r.text, r.status_code, r.headers.get("Content-Type", "").lower()
            except requests.exceptions.Timeout:
                if a < retries:
                    time.sleep(1)
                    continue
                return None, "TIMEOUT", ""
            except requests.exceptions.ConnectionError:
                if a < retries:
                    time.sleep(1)
                    continue
                return None, "CONN_ERR", ""
            except Exception:
                return None, "ERROR", ""
        return None, "ERROR", ""

    def get_status(self, url, retries=2):
        s = get_session()
        for a in range(retries + 1):
            try:
                r = s.get(url, timeout=self.timeout, allow_redirects=True, stream=True)
                r.close()
                rh = urlparse(r.url).hostname or ""
                # FIX-BUG-C: Use _clean_host
                rc = self._clean_host(rh)
                if not (rc == self.base_host_clean or rc.endswith("." + self.base_host_clean)):
                    return "REDIRECT_OFFSITE"
                return r.status_code
            except requests.exceptions.Timeout:
                if a < retries:
                    time.sleep(1)
                    continue
                return "TIMEOUT"
            except requests.exceptions.ConnectionError:
                if a < retries:
                    time.sleep(1)
                    continue
                return "CONN_ERR"
            except Exception:
                return "ERROR"
        return "ERROR"

    # FIX-BUG-B: rstrip only ", ;" — never strip ) ] } > from URLs
    def clean_url(self, url):
        if not url:
            return ""
        url = url.strip().strip('"').strip("'").strip("`").strip()
        url = url.rstrip(", ;")
        for sep in ['"', "'", "`", " ", "\t", "\n", "\r"]:
            if sep in url:
                url = url.split(sep)[0]
        return url.strip()

    def is_valid(self, url):
        try:
            p = urlparse(url)
            if not p.scheme or not p.hostname:
                return False
            if not self.is_same_host(url):
                return False
            pl = p.path.lower().split('?')[0]
            for ext in SKIP_EXT:
                if pl.endswith(ext):
                    return False
            if any(c in p.path for c in ['(', ')', '{', '}']):
                return False
            if p.query:
                BAD_CHARS = ('<', '>', '\n', '\t', '\r')
                if any(c in p.query for c in BAD_CHARS):
                    return False
                if JS_GARBAGE_RE.search(p.query):
                    return False
            return True
        except Exception:
            return False

    def merge_query(self, base_url, href):
        if not href.startswith('?'):
            return urljoin(base_url, href)
        pb = urlparse(base_url)
        hq = href[1:]
        merged = (pb.query + '&' + hq) if (pb.query and hq) else (hq or pb.query)
        path = pb.path if pb.path else "/"
        return f"{pb.scheme}://{pb.netloc}{path}?{merged}"

    def extract_urls(self, base_url, html):
        urls = set()
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(href=True):
            try:
                href = tag["href"].strip()
                if href and not href.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
                    full = self.merge_query(base_url, href) if href.startswith("?") else urljoin(base_url, href)
                    full = full.split("#")[0] if "#!" not in full else full
                    if self.is_valid(full):
                        urls.add(full)
            except Exception:
                continue
        for tag in soup.find_all(src=True):
            try:
                src = tag["src"].strip()
                if src and not src.startswith(("javascript:", "data:", "#")):
                    full = urljoin(base_url, src).split("#")[0]
                    if self.is_valid(full):
                        urls.add(full)
            except Exception:
                continue
        for tag in soup.find_all(action=True):
            try:
                action = tag["action"].strip()
                if action and not action.startswith(("javascript:", "#")):
                    full = self.merge_query(base_url, action) if action.startswith("?") else urljoin(base_url, action).split("#")[0]
                    if self.is_valid(full):
                        urls.add(full)
            except Exception:
                continue
        for m in re.finditer(r'(?:href|src|action)\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE):
            raw = self.clean_url(m.group(1))
            if raw and not raw.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
                full = self.merge_query(base_url, raw) if raw.startswith("?") else urljoin(base_url, raw).split("#")[0]
                if self.is_valid(full):
                    urls.add(full)
        for m in re.finditer(r'["\']([^"\']*(?:\.php|\.asp|\.aspx|\.html|\.htm|\.jsp|\.do|\.action)\?[^"\']*)["\']', html, re.IGNORECASE):
            raw = self.clean_url(m.group(1))
            full = urljoin(base_url, raw).split("#")[0]
            if self.is_valid(full):
                urls.add(full)
        for m in re.finditer(r'["\'](\.?[a-zA-Z0-9_\-/\.]*(?:\.php|\.asp|\.aspx|\.html|\.htm|\.jsp)?\?[^"\']+)["\']', html):
            raw = self.clean_url(m.group(1))
            if raw and not raw.startswith("http"):
                full = urljoin(base_url, raw).split("#")[0]
                if self.is_valid(full):
                    urls.add(full)
        for m in re.finditer(r'(?:fetch|ajax|open)\(["\']([^"\']+)["\']', html, re.IGNORECASE):
            raw = self.clean_url(m.group(1))
            full = urljoin(base_url, raw).split("#")[0]
            if self.is_valid(full):
                urls.add(full)
        return urls

    def extract_url_params(self, url):
        params = set()
        p = urlparse(url)
        if p.query:
            qs = parse_qs(p.query, keep_blank_values=True)
            for key in qs:
                if key and len(key) >= 1 and not re.fullmatch(r'_+', key) and key.lower() not in TRACKING_BLACKLIST:
                    params.add(key)
        return params

    def extract_form_fields(self, html, page_url):
        fields = set()
        soup = BeautifulSoup(html, "html.parser")
        for form in soup.find_all("form"):
            for inp in form.find_all(["input", "select", "textarea", "button"]):
                name = inp.get("name")
                if name and len(name) >= 1 and not re.fullmatch(r'_+', name):
                    fields.add(name)
        if fields:
            if page_url not in self.form_fields:
                self.form_fields[page_url] = set()
            self.form_fields[page_url].update(fields)
        return fields

    def extract_js_urls_and_params(self, js_url, js_content):
        js_urls = set()
        js_params = set()
        for pattern in JS_URL_PATTERNS:
            for m in pattern.finditer(js_content):
                raw = self.clean_url(m.group(1))
                full = urljoin(js_url, raw).split("#")[0]
                if self.is_valid(full):
                    js_urls.add(full)
        for m in re.finditer(r'req\.(?:query|body|params)\.([a-zA-Z0-9_\-]{1,40})', js_content):
            js_params.add(m.group(1))
        for m in re.finditer(r'\$_(?:GET|POST|REQUEST)\[["\']([a-zA-Z0-9_\-]{1,40})["\']\]', js_content):
            js_params.add(m.group(1))
        for m in re.finditer(r'(?:params|data|body|query)\.([a-zA-Z0-9_\-]{1,40})\s*=[^=]', js_content):
            js_params.add(m.group(1))
        for m in re.finditer(r'URLSearchParams\(["\']([^"\']+)["\']', js_content):
            val = m.group(1)
            if "=" in val:
                for pm in re.finditer(r'([a-zA-Z0-9_\-]{1,40})=', val):
                    js_params.add(pm.group(1))
            else:
                js_params.add(val)
        for m in re.finditer(r'getParameterByName\(["\']([a-zA-Z0-9_\-]{1,40})["\']', js_content):
            js_params.add(m.group(1))
        # FIX-BUG-A: Added \[\] to param name pattern — catches filter[], user[name]
        for m in re.finditer(r'[?&]([a-zA-Z0-9_\-\[\]]{1,40})=', js_content):
            key = m.group(1)
            if key.lower() not in TRACKING_BLACKLIST and not re.fullmatch(r'_+', key):
                js_params.add(key)
        return js_urls, js_params

    def extract_json_urls(self, json_text, base_url):
        urls = set()
        try:
            data = json.loads(json_text)
            def search(obj):
                if isinstance(obj, dict):
                    for v in obj.values():
                        search(v)
                elif isinstance(obj, list):
                    for item in obj:
                        search(item)
                elif isinstance(obj, str):
                    if JSON_URL_RE.search(obj):
                        raw = self.clean_url(obj)
                        full = urljoin(base_url, raw).split("#")[0]
                        if self.is_valid(full):
                            urls.add(full)
            search(data)
        except Exception:
            pass
        return urls

    def is_js_file(self, url):
        return bool(re.search(r'\.(?:js|mjs|cjs|jsx)(\?|$)', url, re.IGNORECASE))

    def try_connect(self, url):
        if not url.startswith("http"):
            url = "https://" + url
        html, status, ct = self.fetch(url)
        if html and isinstance(status, int) and status < 400:
            return url, html, ct
        if url.startswith("https://"):
            http_url = "http://" + url[8:]
            html, status, ct = self.fetch(http_url)
            if html and isinstance(status, int) and status < 400:
                return http_url, html, ct
        return url, None, ""

    def crawl(self):
        safe_print(f"\n{BOLD}{C}[*] Target:{RESET} {self.base_url}")
        safe_print(f"{BOLD}{C}[*] Mode:{RESET} Deep Crawl + JS Mining")
        safe_print(f"{BOLD}{C}[*] Delay:{RESET} {self.delay}s | {BOLD}{C}Timeout:{RESET} {self.timeout}s")
        safe_print(f"{BOLD}{C}[*] Max Depth:{RESET} {self.max_depth} | {BOLD}{C}JS Depth:{RESET} {self.js_depth} | {BOLD}{C}Max Pages:{RESET} {self.max_pages} | {BOLD}{C}Threads:{RESET} {self.threads}")

        working_url, html, ct = self.try_connect(self.base_url)
        if not html:
            safe_print(f"{R}[!] Cannot connect to target!{RESET}")
            return
        self.base_url = working_url
        safe_print(f"{G}[+] Connected to: {working_url}{RESET}\n")

        safe_print(f"{Y}[*] Phase 1: Crawling and collecting URLs...{RESET}\n")
        queue = [(self.base_url, 0)]
        self.queued.add(self.base_url)

        while queue and self.pages_crawled < self.max_pages:
            current_url, depth = queue.pop(0)
            if current_url in self.visited:
                continue
            self.visited.add(current_url)
            path = urlparse(current_url).path
            query = urlparse(current_url).query
            if not query:
                if path in self.visited_paths and depth > 0:
                    continue
                self.visited_paths.add(path)
            if not self.is_same_host(current_url):
                continue
            html, status, ct = self.fetch(current_url)
            if isinstance(status, int) and status in LIVE_CODES:
                safe_print(f"  {G}[{status}]{RESET} {W}{current_url}{RESET}")
            elif isinstance(status, int):
                safe_print(f"  {Y}[{status}]{RESET} {D}{current_url}{RESET}")
            else:
                safe_print(f"  {R}[{status}]{RESET} {D}{current_url}{RESET}")
            if not html:
                time.sleep(self.delay)
                continue
            self.pages_crawled += 1
            self.all_urls.add(current_url)
            if "html" in ct or "xml" in ct:
                self.extract_form_fields(html, current_url)
            if "json" in ct:
                json_urls = self.extract_json_urls(html, current_url)
                for u in json_urls:
                    self.all_urls.add(u)
                    if u not in self.visited and u not in self.queued and depth < self.max_depth:
                        queue.append((u, depth + 1))
                        self.queued.add(u)
            else:
                found_urls = self.extract_urls(current_url, html)
                if depth < self.max_depth:
                    for u in found_urls:
                        self.all_urls.add(u)
                        if u not in self.visited and u not in self.queued:
                            queue.append((u, depth + 1))
                            self.queued.add(u)
            time.sleep(self.delay)

        if self.pages_crawled >= self.max_pages:
            safe_print(f"\n{Y}[!] Max page limit ({self.max_pages}).{RESET}")

        safe_print(f"\n{Y}[*] Phase 2: Checking {len(self.all_urls)} URLs...{RESET}\n")
        urls_list = list(self.all_urls)
        batch_size = 5
        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            for i in range(0, len(urls_list), batch_size):
                batch = urls_list[i:i + batch_size]
                futs = {executor.submit(self.get_status, u): u for u in batch}
                for f in as_completed(futs):
                    u = futs[f]
                    try:
                        st = f.result()
                        if isinstance(st, int) and st in LIVE_CODES:
                            self.live_urls[u] = st
                            safe_print(f"  {G}[LIVE {st}]{RESET} {u}")
                        else:
                            safe_print(f"  {R}[DEAD {st}]{RESET} {D}{u}{RESET}")
                    except Exception:
                        safe_print(f"  {R}[ERROR]{RESET} {u}")
                time.sleep(self.delay)

        for url in self.live_urls:
            if "?" in url:
                self.param_urls.add(url)
                self.url_params.update(self.extract_url_params(url))
            if self.is_js_file(url):
                self.js_files.add(url)

        if self.js_files:
            safe_print(f"\n{Y}[*] Phase 3: Mining JS files...{RESET}\n")
            mined_js = set()
            js_queue = list(self.js_files)
            js_d = 0
            while js_queue and js_d < self.js_depth:
                js_d += 1
                next_q = []
                to_verify = set()
                for js_url in js_queue:
                    if js_url in mined_js:
                        continue
                    mined_js.add(js_url)
                    safe_print(f"  {D}[*] Mining JS (Depth {js_d}):{RESET} {js_url}")
                    jc, js, jct = self.fetch(js_url)
                    if not jc:
                        continue
                    if jct and ("html" in jct or "css" in jct or "image" in jct):
                        continue
                    ju, jp = self.extract_js_urls_and_params(js_url, jc)
                    new_jp = jp - self.url_params
                    self.js_params.update(new_jp)
                    self.url_params.update(jp)
                    safe_print(f"  {G}    Found: {len(ju)} URLs, {len(new_jp)} new params{RESET}")
                    for u in ju:
                        if self.is_js_file(u) and u not in mined_js and u not in next_q:
                            next_q.append(u)
                            self.js_files.add(u)
                        elif u not in self.live_urls:
                            to_verify.add(u)
                if to_verify:
                    safe_print(f"\n  {Y}[*] Verifying {len(to_verify)} JS URLs...{RESET}")
                    with ThreadPoolExecutor(max_workers=self.threads) as executor:
                        futs = {executor.submit(self.get_status, u): u for u in to_verify}
                        for f in as_completed(futs):
                            u = futs[f]
                            try:
                                st = f.result()
                                if isinstance(st, int) and st in LIVE_CODES:
                                    self.live_urls[u] = st
                                    safe_print(f"  {G}[LIVE {st}]{RESET} {u}")
                                    if "?" in u:
                                        self.param_urls.add(u)
                                        self.url_params.update(self.extract_url_params(u))
                                else:
                                    safe_print(f"  {R}[DEAD {st}]{RESET} {D}{u}{RESET}")
                            except Exception:
                                pass
                    time.sleep(self.delay)
                js_queue = next_q

    def save_output(self):
        if not self.output_file:
            return
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\nKYORAKU PARAMHUNTER v25.6 — SCAN RESULTS\n")
            f.write(f"Target: {self.base_url}\nTime: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"Pages Crawled:    {self.pages_crawled}\n")
            f.write(f"Live URLs:        {len(self.live_urls)}\n")
            f.write(f"Live JS Files:    {len(self.js_files)}\n")
            f.write(f"Param URLs:       {len(self.param_urls)}\n")
            f.write(f"URL Parameters:   {len(self.url_params)}\n")
            f.write(f"JS Params:        {len(self.js_params)}\n")
            uf = set()
            for fields in self.form_fields.values():
                uf.update(fields)
            f.write(f"Form Fields:      {len(uf)}\n\n")
            if self.param_urls:
                f.write(f"PARAMETERIZED URLS:\n")
                for u in sorted(self.param_urls):
                    f.write(f"  {u}\n")
                f.write("\n")
            if self.url_params:
                f.write(f"PARAMETERS:\n")
                for p in sorted(self.url_params):
                    f.write(f"  {p}\n")
        safe_print(f"\n{G}[+] Results saved: {self.output_file}{RESET}")

    def print_results(self):
        safe_print(f"\n{M}{BOLD}{'='*70}{RESET}")
        safe_print(f"{M}{BOLD}SCAN SUMMARY{RESET}")
        safe_print(f"{M}{BOLD}{'='*70}{RESET}")
        safe_print(f"  {C}Pages Crawled:{RESET}    {self.pages_crawled}")
        safe_print(f"  {C}Live URLs:{RESET}        {len(self.live_urls)}")
        safe_print(f"  {C}Live JS Files:{RESET}    {len(self.js_files)}")
        safe_print(f"  {C}Param URLs:{RESET}       {len(self.param_urls)}")
        safe_print(f"  {C}Parameters:{RESET}       {len(self.url_params)}")
        safe_print(f"  {C}JS Params:{RESET}        {len(self.js_params)}")
        uf = set()
        for fields in self.form_fields.values():
            uf.update(fields)
        safe_print(f"  {C}Form Fields:{RESET}      {len(uf)}")

        if self.param_urls:
            safe_print(f"\n{C}{BOLD}PARAMETERIZED URLS:{RESET}")
            for u in sorted(self.param_urls):
                safe_print(f"  {C}{u}{RESET}")
        if self.url_params:
            safe_print(f"\n{G}{BOLD}PARAMETERS:{RESET}")
            for p in sorted(self.url_params):
                safe_print(f"  {G}{p}{RESET}")
        self.save_output()


def main():
    print(BANNER)
    parser = argparse.ArgumentParser(
        description="KYORAKU PARAMHUNTER v25.6 — Param Discovery",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-u", "--url", help="Target URL")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--js-depth", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=300)
    parser.add_argument("--output", help="Save scan results to file")

    args = parser.parse_args()

    url = args.url
    if not url:
        url = input(f"{G}[?] Target URL: {RESET}").strip()
        if not url:
            return
    if not url.startswith("http"):
        url = "https://" + url

    hunter = KyorakuHunter(
        target_url=url, threads=args.threads, delay=args.delay,
        timeout=args.timeout, max_depth=args.depth, js_depth=args.js_depth,
        max_pages=args.max_pages, output_file=args.output
    )

    start = time.time()
    try:
        hunter.crawl()
        hunter.print_results()
    except KeyboardInterrupt:
        safe_print(f"\n{Y}[*] Stopped. Saving...{RESET}")
        hunter.print_results()

    elapsed = time.time() - start
    safe_print(f"\n{D}[*] Completed in {elapsed:.2f}s{RESET}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Y}[*] Stopped.{RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"{R}[!] Error: {e}{RESET}")
        sys.exit(1)
