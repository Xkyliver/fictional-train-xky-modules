#!/usr/bin/env python3
"""
APKMirror Helper using cloudscraper & BeautifulSoup
Replicates the reliable download mechanism used by crimera/twitter-apk and ikafly144/piko-module
"""
import sys
import os
import re
import time
import argparse
import urllib.parse
import cloudscraper
from bs4 import BeautifulSoup

def get_scraper():
    scraper = cloudscraper.create_scraper()
    scraper.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return scraper

def safe_get(scraper, url: str, referer: str = None, max_retries: int = 3):
    headers = {}
    if referer:
        headers["Referer"] = referer
    for attempt in range(max_retries):
        try:
            r = scraper.get(url, headers=headers)
            if r.status_code == 200:
                return r
            elif r.status_code in (429, 503, 504):
                wait = (attempt + 1) * 3
                print(f"Request to {url} returned {r.status_code}, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"Request to {url} returned status {r.status_code}", file=sys.stderr)
                return r
        except Exception as e:
            print(f"Request to {url} failed with exception: {e}", file=sys.stderr)
            time.sleep(2)
    return None

def sanitize_version(version: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]+', '-', version).strip('-').lower()

def compact_version(version: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', version).lower()

def get_pkg_name(scraper, base_url: str) -> str:
    try:
        r = safe_get(scraper, base_url)
        if r and r.status_code == 200:
            soup = BeautifulSoup(r.content, "html.parser")
            link = soup.find("a", href=re.compile(r"details\?id=([a-zA-Z0-9_\.]+)"))
            if link and "href" in link.attrs:
                m = re.search(r"details\?id=([a-zA-Z0-9_\.]+)", link["href"])
                if m:
                    return m.group(1)
            for a in soup.find_all("a", href=True):
                if "id=" in a["href"]:
                    m = re.search(r"id=([a-zA-Z0-9_\.]+)", a["href"])
                    if m:
                        return m.group(1)
    except Exception:
        pass
    if "twitter" in base_url.lower():
        return "com.twitter.android"
    return ""

def get_versions_list(scraper, base_url: str) -> list[str]:
    r = safe_get(scraper, base_url)
    if not r or r.status_code != 200:
        raise Exception(f"Failed to fetch {base_url}")
    soup = BeautifulSoup(r.content, "html.parser")
    container = soup.find(id="primary") or soup
    versions = []
    for a in container.find_all("a", {"class": "fontBlack"}):
        text = a.get_text(strip=True)
        if "wear os" in text.lower() or "android tv" in text.lower():
            continue
        m = re.search(r'(\d+(\.\d+)+[a-zA-Z0-9_\-]*)', text)
        if m:
            v = m.group(1).strip()
            if v and "beta" not in v.lower() and "alpha" not in v.lower() and v not in versions:
                versions.append(v)
    if not versions:
        for span in container.find_all("span", {"class": "infoSlide-value"}):
            text = span.get_text(strip=True)
            if re.match(r'^\d+(\.\d+)+([a-zA-Z0-9_\-]+)?$', text):
                if "beta" not in text.lower() and "alpha" not in text.lower() and text not in versions:
                    versions.append(text)
    return versions

def is_version_match(href: str, v_slug: str, v_compact: str) -> bool:
    href_l = href.lower()
    if "#" in href_l:
        return False
    if not (href_l.startswith("/apk/") or "apkmirror.com/apk/" in href_l):
        return False
    if any(x in href_l for x in ("apk-download", "variant-", "download.php", "/author/", "/apk/page/")):
        return False
    if v_slug in href_l:
        return True
    href_compact = re.sub(r'[^a-zA-Z0-9]', '', href_l)
    if v_compact and len(v_compact) >= 4 and v_compact in href_compact:
        return True
    return False

def page_has_variants(html_text: str) -> bool:
    if not html_text:
        return False
    soup = BeautifulSoup(html_text, "html.parser")
    if soup.find("a", href=re.compile(r"-apk-download/?$")):
        return True
    table = soup.find("div", {"class": ["variants-table", "table"]})
    if table and table.find("a", href=re.compile(r"-apk-download/?$")):
        return True
    dl_btn = soup.find("a", {"class": re.compile(r"downloadButton")})
    if dl_btn and dl_btn.get("href") and not dl_btn["href"].startswith("#"):
        return True
    return False

def find_version_page(scraper, base_url: str, version: str):
    app_slug = base_url.rstrip('/').split('/')[-1]
    v_slug = sanitize_version(version)
    v_compact = compact_version(version)

    v_parts = version.split('.')
    v_trim = '.'.join(v_parts[:3]) if len(v_parts) > 3 else None
    v_trim_slug = sanitize_version(v_trim) if v_trim else None
    v_trim_compact = compact_version(v_trim) if v_trim else None
    
    title_slug = None
    # 1. Base listing page (most reliable & avoids guessing)
    r = safe_get(scraper, base_url)
    if r and r.status_code == 200:
        soup = BeautifulSoup(r.content, "html.parser")
        h1 = soup.find("h1", {"class": "marginZero"})
        if h1:
            title_slug = sanitize_version(h1.get_text(strip=True))

        matching_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if is_version_match(href, v_slug, v_compact) or (v_trim_slug and is_version_match(href, v_trim_slug, v_trim_compact)):
                matching_links.append(href)
        
        # Sort candidates: prefer those containing '-release' and matching exact slug
        matching_links.sort(key=lambda h: (1 if "-release" in h.lower() else 0, 1 if v_slug in h.lower() else 0), reverse=True)
        
        for href in matching_links[:5]:
            full_url = "https://www.apkmirror.com" + href if href.startswith("/") else href
            r2 = safe_get(scraper, full_url, referer=base_url)
            if r2 and r2.status_code == 200 and page_has_variants(r2.text):
                return full_url, r2

    # 2. Try candidate URLs: PRIORITIZE -release candidates
    candidates = []
    if title_slug:
        candidates.append(f"{base_url.rstrip('/')}/{title_slug}-{v_slug}-release/")
        if v_trim_slug:
            candidates.append(f"{base_url.rstrip('/')}/{title_slug}-{v_trim_slug}-release/")
    candidates.append(f"{base_url.rstrip('/')}/{app_slug}-{v_slug}-release/")
    if v_trim_slug:
        candidates.append(f"{base_url.rstrip('/')}/{app_slug}-{v_trim_slug}-release/")
    candidates.append(f"{base_url.rstrip('/')}/{v_slug}-release/")
    if v_trim_slug:
        candidates.append(f"{base_url.rstrip('/')}/{v_trim_slug}-release/")
    
    # Non -release fallbacks
    if title_slug:
        candidates.append(f"{base_url.rstrip('/')}/{title_slug}-{v_slug}/")
        if v_trim_slug:
            candidates.append(f"{base_url.rstrip('/')}/{title_slug}-{v_trim_slug}/")
    candidates.append(f"{base_url.rstrip('/')}/{app_slug}-{v_slug}/")
    if v_trim_slug:
        candidates.append(f"{base_url.rstrip('/')}/{app_slug}-{v_trim_slug}/")
    candidates.append(f"{base_url.rstrip('/')}/{v_slug}/")
    if v_trim_slug:
        candidates.append(f"{base_url.rstrip('/')}/{v_trim_slug}/")

    for url in candidates:
        r2 = safe_get(scraper, url, referer=base_url)
        if r2 and r2.status_code == 200 and page_has_variants(r2.text):
            return url, r2

    # 3. Search APKMirror fallback
    search_q = f"{app_slug.replace('-', ' ')} {v_trim if v_trim else version}"
    search_url = f"https://www.apkmirror.com/?post_type=app_release&searchtype=apk&s={urllib.parse.quote(search_q)}"
    print(f"Searching APKMirror: {search_url}", file=sys.stderr)
    r_search = safe_get(scraper, search_url, referer=base_url)
    if r_search and r_search.status_code == 200:
        soup = BeautifulSoup(r_search.content, "html.parser")
        matching_search = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if is_version_match(href, v_slug, v_compact) or (v_trim_slug and is_version_match(href, v_trim_slug, v_trim_compact)):
                matching_search.append(href)
        matching_search.sort(key=lambda h: (1 if "-release" in h.lower() else 0, 1 if v_slug in h.lower() else 0), reverse=True)
        for href in matching_search[:3]:
            full_url = "https://www.apkmirror.com" + href if href.startswith("/") else href
            r2 = safe_get(scraper, full_url, referer=search_url)
            if r2 and r2.status_code == 200 and page_has_variants(r2.text):
                return full_url, r2

    raise Exception(f"Could not find APKMirror page for version '{version}' at {base_url}")

def download_file(scraper, direct_url: str, referer: str, out_path: str):
    dir_name = os.path.dirname(out_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    
    headers = {"Referer": referer}
    print(f"Downloading from {direct_url} -> {out_path}", file=sys.stderr)
    with scraper.get(direct_url, stream=True, headers=headers) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    print(f"Downloaded successfully: {out_path} ({os.path.getsize(out_path)} bytes)", file=sys.stderr)

def download_apkmirror(base_url: str, version: str, output: str, arch: str = "all", dpi: str = ""):
    scraper = get_scraper()
    
    version_url, resp = find_version_page(scraper, base_url, version)
    print(f"Found version page: {version_url}", file=sys.stderr)
    
    soup = BeautifulSoup(resp.content, "html.parser")
    raw_variants = []
    
    table = soup.find("div", {"class": ["table", "variants-table"]})
    if not table:
        table = soup.find("div", {"class": re.compile(r"variants-table")})
    
    if table:
        rows = table.find_all("div", {"class": re.compile(r"table-row")})
        if not rows:
            rows = table.find_all("div", recursive=False)[1:]
        for row in rows:
            cells = row.find_all("div", {"class": "table-cell"}, recursive=False)
            if not cells:
                continue
            
            link_el = row.find("a", href=re.compile(r"-apk-download/?$")) or row.find("a", {"class": "accent_color"})
            if not link_el or not link_el.get("href"):
                continue
            
            href = link_el["href"].strip()
            if href.startswith("#") or "all_versions" in href or "variant-" in href:
                continue
            
            badge = row.find("span", {"class": re.compile(r"apkm-badge")})
            badge_text = badge.text.strip().upper() if badge else ""
            is_bundle = ("BUNDLE" in badge_text) or ("bundle" in href.lower())
            
            variant_arch = "universal"
            for c in cells:
                c_text = c.get_text(strip=True).lower()
                if any(a in c_text for a in ("arm64-v8a", "armeabi-v7a", "arm", "x86_64", "x86", "universal", "noarch")):
                    variant_arch = c_text
                    break
            
            variant_url = "https://www.apkmirror.com" + href if href.startswith("/") else href
            raw_variants.append({
                "is_bundle": is_bundle,
                "url": variant_url,
                "arch": variant_arch
            })
    
    # Fallback: check all -apk-download links directly on page
    if not raw_variants:
        for a in soup.find_all("a", href=re.compile(r"-apk-download/?$")):
            href = a["href"].strip()
            if href and not href.startswith("#") and "variant-" not in href:
                variant_url = "https://www.apkmirror.com" + href if href.startswith("/") else href
                raw_variants.append({
                    "is_bundle": "bundle" in href.lower(),
                    "url": variant_url,
                    "arch": "universal"
                })
    
    # If no variants in table, check if page itself has downloadButton
    if not raw_variants:
        dl_btn = soup.find("a", {"class": re.compile(r"downloadButton")})
        if dl_btn and dl_btn.get("href"):
            href = dl_btn["href"].strip()
            if href and not href.startswith("#"):
                variant_url = "https://www.apkmirror.com" + href if href.startswith("/") else href
                raw_variants.append({
                    "is_bundle": False,
                    "url": variant_url,
                    "arch": "universal"
                })
    
    if not raw_variants:
        raise Exception(f"No variants found for {version}")
    
    # Sort variants by priority
    target_arch = arch.lower() if arch else "all"
    v_parts = version.split('.')
    sub_ver = v_parts[-1] if len(v_parts) > 3 else ""
    
    def variant_score(v):
        score = 0
        if v["is_bundle"]:
            score += 10
        if target_arch in ("all", "both"):
            score += 10
        elif target_arch in v["arch"]:
            score += 50
        elif "universal" in v["arch"] or "noarch" in v["arch"]:
            score += 25
        if sub_ver and sub_ver in v["url"]:
            score += 100
        return score

    ordered_variants = sorted(raw_variants, key=variant_score, reverse=True)
    
    last_err = None
    for idx, selected in enumerate(ordered_variants):
        print(f"Trying variant {idx+1}/{len(ordered_variants)} (bundle={selected['is_bundle']}, arch={selected['arch']}): {selected['url']}", file=sys.stderr)
        try:
            r_variant = safe_get(scraper, selected["url"], referer=version_url)
            if not r_variant or r_variant.status_code != 200:
                print(f"  Variant page returned {getattr(r_variant, 'status_code', None)}, skipping", file=sys.stderr)
                continue
            
            soup_var = BeautifulSoup(r_variant.content, "html.parser")
            dl_btn = soup_var.find("a", {"class": re.compile(r"downloadButton")})
            if not dl_btn or not dl_btn.get("href"):
                print("  Download button not found, skipping", file=sys.stderr)
                continue
            
            dl_page_href = dl_btn["href"].strip()
            dl_page_url = "https://www.apkmirror.com" + dl_page_href if dl_page_href.startswith("/") else dl_page_href
            
            r_dl = safe_get(scraper, dl_page_url, referer=selected["url"])
            if not r_dl or r_dl.status_code != 200:
                print(f"  Download page returned {getattr(r_dl, 'status_code', None)}, skipping", file=sys.stderr)
                continue
            
            soup_dl = BeautifulSoup(r_dl.content, "html.parser")
            direct_link = soup_dl.find("a", href=re.compile(r"download\.php"))
            if not direct_link:
                direct_link = soup_dl.find("a", {"rel": "nofollow", "href": re.compile(r"download\.php|/wp-content/")})
            if not direct_link:
                direct_link = soup_dl.find("a", string=re.compile(r"here", re.I))
            if not direct_link:
                direct_link = soup_dl.find("a", {"rel": "nofollow"})
            if not direct_link or not direct_link.get("href"):
                print("  Direct link not found on download page, skipping", file=sys.stderr)
                continue
            
            direct_href = direct_link["href"].strip()
            direct_url = "https://www.apkmirror.com" + direct_href if direct_href.startswith("/") else direct_href
            
            actual_output = output
            if selected["is_bundle"]:
                if not actual_output.endswith(".apkm"):
                    actual_output = f"{output}.apkm"
            
            download_file(scraper, direct_url, dl_page_url, actual_output)
            print(actual_output)
            return actual_output
        except Exception as e:
            last_err = e
            print(f"  Variant attempt encountered error: {e}", file=sys.stderr)
            continue
            
    raise Exception(f"All variants failed for {version}. Last error: {last_err}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="APKMirror Helper")
    parser.add_argument("url", nargs="?", help="APKMirror app URL")
    parser.add_argument("version", nargs="?", help="App version")
    parser.add_argument("output", nargs="?", help="Output file path")
    parser.add_argument("arch", nargs="?", default="all", help="Target architecture")
    parser.add_argument("dpi", nargs="?", default="", help="Target DPI")
    parser.add_argument("--pkg-name", dest="pkg_url", help="Get package name for URL")
    parser.add_argument("--versions", dest="versions_url", help="Get version list for URL")
    
    args = parser.parse_args()
    scraper = get_scraper()
    
    if args.pkg_url:
        print(get_pkg_name(scraper, args.pkg_url))
        sys.exit(0)
    elif args.versions_url:
        for v in get_versions_list(scraper, args.versions_url):
            print(v)
        sys.exit(0)
        
    if not args.url or not args.version or not args.output:
        parser.print_help(sys.stderr)
        sys.exit(1)
        
    try:
        download_apkmirror(args.url, args.version, args.output, args.arch, args.dpi)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
