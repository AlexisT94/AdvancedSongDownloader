# 🎧 Advanced Song Downloader

A macOS desktop app to search, preview, and download YouTube audio as high-quality MP3s — with embedded thumbnails and metadata.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![Platform](https://img.shields.io/badge/Platform-macOS-lightgrey) ![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

- **Queue tab** — paste any YouTube URL or playlist and download all tracks to MP3 (320kbps)
- **Search tab** — search YouTube directly, preview tracks before downloading
- **Live progress** — per-track status badges (Queued → % → Converting → Done / Error)
- **Embedded metadata** — thumbnail, title, and artist written into every MP3
- **Built-in updater** — check and update yt-dlp from inside the app without touching the terminal
- **Persistent player bar** — seekable playback with volume control

---

## Requirements

- macOS (tested on macOS 13+)
- Python 3.10+
- VLC installed on your machine → [videolan.org/vlc](https://www.videolan.org/vlc/)

---

## Installation

**1. Clone the repo**
```bash
git clone https://github.com/AlexisT94/AdvancedSongDownloader.git
cd AdvancedSongDownloader
```

**2. Install Python dependencies**
```bash
pip install -r requirements.txt
```

**3. Make ffmpeg executable**
```bash
chmod +x assets/ffmpeg
```

**4. Run**
```bash
python Main.py
```

---

## Project structure

```
AdvancedSongDownloader/
├── Main.py           # Application entry point
├── assets/
│   └── ffmpeg        # macOS ffmpeg binary (arm64)
├── requirements.txt
└── README.md
```

---

## Updating yt-dlp

YouTube frequently changes its internal API. If downloads start failing, open the built-in updater from the top bar (**⟳ yt-dlp** button) — it will check for a newer version and upgrade in one click without leaving the app.

---

## Notes

- **macOS only** — the bundled `ffmpeg` binary targets macOS arm64 (Apple Silicon). If you're on Intel, replace `assets/ffmpeg` with the x86_64 build from [ffmpeg.org](https://ffmpeg.org/download.html).
- Downloads go to `~/Downloads` by default. You can change this per-session using the folder picker in the app.
- VLC must be installed separately — it is not bundled.

---

## License

MIT
