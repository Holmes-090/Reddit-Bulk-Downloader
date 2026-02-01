import os
import re
import time
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse
from tkinter import *
from tkinter import ttk, messagebox, filedialog
from threading import Thread, Event

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


def clean_filename(name):
    # Sanitize filename for Windows
    sanitized = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    # Remove single quotes and other problematic characters to avoid path issues
    sanitized = sanitized.replace("'", "").replace("`", "").replace("\"", "")
    # Remove trailing dots/spaces (invalid on Windows)
    sanitized = re.sub(r'[\. ]+$', "", sanitized)
    # Replace multiple spaces with single spaces
    sanitized = re.sub(r'\s+', ' ', sanitized)
    if not sanitized:
        sanitized = "untitled"
    # Avoid Windows reserved device names
    reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
    if sanitized.upper() in reserved:
        sanitized = f"_{sanitized}_"
    
    # Limit filename length to avoid Windows path length issues
    if len(sanitized) > 100:
        sanitized = sanitized[:100].rstrip()
    
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


def download_file(url, dest_folder, filename_prefix=""):
    timeout = (15, 180)
    attempts = 2
    last_error = None
    
    # Try multiple URLs for Reddit preview links
    urls_to_try = _try_convert_reddit_preview_url(url)
    
    for attempt_url in urls_to_try:
        local_filename = attempt_url.split('/')[-1].split("?")[0]
        
        # Add prefix if provided (useful for gallery ordering)
        if filename_prefix:
            name, ext = os.path.splitext(local_filename)
            local_filename = f"{filename_prefix}_{local_filename}"
        
        filepath = os.path.join(dest_folder, local_filename)
        
        # Try downloading this URL variant
        result = _download_single_url(attempt_url, filepath, dest_folder, timeout, attempts)
        if result:
            return result
        
        last_error = f"All URL variants failed for {url}"
    
    return None


def _download_single_url(url, filepath, dest_folder, timeout, attempts):
    """Helper function to download a single URL"""
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    # Set appropriate headers based on the URL
    if 'redgifs.com' in url:
        headers['Referer'] = 'https://www.redgifs.com/'
        headers['Origin'] = 'https://www.redgifs.com'
        headers['Accept'] = '*/*'
    elif 'redd.it' in url or 'reddit.com' in url:
        # Reddit preview URLs need proper referrer and headers
        headers['Referer'] = 'https://www.reddit.com/'
        headers['Accept'] = 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
        headers['Sec-Fetch-Dest'] = 'image'
        headers['Sec-Fetch-Mode'] = 'no-cors'
        headers['Sec-Fetch-Site'] = 'cross-site'

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
            # Verify file was created and has content
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return filepath
            else:
                return None
        except Exception as e:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception:
                pass
    
    # Return None if all attempts failed
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


