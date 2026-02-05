# Reddit Saved Posts Media Downloader

A desktop tool for downloading and archiving media (images, GIFs, and videos) from your Reddit saved posts.

![Version](https://img.shields.io/badge/version-1.0-blue)
![Python](https://img.shields.io/badge/python-3.7+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Bulk Download** - Download all media from your saved Reddit posts at once
- **Auto-Organization** - Each post is saved in its own folder with a clean filename
- **Dark Mode UI** - Modern, easy-to-use graphical interface
- **Pause & Resume** - Control your downloads with pause/resume/stop buttons
- **Progress Tracking** - Real-time progress indicator and detailed logging
- **Multi-Host Support** - Works with Reddit, Imgur, Redgifs, and other common hosts
- **Gallery Support** - Properly handles Reddit gallery posts with multiple images

## Installation

### Requirements
- Python 3.7 or higher
- pip (Python package manager)

### Setup

1. **Clone or download this repository**
   ```bash
   git clone https://github.com/yourusername/reddit-saved-downloader.git
   cd reddit-saved-downloader
   ```

2. **Install dependencies**
   ```bash
   pip install requests beautifulsoup4 pillow
   ```

3. **Run the application**
   ```bash
   python reddit_downloader.py
   ```

## Usage

### Step 1: Get Your Reddit Saved Posts URL
1. Log into Reddit in your web browser
2. Navigate to your saved posts: `https://reddit.com/user/YOUR_USERNAME/saved/`
3. Copy the URL from your browser's address bar

### Step 2: Get Your Cookie Header String
Your Reddit session cookie header is required to access your saved posts (just like being logged in).

**IMPORTANT:** You need the complete **Cookie header string** from your browser, not individual cookie values.

**Method 1: Using Browser Extension (Easiest)**
1. Install the "Cookie-Editor" browser extension (available for Chrome, Firefox, Edge)
2. While logged into Reddit, click the Cookie-Editor icon
3. Click "Export" and choose "Header String" format
4. Copy the exported string

**Method 2: Using Browser DevTools**
1. While logged into Reddit, press **F12** to open Developer Tools
2. Go to the **Network** tab
3. Refresh the page (F5)
4. Click on any request to `reddit.com`
5. Scroll down to **Request Headers**
6. Find the **Cookie:** header
7. Copy the entire value after "Cookie: " (everything on that line)

**Example cookie header format:**
```
session=abc123...; token_v2=xyz789...; reddit_session=def456...
```

The cookie string should contain multiple cookies separated by semicolons.

### Step 3: Download Your Media
1. Paste your Reddit saved posts URL into the first field
2. Paste your cookie header string into the second field
3. Choose where to save your downloads (or leave default)
4. Click "Start Download"
5. Use "Pause" or "Stop" if needed

## Security & Privacy

### Important Security Notes

- **Never share your cookies publicly** - Treat them like passwords. Anyone with your cookies can access your Reddit account.
- **Cookies expire** - If downloads fail with authentication errors, get fresh cookies from your browser.
- **Personal use only** - This tool is designed for downloading your own saved posts from your own account.
- **Cookie handling** - Cookies are only used locally during the download session and are never stored or transmitted anywhere.

### Safety Considerations

- **Trusted sources only** - The tool downloads files from URLs in your saved posts. Only use this on accounts you trust and posts you've saved yourself.
- **Copyright awareness** - Downloaded content may be copyrighted. Ensure you have the right to save and use the media.
- **Filename sanitization** - Files are automatically saved with sanitized filenames to prevent system issues.
- **Rate limiting** - The tool includes built-in delays to respect Reddit's servers.

## Troubleshooting

### "Authentication failed" or "401/403 errors"
- Your cookies may have expired. Get fresh cookies from your browser.
- Make sure you copied the entire cookie header string.
- Ensure you're logged into Reddit in the browser you're copying cookies from.

### "No saved items found"
- Verify the URL points to your saved posts page.
- Check that your cookies are from a logged-in session.
- Make sure you actually have saved posts.

### Downloads are slow
- This is normal for large batches. Use the pause feature if needed.
- The tool includes rate limiting to avoid overloading Reddit's servers.

### Some media files failed to download
- Some external hosts may have removed the content.
- Preview URLs sometimes fail - the tool will log which URLs failed.
- You can check the log for specific error messages.

## Supported Media Hosts

- Reddit (i.redd.it, v.redd.it)
- Imgur
- Redgifs
- Gfycat (via Redgifs)
- Direct image/video URLs (.jpg, .png, .gif, .mp4, .webp)

## File Organization

Downloads are organized as follows:
```
output_folder/
├── Post_Title_1/
│   ├── image1.jpg
│   └── image2.png
├── Post_Title_2/
│   ├── 01_gallery_image1.jpg
│   ├── 02_gallery_image2.jpg
│   └── 03_gallery_image3.jpg
└── Post_Title_3/
    └── video.mp4
```

## Technical Details

- **Language:** Python 3.7+
- **GUI Framework:** tkinter (built into Python)
- **Dependencies:** requests, beautifulsoup4, Pillow (optional, for high-quality UI icons)
- **Download Method:** Direct HTTP requests (no Reddit API)

## Known Limitations

- Cannot download content from private/deleted posts
- Some external hosts may block automated downloads
- Reddit preview URLs sometimes return 403 errors (the tool tries alternative URLs)
- Very old posts may have broken media links

## Disclaimer

This tool is intended for **personal archival use only**. 

- **Copyright:** Do not use this to download copyrighted content you do not own or have permission to save.
- **Purpose:** Designed for users to create backups of their own saved posts.
- **Terms of Service:** Use of this tool should comply with Reddit's Terms of Service.
- **Liability:** The developer is not responsible for how this tool is used.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built for the Reddit community
- Uses BeautifulSoup for HTML parsing
- Thanks to all contributors and users

---

**Note:** This is an unofficial tool and is not affiliated with Reddit, Inc.
