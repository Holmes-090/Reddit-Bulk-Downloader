import os
import re
import time
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse
from tkinter import *
from tkinter import ttk, messagebox, filedialog
from threading import Thread


def clean_filename(name):
    # Sanitize filename for Windows
    sanitized = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    # Remove single quotes to avoid awkward paths like 'title'
    sanitized = sanitized.replace("'", "")
    # Remove trailing dots/spaces (invalid on Windows)
    sanitized = re.sub(r'[\. ]+$', "", sanitized)
    if not sanitized:
        sanitized = "untitled"
    # Avoid Windows reserved device names
    reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
    if sanitized.upper() in reserved:
        sanitized = f"_{sanitized}_"
    return sanitized


def get_media_links_from_post_html(post_div):
    media_links = []

    for tag in post_div.find_all(['a', 'img', 'source']):
        for attr in ['href', 'src']:
            url = tag.get(attr)
            if not url:
                continue
            url = url.split('?')[0]
            lower = url.lower()
            if any(lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.gifv']):
                if lower.endswith('.gifv') and 'imgur.com' in lower:
                    media_links.append(url[:-5] + '.mp4')
                else:
                    media_links.append(url)

    return list(set(media_links))


def download_file(url, dest_folder):
    timeout = (15, 180)
    attempts = 2
    last_error = None
    local_filename = url.split('/')[-1].split("?")[0]
    filepath = os.path.join(dest_folder, local_filename)

    headers = {'User-Agent': 'Mozilla/5.0'}
    if 'redgifs.com' in url:
        headers['Referer'] = 'https://www.redgifs.com/'
        headers['Origin'] = 'https://www.redgifs.com'
        headers['Accept'] = '*/*'

    for _ in range(attempts):
        try:
            os.makedirs(dest_folder, exist_ok=True)
            with requests.get(url, stream=True, headers=headers, timeout=timeout) as r:
                r.raise_for_status()
                with open(filepath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        f.write(chunk)
            return filepath
        except Exception as e:
            last_error = e
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception:
                pass

    print(f"Error downloading {url}: {last_error}")
    return None

def parse_cookie_string_to_dict(cookies_str: str) -> dict:
    # Accept either raw cookie string or a full "Cookie: a=b; c=d" header
    if cookies_str.lower().startswith("cookie:"):
        cookies_str = cookies_str.split(":", 1)[1]
    cookies: dict[str, str] = {}
    for part in cookies_str.split(';'):
        if '=' not in part:
            continue
        key, value = part.strip().split('=', 1)
        # Skip cookie attributes that sometimes get included by exporters
        if key.lower() in {"path", "domain", "expires", "max-age", "secure", "httponly", "samesite"}:
            continue
        cookies[key] = value
    return cookies


def normalize_saved_url_to_old_reddit(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc or "www.reddit.com"
    if "reddit.com" not in netloc:
        raise ValueError("URL must be a reddit.com URL")
    # Force old.reddit.com for server-rendered pages
    netloc = "old.reddit.com"
    path = parsed.path
    if not path.endswith('/'):
        path = path + '/'
    # Ensure it points to /saved/
    if "/saved/" not in path:
        if path.endswith("/saved/"):
            pass
        elif path.endswith("/saved/") is False and path.rstrip('/').endswith('/saved') is False:
            if path.endswith('/'):
                path = path + "saved/"
            else:
                path = path + "/saved/"
    new_parsed = parsed._replace(netloc=netloc, path=path, params='', query='', fragment='')
    return urlunparse(new_parsed)


_redgifs_auth_cache: dict = {"token": None, "fetched_at": 0}


def _get_redgifs_token(headers: dict, log_callback) -> str | None:
    now = time.time()
    token = _redgifs_auth_cache.get('token')
    if token and (now - _redgifs_auth_cache.get('fetched_at', 0)) < 60 * 30:
        return token
    try:
        resp = requests.get('https://api.redgifs.com/v2/auth/temporary', headers=headers, timeout=15)
        resp.raise_for_status()
        j = resp.json()
        token = j.get('token') or (j.get('data') or {}).get('token')
        if token:
            _redgifs_auth_cache['token'] = token
            _redgifs_auth_cache['fetched_at'] = now
            return token
    except Exception as e:
        log_callback(f"Failed to auth with Redgifs: {e}")
    return None


def _extract_redgifs_id_from_url(url: str) -> str | None:
    try:
        p = urlparse(url)
        if 'redgifs.com' not in p.netloc and 'gifdeliverynetwork.com' not in p.netloc and 'gfycat.com' not in p.netloc:
            return None
        parts = [seg for seg in p.path.split('/') if seg]
        if not parts:
            return None
        if parts[0] in {'watch', 'ifr'} and len(parts) >= 2:
            return parts[1]
        return parts[-1]
    except Exception:
        return None


def _resolve_redgifs_direct_urls(url: str, headers: dict, log_callback) -> list[str]:
    if 'gfycat.com' in url:
        try:
            p = urlparse(url)
            parts = [seg for seg in p.path.split('/') if seg]
            gif_id = parts[1] if parts and parts[0] == 'ifr' and len(parts) > 1 else (parts[0] if parts else None)
            if gif_id:
                url = f"https://redgifs.com/ifr/{gif_id}"
        except Exception:
            pass

    gid = _extract_redgifs_id_from_url(url)
    if not gid:
        return []
    token = _get_redgifs_token(headers, log_callback)
    if not token:
        return []
    try:
        api_headers = dict(headers)
        api_headers['Authorization'] = f"Bearer {token}"
        resp = requests.get(f'https://api.redgifs.com/v2/gifs/{gid}', headers=api_headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        gif = data.get('gif') or data.get('result') or data.get('data') or {}
        urls = gif.get('urls') or {}
        candidates = [urls.get('hd'), urls.get('sd'), urls.get('gif')]
        return [u for u in candidates if isinstance(u, str)]
    except Exception as e:
        log_callback(f"Failed to resolve Redgifs {gid}: {e}")
        return []


def _convert_imgur_gifv_to_mp4(url: str) -> str:
    if url.lower().endswith('.gifv') and 'imgur.com' in url:
        return url[:-5] + '.mp4'
    return url


def extract_media_urls_from_post_data(post_data: dict, headers: dict, log_callback) -> list[str]:
    media_urls: list[str] = []

    # Direct media link overrides
    url_overridden = post_data.get('url_overridden_by_dest') or post_data.get('url')
    if isinstance(url_overridden, str):
        cleaned = url_overridden.split('?')[0]
        lower = cleaned.lower()
        if 'redgifs.com' in lower or 'gifdeliverynetwork.com' in lower or 'gfycat.com' in lower:
            media_urls.extend(_resolve_redgifs_direct_urls(cleaned, headers, log_callback))
        else:
            if lower.endswith('.gifv') and 'imgur.com' in lower:
                cleaned = _convert_imgur_gifv_to_mp4(cleaned)
            if any(lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4']):
                media_urls.append(cleaned)

    # Reddit-hosted gallery
    if post_data.get('is_gallery') and isinstance(post_data.get('media_metadata'), dict):
        for item in post_data['media_metadata'].values():
            if not isinstance(item, dict):
                continue
            # Prefer the highest resolution preview available
            previews = item.get('p') or []
            if previews:
                best = previews[-1]
                url = best.get('u') or best.get('url')
                if url:
                    media_urls.append(url.split('?')[0])
            else:
                # Fallback to source if no previews
                source = item.get('s') or {}
                url = source.get('u') or source.get('url')
                if url:
                    media_urls.append(url.split('?')[0])

    # Reddit-hosted videos
    secure_media = post_data.get('secure_media') or {}
    if isinstance(secure_media, dict):
        reddit_video = secure_media.get('reddit_video') or {}
        if isinstance(reddit_video, dict):
            fallback_url = reddit_video.get('fallback_url')
            if isinstance(fallback_url, str):
                media_urls.append(fallback_url.split('?')[0])
        oembed = secure_media.get('oembed') or {}
        if isinstance(oembed, dict):
            html = oembed.get('html') or ''
            if isinstance(html, str) and ('redgifs.com' in html or 'gfycat.com' in html or 'imgur.com' in html):
                try:
                    soup = BeautifulSoup(html, 'html.parser')
                    iframe = soup.find('iframe')
                    if iframe and iframe.get('src'):
                        src = iframe['src']
                        lower = src.lower()
                        if 'redgifs.com' in lower or 'gfycat.com' in lower:
                            media_urls.extend(_resolve_redgifs_direct_urls(src, headers, log_callback))
                        elif lower.endswith('.gifv') and 'imgur.com' in lower:
                            media_urls.append(_convert_imgur_gifv_to_mp4(src))
                except Exception:
                    pass

    # De-duplicate
    unique_urls = []
    seen = set()
    for u in media_urls:
        if u not in seen:
            unique_urls.append(u)
            seen.add(u)
    return unique_urls


def fetch_all_saved_items_json(saved_url: str, headers: dict, cookies: dict, log_callback) -> list[dict]:
    items: list[dict] = []
    after: str | None = None

    # Build base JSON endpoint
    # Example: https://old.reddit.com/user/<username>/saved/.json?limit=100&raw_json=1
    while True:
        params = {
            'limit': '100',
            'raw_json': '1',
        }
        if after:
            params['after'] = after

        json_url = saved_url.rstrip('/') + '/.json'
        try:
            resp = requests.get(json_url, headers=headers, cookies=cookies, params=params, timeout=30)
            if resp.status_code in (401, 403):
                log_callback("Authentication failed. Make sure your cookie header is from a logged-in session.")
                break
            resp.raise_for_status()
        except Exception as e:
            log_callback(f"Error fetching JSON: {e}")
            break

        try:
            data = resp.json()
        except json.JSONDecodeError:
            log_callback("Failed to parse JSON. Your cookies may be invalid or you were redirected to a login page.")
            break

        if not isinstance(data, dict) or 'data' not in data or 'children' not in data['data']:
            log_callback("No saved items found or unexpected response structure.")
            break

        children = data['data']['children']
        if not children:
            break

        items.extend(children)
        after = data['data'].get('after')
        log_callback(f"Fetched {len(children)} saved items (total: {len(items)}).")

        # Stop if no more pages
        if not after:
            break

        # Be polite and avoid hammering the server
        time.sleep(0.6)

    return items


def scrape_reddit_saved(url, cookies_str, output_dir, log_callback):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) RedditSavedDownloader/1.0'}
    cookies = parse_cookie_string_to_dict(cookies_str)
    cookies.setdefault('over18', '1')

    try:
        saved_url = normalize_saved_url_to_old_reddit(url)
    except Exception as e:
        log_callback(f"Invalid URL: {e}")
        return

    log_callback(f"Using endpoint: {saved_url}")
    items = fetch_all_saved_items_json(saved_url, headers, cookies, log_callback)
    if not items:
        log_callback("No saved items found. If this seems wrong, re-copy your Cookie header from a logged-in tab on old.reddit.com.")
        return

    log_callback(f"Found {len(items)} saved items. Extracting media and downloading...")

    for idx, child in enumerate(items, start=1):
        if not isinstance(child, dict) or 'data' not in child:
            continue
        post = child['data']
        post_title = clean_filename(post.get('title') or post.get('name') or f'post_{idx}')
        post_folder = os.path.join(output_dir, post_title)

        media_links = extract_media_urls_from_post_data(post, headers, log_callback)
        if not media_links:
            # Fallback to minimal HTML scrape for any obvious direct links when JSON lacks media
            permalink = post.get('permalink')
            if permalink:
                try:
                    html_url = 'https://old.reddit.com' + permalink
                    resp = requests.get(html_url, headers=headers, cookies=cookies, timeout=30)
                    if resp.ok:
                        soup = BeautifulSoup(resp.text, 'html.parser')
                        media_links = get_media_links_from_post_html(soup)
                except Exception:
                    pass

        if not media_links:
            log_callback(f"[{post_title}] No media found.")
            continue

        log_callback(f"[{post_title}] Found {len(media_links)} media file(s).")
        downloaded_any = False
        for media_url in media_links:
            log_callback(f"→ {media_url}")
            result = download_file(media_url, post_folder)
            if result:
                downloaded_any = True
        if not downloaded_any:
            try:
                if os.path.isdir(post_folder):
                    try:
                        is_empty = len(os.listdir(post_folder)) == 0
                    except FileNotFoundError:
                        is_empty = False
                    if is_empty:
                        os.rmdir(post_folder)
            except Exception:
                pass

    log_callback("✅ Done downloading saved posts!")


# GUI Setup
def start_download():
    url = url_entry.get().strip()
    cookie = cookie_entry.get().strip()
    folder = folder_entry.get().strip() or os.getcwd()

    if not url or not cookie:
        messagebox.showwarning("Input Needed", "Please provide both URL and Cookie.")
        return

    def log(msg):
        output_box.insert(END, msg + "\n")
        output_box.see(END)

    Thread(target=scrape_reddit_saved, args=(url, cookie, folder, log), daemon=True).start()


def browse_folder():
    folder = filedialog.askdirectory()
    if folder:
        folder_entry.delete(0, END)
        folder_entry.insert(0, folder)


root = Tk()
root.title("Reddit Saved Media Downloader")
root.geometry("700x500")

# URL
ttk.Label(root, text="Reddit Saved URL:").pack(anchor='w', padx=10, pady=(10, 0))
url_entry = ttk.Entry(root, width=100)
url_entry.insert(0, "https://old.reddit.com/user/YOUR_USERNAME/saved/")
url_entry.pack(padx=10)

# Cookie
ttk.Label(root, text="Login Cookie:").pack(anchor='w', padx=10, pady=(10, 0))
cookie_entry = ttk.Entry(root, width=100)
cookie_entry.pack(padx=10)

# Folder
ttk.Label(root, text="Save Folder:").pack(anchor='w', padx=10, pady=(10, 0))
folder_frame = Frame(root)
folder_frame.pack(padx=10, pady=(0, 10), fill='x')
folder_entry = ttk.Entry(folder_frame, width=85)
folder_entry.pack(side='left', fill='x', expand=True)
ttk.Button(folder_frame, text="Browse", command=browse_folder).pack(side='left', padx=(5, 0))

# Download button
ttk.Button(root, text="Start Download", command=start_download).pack(pady=(0, 10))

# Output log
output_box = Text(root, height=15, wrap=WORD)
output_box.pack(fill='both', padx=10, pady=(0, 10), expand=True)

root.mainloop()