def _try_convert_reddit_preview_url(url: str) -> list[str]:
    """
    Convert Reddit preview URLs to potential direct media URLs.
    Reddit preview URLs often return 403, but direct media URLs work.
    """
    if not ('preview.redd.it' in url or 'external-preview.redd.it' in url):
        return [url]
    
    urls_to_try = [url]  # Always try original first
    
    try:
        # Try converting preview.redd.it to i.redd.it (direct media)
        if 'preview.redd.it' in url:
            direct_url = url.replace('preview.redd.it', 'i.redd.it')
            urls_to_try.append(direct_url)
        
        # Try removing preview parameters
        if '?' in url:
            clean_url = url.split('?')[0]
            if clean_url != url:
                urls_to_try.append(clean_url)
                # Also try the i.redd.it version of the clean URL
                if 'preview.redd.it' in clean_url:
                    direct_clean = clean_url.replace('preview.redd.it', 'i.redd.it')
                    urls_to_try.append(direct_clean)
    
    except Exception:
        pass
    
    return urls_to_try


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
        media_metadata = post_data['media_metadata']
        gallery_data = post_data.get('gallery_data', {})
        gallery_items = gallery_data.get('items', []) if isinstance(gallery_data, dict) else []
        
        # Use gallery_data order if available, otherwise use media_metadata keys
        if gallery_items:
            # Process in the order specified by gallery_data
            for gallery_item in gallery_items:
                if not isinstance(gallery_item, dict):
                    continue
                media_id = gallery_item.get('media_id')
                if not media_id or media_id not in media_metadata:
                    continue
                item = media_metadata[media_id]
                if not isinstance(item, dict):
                    continue
                
                # Extract URL and decode HTML entities
                url = None
                # Prefer source (original) quality over preview
                source = item.get('s') or {}
                url = source.get('u') or source.get('url')
                
                # If no source URL, try the highest resolution preview
                if not url:
                    previews = item.get('p') or []
                    if previews:
                        best = previews[-1]
                        url = best.get('u') or best.get('url')
                
                if url:
                    # Decode HTML entities in URLs (Reddit sometimes encodes &amp; etc.)
                    import html as html_module
                    url = html_module.unescape(url)
                    media_urls.append(url.split('?')[0])
        else:
            # Fallback: process all media_metadata items (no guaranteed order)
            for item in media_metadata.values():
                if not isinstance(item, dict):
                    continue
                # Prefer source (original) quality over preview
                url = None
                source = item.get('s') or {}
                url = source.get('u') or source.get('url')
                
                # If no source URL, try the highest resolution preview
                if not url:
                    previews = item.get('p') or []
                    if previews:
                        best = previews[-1]
                        url = best.get('u') or best.get('url')
                
                if url:
                    # Decode HTML entities in URLs
                    import html as html_module
                    url = html_module.unescape(url)
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


def scrape_reddit_saved(url, cookies_str, output_dir, log_callback, pause_event=None, stop_event=None):
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
        # Check for stop
        if stop_event and stop_event.is_set():
            log_callback("⏹ Stopped downloading.")
            return
        
        # Wait if paused
        if pause_event and pause_event.is_set():
            while pause_event.is_set() and not (stop_event and stop_event.is_set()):
                time.sleep(0.1)
            if stop_event and stop_event.is_set():
                log_callback("⏹ Stopped downloading.")
                return
        
        if not isinstance(child, dict) or 'data' not in child:
            continue
        post = child['data']
        post_title = clean_filename(post.get('title') or post.get('name') or f'post_{idx}')
        post_folder = os.path.join(output_dir, post_title)
        log_callback(f"Processing post: '{post_title}' -> {post_folder}")

        # Check for stop before processing
        if stop_event and stop_event.is_set():
            log_callback("⏹ Stopped downloading.")
            return

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
        
        # Check if this is a gallery to add numbering
        is_gallery = post.get('is_gallery', False)
        
        for media_idx, media_url in enumerate(media_links, 1):
            # Check for stop before each download
            if stop_event and stop_event.is_set():
                log_callback("⏹ Stopped downloading.")
                return
            
            # Wait if paused
            if pause_event and pause_event.is_set():
                while pause_event.is_set() and not (stop_event and stop_event.is_set()):
                    time.sleep(0.1)
                if stop_event and stop_event.is_set():
                    log_callback("⏹ Stopped downloading.")
                    return
            
            log_callback(f"→ {media_url}")
            
            # Add numbering for gallery images to maintain order
            filename_prefix = f"{media_idx:02d}" if is_gallery and len(media_links) > 1 else ""
            
            result = download_file(media_url, post_folder, filename_prefix)
            if result:
                downloaded_any = True
                log_callback(f"  ✓ Saved to: {result}")
            else:
                log_callback(f"  ✗ Failed to download: {media_url}")
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

    if not (stop_event and stop_event.is_set()):
        log_callback("✅ Done downloading saved posts!")


# GUI Setup
# Progress tracking variables
progress_state = {"total": 0, "current": 0, "active": False}
# Download control variables
pause_event = Event()
stop_event = Event()
download_thread = None

def restore_start_button():
    pause_btn.pack_forget()
    stop_btn.pack_forget()
    download_btn.pack(ipadx=25, ipady=8)

def start_download():
    global download_thread
    
    url = url_entry.get().strip()
    cookie = cookie_entry.get().strip()
    folder = folder_entry.get().strip() or os.getcwd()

    if not url or not cookie:
        messagebox.showwarning("Input Needed", "Please provide both URL and Cookie.")
        return

    # Reset progress and control events
    progress_state["total"] = 0
    progress_state["current"] = 0
    progress_state["active"] = True
    pause_event.clear()
    stop_event.clear()
    progress_label.config(text="")
    progress_label.pack_forget()  # Hide initially
    output_box.delete(1.0, END)  # Clear previous log
    
    # Update UI to show pause/stop buttons
    download_btn.pack_forget()
    pause_btn.pack(side='left', padx=(0, 8), ipadx=20, ipady=8)
    stop_btn.pack(side='left', ipadx=20, ipady=8)

    def log(msg):
        # Update GUI on main thread
        root.after(0, lambda: output_box.insert(END, msg + "\n"))
        root.after(0, lambda: output_box.see(END))
        
        # Parse "Found X saved items" message to extract total
        if "Found" in msg and "saved items" in msg:
            match = re.search(r'Found (\d+) saved items', msg)
            if match:
                progress_state["total"] = int(match.group(1))
                progress_state["current"] = 0
                root.after(0, update_progress_label)
        
        # Track when processing posts
        if "Processing post:" in msg:
            progress_state["current"] += 1
            root.after(0, update_progress_label)
        
        # Hide progress when done
        if "Done downloading" in msg or "✅" in msg or "Stopped" in msg:
            progress_state["active"] = False
            root.after(100, lambda: progress_label.pack_forget())
            root.after(100, restore_start_button)

    def update_progress_label():
        if progress_state["active"] and progress_state["total"] > 0:
            current = progress_state["current"]
            total = progress_state["total"]
            percentage = int((current / total) * 100) if total > 0 else 0
            progress_text = f"{current}/{total} ({percentage}%)"
            progress_label.config(text=progress_text)
            if not progress_label.winfo_viewable():
                progress_label.pack(side='right')

    download_thread = Thread(target=scrape_reddit_saved, args=(url, cookie, folder, log, pause_event, stop_event), daemon=True)
    download_thread.start()

def pause_download():
    if pause_event.is_set():
        # Resume
        pause_event.clear()
        pause_btn.config(text="⏸ Pause Download")
    else:
        # Pause
        pause_event.set()
        pause_btn.config(text="▶ Resume Download")

def stop_download():
    stop_event.set()
    pause_event.clear()  # Clear pause so we can exit
    progress_state["active"] = False
    root.after(100, restore_start_button)


def browse_folder():
    folder = filedialog.askdirectory()
    if folder:
        folder_entry.delete(0, END)
        folder_entry.insert(0, folder)


def create_tooltip(widget, text, delay_ms=500):
    """Show a tooltip on hover, hide on leave. Does not take layout space."""
    tooltip_window = None
    after_id = None

    def show_tooltip(event):
        nonlocal tooltip_window, after_id
        if after_id:
            root.after_cancel(after_id)
            after_id = None
        if tooltip_window:
            return
        def do_show():
            nonlocal tooltip_window
            if tooltip_window:
                return
            tooltip_window = Toplevel(root)
            tooltip_window.overrideredirect(True)
            tooltip_window.withdraw()
            lbl = Label(tooltip_window, text=text, font=("Segoe UI", 9),
                        bg="#2d2d2d", fg="#e0e0e0", relief='solid', bd=1,
                        padx=10, pady=8, wraplength=320, justify='left')
            lbl.pack()
            tooltip_window.update_idletasks()
            x = widget.winfo_rootx() + 16
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tooltip_window.geometry(f"+{x}+{y}")
            tooltip_window.deiconify()
        after_id = root.after(delay_ms, do_show)

    def hide_tooltip(event):
        nonlocal tooltip_window, after_id
        if after_id:
            root.after_cancel(after_id)
            after_id = None
        if tooltip_window:
            tooltip_window.destroy()
            tooltip_window = None

    widget.bind('<Enter>', show_tooltip)
    widget.bind('<Leave>', hide_tooltip)


def create_smooth_help_icon(parent, bg_color, size=22):
    """Create a smooth, anti-aliased '?' in circle icon using PIL (high-res render + downscale). Returns (photo_image, label_widget) or (None, canvas_widget) if PIL unavailable."""
    if not _PIL_AVAILABLE:
        return None, None
    try:
        scale = 3
        w, h = size * scale, size * scale
        bg = bg_color.lstrip("#")
        bg_rgb = tuple(int(bg[i:i+2], 16) for i in (0, 2, 4))
        img = Image.new("RGB", (w, h), bg_rgb)
        draw = ImageDraw.Draw(img)
        # White circle ring: outer white, inner bg by drawing filled white circle then smaller filled bg circle
        margin = scale * 2
        draw.ellipse([margin, margin, w - margin, h - margin], fill=(255, 255, 255), outline=None)
        inner = scale * 3
        draw.ellipse([inner, inner, w - inner, h - inner], fill=bg_rgb, outline=None)
        # White "?" in center
        try:
            font = ImageFont.truetype("segoeui.ttf", 14 * scale)
        except OSError:
            try:
                font = ImageFont.truetype("arial.ttf", 14 * scale)
            except OSError:
                font = ImageFont.load_default()
        text = "?"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (w - tw) // 2 - bbox[0]
        y = (h - th) // 2 - bbox[1]
        draw.text((x, y), text, fill=(255, 255, 255), font=font)
        resample = getattr(Image, "Resampling", None) and Image.Resampling.LANCZOS or getattr(Image, "LANCZOS", Image.BICUBIC)
        img_small = img.resize((size, size), resample)
        photo = ImageTk.PhotoImage(img_small)
        label = Label(parent, image=photo, bg=bg_color, cursor="question_arrow")
        label._photo = photo
        return photo, label
    except Exception:
        return None, None


root = Tk()
root.title("Reddit Saved Media Downloader")
root.geometry("750x600")

# Configure dark mode color scheme
bg_color = "#1e1e1e"  # Dark background
section_bg = "#2d2d2d"  # Darker section background
accent_color = "#ff4500"  # Reddit orange
text_color = "#e0e0e0"  # Light text
text_color_secondary = "#b0b0b0"  # Secondary text
border_color = "#404040"  # Dark border
entry_bg = "#1a1a1a"  # Even darker for entries
entry_fg = "#ffffff"  # White text in entries

root.configure(bg=bg_color)

# Configure ttk style for dark mode
style = ttk.Style()
style.theme_use('clam')

# Configure Entry style for dark mode
style.configure("TEntry",
               fieldbackground=entry_bg,
               foreground="#888888",  # Greyed out text for placeholder
               borderwidth=1,
               relief='flat')

# Configure Button style for dark mode
style.configure("TButton",
               background=section_bg,
               foreground=text_color,
               borderwidth=1,
               relief='flat',
               padding=5)
style.map("TButton",
         background=[('active', '#3d3d3d')],
         relief=[('pressed', 'sunken')])

# Configure Accent button style
style.configure("Accent.TButton",
               background=accent_color,
               foreground="#ffffff",
               font=("Segoe UI", 10, "bold"),
               padding=(20, 8))
style.map("Accent.TButton",
         background=[('active', '#ff5500')],
         relief=[('pressed', 'sunken')])

# Configure Stop button style (red/danger)
style.configure("Stop.TButton",
               background="#d32f2f",
               foreground="#ffffff",
               font=("Segoe UI", 10, "bold"),
               padding=(20, 8))
style.map("Stop.TButton",
         background=[('active', '#b71c1c')],
         relief=[('pressed', 'sunken')])

# Configure Scrollbar style
style.configure("TScrollbar",
               background=section_bg,
               troughcolor=bg_color,
               borderwidth=0,
               arrowcolor=text_color,
               darkcolor=section_bg,
               lightcolor=section_bg)

# Compact header section
header_frame = Frame(root, bg=section_bg, relief='flat', bd=0)
header_frame.pack(fill='x', padx=12, pady=(10, 8))

title_label = Label(header_frame, text="Reddit Bulk Downloader", 
                    font=("Segoe UI", 16, "bold"), 
                    bg=section_bg, fg=text_color)
title_label.pack(pady=(10, 3))

subtitle_label = Label(header_frame, text="Download your saved Reddit posts and media", 
                      font=("Segoe UI", 8), 
                      bg=section_bg, fg=text_color_secondary)
subtitle_label.pack(pady=(0, 10))

# Main content frame
main_frame = Frame(root, bg=bg_color)
main_frame.pack(fill='both', expand=True, padx=12, pady=(0, 12))

# Compact input section
input_section = Frame(main_frame, bg=section_bg, relief='flat', bd=1)
input_section.pack(fill='x', pady=(0, 10))

# Section title
section_title = Label(input_section, text="Configuration", 
                     font=("Segoe UI", 10, "bold"), 
                     bg=section_bg, fg=text_color, anchor='w')
section_title.pack(fill='x', padx=15, pady=(12, 10))

# URL field
url_container = Frame(input_section, bg=section_bg)
url_container.pack(fill='x', padx=15, pady=(0, 10))

url_label = Label(url_container, text="Reddit Saved URL", 
                 font=("Segoe UI", 8), 
                 bg=section_bg, fg=text_color_secondary, anchor='w')
url_label.pack(fill='x', pady=(0, 4))

# Use regular Entry for URL field to allow individual color control
url_entry = Entry(url_container, width=100, font=("Segoe UI", 9),
                 bg=entry_bg, fg="#666666",  # Greyed out placeholder color
                 insertbackground=text_color,
                 selectbackground="#404040",
                 selectforeground=text_color,
                 relief='flat', bd=1,
                 highlightthickness=1,
                 highlightcolor=accent_color,
                 highlightbackground=border_color)
placeholder_text = " https://reddit.com/user/YOUR_USERNAME/saved/ "
url_entry.insert(0, placeholder_text)
url_entry.pack(fill='x', ipady=5)

# Make placeholder text greyed out, turn white when user types
def on_url_focus_in(event):
    if url_entry.get() == placeholder_text:
        url_entry.delete(0, END)
        url_entry.config(fg=entry_fg)
    else:
        url_entry.config(fg=entry_fg)

def on_url_focus_out(event):
    if url_entry.get().strip() == "":
        url_entry.insert(0, placeholder_text)
        url_entry.config(fg="#666666")

def on_url_key(event):
    if url_entry.get() != placeholder_text:
        url_entry.config(fg=entry_fg)

url_entry.bind('<FocusIn>', on_url_focus_in)
url_entry.bind('<FocusOut>', on_url_focus_out)
url_entry.bind('<Key>', on_url_key)

# Cookie field
cookie_container = Frame(input_section, bg=section_bg)
cookie_container.pack(fill='x', padx=15, pady=(0, 10))

cookie_label_row = Frame(cookie_container, bg=section_bg)
cookie_label_row.pack(fill='x', pady=(0, 4))
cookie_label = Label(cookie_label_row, text="Login Cookie", 
                    font=("Segoe UI", 8), 
                    bg=section_bg, fg=text_color_secondary, anchor='w')
cookie_label.pack(side='left')
# Help icon: smooth white circle + "?" (PIL high-res + downscale for anti-aliasing; fallback Canvas if no PIL)
_help_icon_size = 22
cookie_help_icon_photo, cookie_help_icon_label = create_smooth_help_icon(cookie_label_row, section_bg, _help_icon_size)
if cookie_help_icon_label is not None:
    cookie_help_icon = cookie_help_icon_label
    cookie_help_icon.pack(side='left', padx=(4, 0))
else:
    cookie_help_icon = Canvas(cookie_label_row, width=_help_icon_size, height=_help_icon_size,
                              bg=section_bg, highlightthickness=0, cursor="question_arrow")
    cookie_help_icon.pack(side='left', padx=(4, 0))
    cookie_help_icon.create_oval(2, 2, _help_icon_size - 2, _help_icon_size - 2,
                                 outline="#ffffff", width=1.5, fill=section_bg)
    cookie_help_icon.create_text(_help_icon_size // 2, _help_icon_size // 2, text="?",
                                 fill="#ffffff", font=("Segoe UI", 11, "bold"))
create_tooltip(cookie_help_icon,
    "This is your Reddit session cookie. You can get it from your browser's developer tools (Network or Application tab) or by exporting request headers with a browser extension. Paste the full Cookie header string here.")

cookie_entry = Entry(cookie_container, width=100, font=("Segoe UI", 9),
                    bg=entry_bg, fg=entry_fg,
                    insertbackground=text_color,
                    selectbackground="#404040",
                    selectforeground=text_color,
                    relief='flat', bd=1,
                    highlightthickness=0)  # No border
cookie_entry.pack(fill='x', ipady=5)

# Folder field
folder_container = Frame(input_section, bg=section_bg)
folder_container.pack(fill='x', padx=15, pady=(0, 12))

folder_label = Label(folder_container, text="Output Folder", 
                    font=("Segoe UI", 8), 
                    bg=section_bg, fg=text_color_secondary, anchor='w')
folder_label.pack(fill='x', pady=(0, 4))

folder_frame = Frame(folder_container, bg=section_bg)
folder_frame.pack(fill='x')
folder_entry = Entry(folder_frame, width=85, font=("Segoe UI", 9),
                     bg=entry_bg, fg=entry_fg,
                     insertbackground=text_color,
                     selectbackground="#404040",
                     selectforeground=text_color,
                     relief='flat', bd=1,
                     highlightthickness=0)  # No border
folder_entry.pack(side='left', fill='x', expand=True, ipady=5)
browse_btn = Button(folder_frame, text="Browse", command=browse_folder,
                   bg=section_bg, fg=text_color,
                   activebackground="#3d3d3d",
                   activeforeground=text_color,
                   font=("Segoe UI", 9),
                   relief='solid', bd=1,
                   highlightthickness=0,
                   padx=12, pady=5)
browse_btn.pack(side='left', padx=(6, 0))

# Download button section
button_frame = Frame(main_frame, bg=bg_color)
button_frame.pack(fill='x', pady=(0, 10))

download_btn = ttk.Button(button_frame, text="▶ Start Download", 
                         command=start_download, 
                         style="Accent.TButton")
download_btn.pack(ipadx=25, ipady=8)

# Pause and Stop buttons (initially hidden)
pause_btn = ttk.Button(button_frame, text="⏸ Pause Download", 
                      command=pause_download,
                      style="Accent.TButton")

stop_btn = ttk.Button(button_frame, text="⏹ Stop Download", 
                     command=stop_download,
                     style="Stop.TButton")

# Output log section - takes remaining space
log_section = Frame(main_frame, bg=section_bg, relief='flat', bd=1)
log_section.pack(fill='both', expand=True)

# Title bar with progress indicator on the right
title_frame = Frame(log_section, bg=section_bg)
title_frame.pack(fill='x', padx=15, pady=(12, 8))

log_title = Label(title_frame, text="Download Progress", 
                 font=("Segoe UI", 10, "bold"), 
                 bg=section_bg, fg=text_color, anchor='w')
log_title.pack(side='left')

# Progress indicator (initially hidden, appears on the right)
progress_label = Label(title_frame, text="", 
                      font=("Segoe UI", 10, "bold"), 
                      bg=section_bg, fg=accent_color, anchor='e')

# Output box with scrollbar
log_container = Frame(log_section, bg=section_bg)
log_container.pack(fill='both', expand=True, padx=15, pady=(0, 12))

scrollbar = ttk.Scrollbar(log_container)
scrollbar.pack(side='right', fill='y')

output_box = Text(log_container, wrap=WORD, 
                 font=("Consolas", 8), 
                 bg=entry_bg, fg="#d0d0d0",
                 relief='flat', bd=0,
                 yscrollcommand=scrollbar.set,
                 padx=8, pady=8,
                 insertbackground=text_color,
                 selectbackground="#404040",
                 selectforeground=text_color)
output_box.pack(side='left', fill='both', expand=True)

scrollbar.config(command=output_box.yview)

root.mainloop()
