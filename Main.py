import yt_dlp
import tkinter as tk
from tkinter import ttk, filedialog
from threading import Thread, Event
from concurrent.futures import ThreadPoolExecutor, as_completed
import vlc
import os
import sys
import time
import subprocess
import importlib

# ─────────────────────────────────────────
#  GLOBALS
# ─────────────────────────────────────────

download_path  = os.path.expanduser("~/Downloads")
player         = None
player_media   = None
is_playing     = False
seek_dragging  = False

# url -> { "iid", "title", "duration", "stop_event" }
queue_items: dict = {}

# Thread pool: up to 3 simultaneous downloads
download_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="dl")

# Thread pool: up to 5 simultaneous info-fetches for search enrichment
search_executor   = ThreadPoolExecutor(max_workers=5, thread_name_prefix="srch")


# ─────────────────────────────────────────
#  FFMPEG PATH
# ─────────────────────────────────────────

def get_ffmpeg_path():
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.abspath(".")
    return os.path.join(base, "assets", "ffmpeg")


print(get_ffmpeg_path())

# ─────────────────────────────────────────
#  THEME CONSTANTS
# ─────────────────────────────────────────

BG        = "#0e0e10"
BG2       = "#18181b"
BG3       = "#27272a"
BORDER    = "#3f3f46"
FG        = "#fafafa"
FG2       = "#a1a1aa"
FG3       = "#71717a"
ACCENT    = "#6366f1"
ACCENT2   = "#818cf8"
SUCCESS   = "#22c55e"
WARNING   = "#f59e0b"
DANGER    = "#ef4444"
INFO      = "#38bdf8"
STOPPED   = "#a1a1aa"
FONT      = "SF Pro Display"
FONT_MONO = "SF Mono"


# ─────────────────────────────────────────
#  YT-DLP AUTO UPDATE
# ─────────────────────────────────────────

import re as _re

try:
    from packaging.version import Version as _V
    def _norm_version(v):
        try:
            return _V(v)
        except Exception:
            return tuple(int(x) for x in v.split("."))
except ImportError:
    # packaging not available (e.g. stripped PyInstaller bundle)
    def _norm_version(v):
        """Normalize '2026.03.17' == '2026.3.17' by parsing each segment as int."""
        try:
            return tuple(int(x) for x in v.split("."))
        except Exception:
            return (0,)


def get_ytdlp_version():
    try:
        return yt_dlp.version.__version__
    except Exception:
        return "unknown"


def _find_python():
    """Return the Python executable to use for pip calls."""
    return sys.executable


def check_ytdlp_update(callback):
    """Background thread: calls callback('up_to_date'|'available'|'error', info)."""
    def _worker():
        python = _find_python()
        try:
            result = subprocess.run(
                [python, "-m", "pip", "index", "versions", "yt-dlp"],
                capture_output=True, text=True, timeout=15
            )
            match = _re.search(r"yt-dlp\s*\(([^)]+)\)", result.stdout)
            if match:
                latest  = match.group(1).strip().split(",")[0].strip()
                current = get_ytdlp_version()
                if _norm_version(latest) > _norm_version(current):
                    root.after(0, lambda: callback("available", latest))
                else:
                    root.after(0, lambda: callback("up_to_date", current))
            else:
                root.after(0, lambda: callback("error", "Could not parse version"))
        except Exception as e:
            root.after(0, lambda: callback("error", str(e)))
    Thread(target=_worker, daemon=True).start()


def update_ytdlp(on_progress, on_done):
    """Background thread: streams pip output, reloads module, calls on_done(bool, str)."""
    def _worker():
        python = _find_python()
        try:
            proc = subprocess.Popen(
                [python, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in proc.stdout:
                line = line.strip()
                if line:
                    root.after(0, lambda l=line: on_progress(l))
            proc.wait()
            if proc.returncode == 0:
                try:
                    importlib.reload(yt_dlp)
                    importlib.reload(yt_dlp.version)
                except Exception:
                    pass
                new_ver = get_ytdlp_version()
                root.after(0, lambda: on_done(True, new_ver))
            else:
                root.after(0, lambda: on_done(False, "pip exited with error"))
        except Exception as e:
            root.after(0, lambda: on_done(False, str(e)))
    Thread(target=_worker, daemon=True).start()


def open_update_dialog():
    win = tk.Toplevel(root)
    win.title("Update yt-dlp")
    win.geometry("420x300")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.grab_set()

    current    = get_ytdlp_version()
    can_update = False   # flipped to True once check finds a newer version

    tk.Label(win, text="yt-dlp updater",
             font=(FONT, 14, "bold"), bg=BG, fg=FG).pack(pady=(18, 2))

    status_var = tk.StringVar(value=f"Installed: {current}  —  Checking for updates…")
    tk.Label(win, textvariable=status_var,
             font=(FONT, 11), bg=BG, fg=FG2).pack()

    # Button row packed FIRST so it anchors to bottom before log takes remaining space
    btn_frame = tk.Frame(win, bg=BG)
    btn_frame.pack(side="bottom", pady=14)

    log_frame = tk.Frame(win, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
    log_frame.pack(fill="both", expand=True, padx=18, pady=(12, 0))

    log_box = tk.Text(
        log_frame, bg=BG2, fg=FG2, insertbackground=FG,
        relief="flat", bd=0, font=(FONT_MONO, 10),
        state="disabled", wrap="word", padx=8, pady=6
    )
    log_box.pack(fill="both", expand=True)

    def log(text):
        log_box.config(state="normal")
        log_box.insert(tk.END, text + "\n")
        log_box.see(tk.END)
        log_box.config(state="disabled")

    # ── Update button: a plain Label styled as a button.
    # We toggle its appearance and click-behaviour after the version check.
    update_lbl = tk.Label(
        btn_frame, text="Update now",
        bg=BG3, fg=FG3,          # greyed out until check passes
        relief="flat", bd=0,
        padx=14, pady=6,
        font=(FONT, 12), cursor="arrow"
    )
    update_lbl.pack(side="left", padx=(0, 8))
    styled_btn(btn_frame, "Close", win.destroy).pack(side="left")

    def _enable_update_btn():
        """Make the update button live once we know an update is available."""
        update_lbl.config(bg=ACCENT, fg="#ffffff", cursor="hand2")

        def on_enter(e):  update_lbl.config(bg=ACCENT2)
        def on_leave(e):  update_lbl.config(bg=ACCENT)
        def on_click(e):
            if not can_update:
                return
            # Disable immediately so it can't be double-clicked
            update_lbl.config(bg=BG3, fg=FG3, cursor="arrow")
            update_lbl.unbind("<Enter>")
            update_lbl.unbind("<Leave>")
            update_lbl.unbind("<ButtonPress-1>")
            _start_update()

        update_lbl.bind("<Enter>",         on_enter)
        update_lbl.bind("<Leave>",         on_leave)
        update_lbl.bind("<ButtonPress-1>", on_click)

    def _start_update():
        status_var.set("Updating…")
        log("Running: pip install --upgrade yt-dlp\n")

        def on_done(success, msg):
            if success:
                status_var.set(f"Done — now running yt-dlp {msg}")
                log(f"\nUpdated to {msg}.")
                log("Reload applied in-process — no restart needed.")
                ytdlp_ver_var.set(f"yt-dlp {msg}")
                update_notif_var.set("")
            else:
                status_var.set("Update failed")
                log(f"\nError: {msg}")

        update_ytdlp(log, on_done)

    def on_check(status, info):
        nonlocal can_update
        if status == "up_to_date":
            status_var.set(f"Already up to date ({info})")
            log(f"yt-dlp {info} is the latest version.")
        elif status == "available":
            can_update = True
            status_var.set(f"Update available:  {current}  →  {info}")
            log(f"Installed : {current}")
            log(f"Latest    : {info}")
            log("\nClick \'Update now\' to upgrade.")
            _enable_update_btn()
        else:
            status_var.set(f"Check failed: {info}")
            log(f"Error: {info}")

    check_ytdlp_update(on_check)





# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def fmt_duration(seconds):
    if not seconds:
        return "?:??"
    h, rem = divmod(int(seconds), 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def fmt_views(n):
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M views"
    if n >= 1_000:
        return f"{n/1_000:.0f}K views"
    return f"{n} views"

def truncate(text, max_len=52):
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


# ─────────────────────────────────────────
#  DOWNLOAD
# ─────────────────────────────────────────

def build_ydl_opts(progress_hook=None):
    opts = {
        "format"          : "bestaudio/best",
        "outtmpl"         : f"{download_path}/%(title)s.%(ext)s",
        "ffmpeg-location" : get_ffmpeg_path(),
        "quiet"           : True,
        "ignoreerrors"    : True,
        "writethumbnail"  : True,
        "extractor_args"  : {
            "youtube": {"player_client": ["android", "ios", "tv"]}
        },
        "http_headers"    : {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; "
                "rv:147.0) Gecko/20100101 Firefox/147.0"
            )
        },
        "postprocessors"  : [
            {"key": "FFmpegExtractAudio",
             "preferredcodec": "mp3", "preferredquality": "320"},
            {"key": "EmbedThumbnail"},
            {"key": "FFmpegMetadata", "add_metadata": True},
        ],
    }
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]
    return opts


def download_url(url, iid, stop_event: Event):
    """
    Download a single URL on a pool thread.
    stop_event.set() cancels at the next progress callback.
    """

    def hook(d):
        if stop_event.is_set():
            raise yt_dlp.utils.DownloadError("Cancelled by user")

        if d["status"] == "downloading":
            total      = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            pct        = int(downloaded / total * 100) if total else 0
            speed      = d.get("_speed_str", "").strip()
            root.after(0, lambda p=pct, s=speed: queue_update_row(
                iid, status="downloading", pct=p, note=s
            ))
        elif d["status"] == "finished":
            root.after(0, lambda: queue_update_row(iid, status="converting"))

    if stop_event.is_set():
        root.after(0, lambda: queue_update_row(iid, status="stopped"))
        return

    try:
        with yt_dlp.YoutubeDL(build_ydl_opts(hook)) as ydl:
            ydl.download([url])

        if stop_event.is_set():
            root.after(0, lambda: queue_update_row(iid, status="stopped"))
        else:
            root.after(0, lambda: queue_update_row(iid, status="done"))

    except Exception as e:
        msg = str(e)[:60]
        if stop_event.is_set() or "Cancelled" in msg:
            root.after(0, lambda: queue_update_row(iid, status="stopped"))
        else:
            root.after(0, lambda m=msg: queue_update_row(iid, status="error", note=m))


def queue_update_row(iid, status, pct=0, note=""):
    colors = {
        "queued"     : FG3,
        "fetching"   : FG2,
        "downloading": INFO,
        "converting" : WARNING,
        "done"       : SUCCESS,
        "error"      : DANGER,
        "stopped"    : STOPPED,
    }
    labels = {
        "queued"     : "Queued",
        "fetching"   : "Fetching…",
        "downloading": f"{pct}%",
        "converting" : "Converting…",
        "done"       : "Done",
        "error"      : "Error",
        "stopped"    : "Stopped",
    }
    try:
        queue_tree.set(iid, "status", labels.get(status, status))
        queue_tree.set(iid, "note",   note)
        queue_tree.item(iid, tags=(status,))
        queue_tree.tag_configure(status, foreground=colors.get(status, FG))
    except tk.TclError:
        pass


def add_urls_from_box():
    raw = url_input.get().strip()
    if not raw or raw == "Paste YouTube URL or playlist…":
        return
    url_input.delete(0, tk.END)

    for url in raw.replace(",", "\n").split("\n"):
        url = url.strip()
        if not url or url in queue_items:
            continue

        iid        = queue_tree.insert(
            "", tk.END,
            values=(truncate(url, 48), "?:??", "—", "Queued", ""),
            tags=("queued",)
        )
        stop_event = Event()
        queue_items[url] = {"iid": iid, "stop_event": stop_event}
        queue_tree.tag_configure("queued", foreground=FG3)

        # Submit to thread pool — runs up to 3 in parallel
        download_executor.submit(fetch_and_download, url, iid, stop_event)


def fetch_and_download(url, iid, stop_event: Event):
    """Fetch metadata then download — all on the pool thread."""
    if stop_event.is_set():
        root.after(0, lambda: queue_update_row(iid, status="stopped"))
        return

    root.after(0, lambda: queue_update_row(iid, status="fetching"))

    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info  = ydl.extract_info(url, download=False)
            title = info.get("title", url)
            dur   = fmt_duration(info.get("duration"))
            chan  = info.get("uploader", "—")

        root.after(0, lambda t=title, d=dur, c=chan: queue_tree.item(
            iid, values=(truncate(t, 48), d, c, "Queued", "")
        ))
        queue_items[url].update({"title": title, "duration": dur})

    except Exception:
        pass   # non-fatal — still attempt download

    if not stop_event.is_set():
        download_url(url, iid, stop_event)


def stop_download(url):
    """Signal the download thread for this URL to stop."""
    data = queue_items.get(url)
    if data:
        data["stop_event"].set()
        root.after(0, lambda: queue_update_row(data["iid"], status="stopped"))


def stop_selected_download():
    sel = queue_tree.selection()
    if not sel:
        return
    iid = sel[0]
    for url, data in queue_items.items():
        if data["iid"] == iid:
            stop_download(url)
            break


def retry_selected():
    """Re-queue a stopped or errored item."""
    sel = queue_tree.selection()
    if not sel:
        return
    iid = sel[0]
    for url, data in list(queue_items.items()):
        if data["iid"] == iid:
            status = queue_tree.set(iid, "status")
            if status in ("Stopped", "Error"):
                new_stop = Event()
                data["stop_event"] = new_stop
                queue_update_row(iid, status="queued")
                download_executor.submit(fetch_and_download, url, iid, new_stop)
            break


def clear_done_rows():
    to_remove = []
    for iid in queue_tree.get_children():
        status = queue_tree.set(iid, "status")
        if status in ("Done", "Error", "Stopped"):
            queue_tree.delete(iid)
            for url, data in queue_items.items():
                if data["iid"] == iid:
                    to_remove.append(url)
                    break
    for url in to_remove:
        queue_items.pop(url, None)


# ─────────────────────────────────────────
#  SEARCH  (parallel result enrichment)
# ─────────────────────────────────────────

_search_generation = 0


def do_search(event=None):
    global _search_generation
    q = search_entry.get().strip()
    if not q:
        return

    _search_generation += 1
    gen = _search_generation

    search_btn.config(text="Searching…")
    search_status.config(text="")
    for row in results_tree.get_children():
        results_tree.delete(row)

    Thread(target=_search_worker, args=(q, gen), daemon=True).start()


def _search_worker(query, gen):
    """
    Step 1 – ytsearch10 (single fast request, shows results immediately).
    Step 2 – enrich each result in parallel via search_executor.
    """
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "ignoreerrors": True}) as ydl:
            raw = ydl.extract_info(f'ytsearch10:{query} "topic"', download=False)

        if gen != _search_generation:
            return

        entries = [e for e in raw.get("entries", []) if e]
        root.after(0, lambda e=entries, g=gen: _populate_results_preliminary(e, g))

    except Exception as exc:
        if gen == _search_generation:
            root.after(0, lambda: search_status.config(text=f"Error: {exc}"))
    finally:
        if gen == _search_generation:
            root.after(0, lambda: search_btn.config(text="Search"))


def _populate_results_preliminary(entries, gen):
    if gen != _search_generation:
        return

    results_tree.delete(*results_tree.get_children())

    for e in entries:
        title = e.get("title", "?")
        dur   = fmt_duration(e.get("duration"))
        chan  = e.get("uploader", "—")
        views = fmt_views(e.get("view_count"))
        url   = e.get("webpage_url", "")
        results_tree.insert(
            "", tk.END,
            values=(truncate(title, 50), dur, chan, views, url),
            iid=url   # stable row id for enrichment updates
        )

    search_status.config(text=f"{len(entries)} results")

    # Kick off parallel enrichment
    Thread(target=_enrich_results, args=(entries, gen), daemon=True).start()


def _enrich_results(entries, gen):
    """Fetch full info for each result concurrently; stream updates into the table."""

    def fetch_one(entry):
        url = entry.get("webpage_url", "")
        if not url or gen != _search_generation:
            return None
        try:
            with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
                info = ydl.extract_info(url, download=False)
            return {
                "url"  : url,
                "title": info.get("title", entry.get("title", "?")),
                "dur"  : fmt_duration(info.get("duration")),
                "chan" : info.get("uploader", entry.get("uploader", "—")),
                "views": fmt_views(info.get("view_count")),
            }
        except Exception:
            return None

    futures = {search_executor.submit(fetch_one, e): e for e in entries}

    for future in as_completed(futures):
        if gen != _search_generation:
            break
        result = future.result()
        if result:
            root.after(0, lambda d=result, g=gen: _update_result_row(d, g))


def _update_result_row(data, gen):
    if gen != _search_generation:
        return
    url = data["url"]
    try:
        results_tree.item(url, values=(
            truncate(data["title"], 50),
            data["dur"],
            data["chan"],
            data["views"],
            url,
        ))
    except tk.TclError:
        pass


def get_selected_result_url():
    sel = results_tree.selection()
    if not sel:
        return None, None
    vals = results_tree.item(sel[0])["values"]
    return vals[4], vals[0]


def download_selected():
    url, title = get_selected_result_url()
    if not url:
        return
    notebook.select(0)
    if url not in queue_items:
        iid        = queue_tree.insert(
            "", tk.END,
            values=(truncate(title, 48), "—", "—", "Queued", ""),
            tags=("queued",)
        )
        stop_event = Event()
        queue_items[url] = {"iid": iid, "title": title, "stop_event": stop_event}
        download_executor.submit(fetch_and_download, url, iid, stop_event)


# ─────────────────────────────────────────
#  PREVIEW (VLC)
# ─────────────────────────────────────────

def play_preview(event=None):
    global player, player_media, is_playing
    url, title = get_selected_result_url()
    if not url:
        return

    def _worker():
        global player, player_media, is_playing
        try:
            with yt_dlp.YoutubeDL({"format": "bestaudio/best", "quiet": True}) as ydl:
                info      = ydl.extract_info(url, download=False)
                audio_url = info["url"]
                dur       = info.get("duration", 0)
                t_title   = info.get("title", title)
                artist    = info.get("uploader", "")

            if player:
                player.stop()

            player       = vlc.MediaPlayer(audio_url)
            player_media = {"title": t_title, "artist": artist, "duration": dur}
            player.play()
            is_playing   = True
            root.after(0, lambda: _update_player_bar(t_title, artist, dur))
        except Exception as e:
            root.after(0, lambda: player_title_var.set(f"Error: {e}"))

    Thread(target=_worker, daemon=True).start()
    player_title_var.set(f"Loading: {truncate(title, 40)}…")


def stop_preview():
    global player, is_playing
    if player:
        player.stop()
    is_playing = False
    play_pause_btn.config(text="▶")


def toggle_play_pause():
    global is_playing
    if not player:
        return
    if is_playing:
        player.pause()
        is_playing = False
        play_pause_btn.config(text="▶")
    else:
        player.play()
        is_playing = True
        play_pause_btn.config(text="⏸")


def _update_player_bar(title, artist, duration):
    player_title_var.set(truncate(title, 38))
    player_artist_var.set(truncate(artist, 38))
    play_pause_btn.config(text="⏸")
    dur_label.config(text=fmt_duration(duration))


def poll_player():
    if player and is_playing and not seek_dragging:
        pos = player.get_position()
        if pos >= 0:
            seek_var.set(pos * 1000)
        t = player.get_time()
        if t >= 0:
            elapsed_label.config(text=fmt_duration(t // 1000))
        if str(player.get_state()) == "State.Ended":
            play_pause_btn.config(text="▶")
    root.after(500, poll_player)


def on_seek_press(event):
    global seek_dragging
    seek_dragging = True


def on_seek_release(event):
    global seek_dragging
    seek_dragging = False
    if player:
        player.set_position(seek_var.get() / 1000)


def on_volume_change(val):
    if player:
        player.audio_set_volume(int(float(val)))


# ─────────────────────────────────────────
#  FOLDER
# ─────────────────────────────────────────

def choose_folder():
    global download_path
    folder = filedialog.askdirectory(initialdir=download_path)
    if folder:
        download_path = folder
        folder_label.config(text=truncate(folder, 44))


# ─────────────────────────────────────────
#  STYLE HELPERS
# ─────────────────────────────────────────

def styled_btn(parent, text, command, accent=False, small=False):
    bg    = ACCENT  if accent else BG3
    fg    = "#ffffff" if accent else FG
    hover = ACCENT2 if accent else BORDER

    b = tk.Label(
        parent, text=text,
        bg=bg, fg=fg,
        relief="flat", bd=0,
        padx=12, pady=4 if small else 6,
        font=(FONT, 11 if small else 12),
        cursor="hand2",
    )

    def on_enter(e):    b.config(bg=hover)
    def on_leave(e):    b.config(bg=bg)
    def on_press(e):    b.config(bg=ACCENT2 if accent else BG2); command()
    def on_release(e):  b.config(bg=hover)

    b.bind("<Enter>",           on_enter)
    b.bind("<Leave>",           on_leave)
    b.bind("<ButtonPress-1>",   on_press)
    b.bind("<ButtonRelease-1>", on_release)
    return b


def separator(parent, axis="x", pad=0):
    if axis == "x":
        f = tk.Frame(parent, bg=BORDER, height=1)
        f.pack(fill="x", padx=pad)
    else:
        f = tk.Frame(parent, bg=BORDER, width=1)
        f.pack(fill="y", pady=pad)
    return f


# ─────────────────────────────────────────
#  BUILD GUI
# ─────────────────────────────────────────

root = tk.Tk()
root.title("Audio Downloader Pro")
root.geometry("860x720")
root.minsize(720, 520)
root.configure(bg=BG)

style = ttk.Style()
style.theme_use("clam")

style.configure("TNotebook",
    background=BG, borderwidth=0, tabmargins=0)
style.configure("TNotebook.Tab",
    background=BG2, foreground=FG2,
    padding=[20, 8], font=(FONT, 12), borderwidth=0)
style.map("TNotebook.Tab",
    background=[("selected", BG), ("active", BG3)],
    foreground=[("selected", FG),  ("active", FG)])

for ts in ("Queue.Treeview", "Results.Treeview"):
    style.configure(ts,
        background=BG2, foreground=FG, fieldbackground=BG2,
        rowheight=36, borderwidth=0, relief="flat", font=(FONT, 11))
    style.configure(f"{ts}.Heading",
        background=BG3, foreground=FG2,
        font=(FONT, 10), borderwidth=0, relief="flat", padding=[8, 6])
    style.map(ts,
        background=[("selected", BG3)],
        foreground=[("selected", FG)])

style.configure("Dark.Vertical.TScrollbar",
    background=BG3, troughcolor=BG2,
    borderwidth=0, arrowcolor=FG3, relief="flat")


# ─────────────────────────────────────────
#  TOP BAR
# ─────────────────────────────────────────

topbar = tk.Frame(root, bg=BG, height=52)
topbar.pack(fill="x", side="top")
topbar.pack_propagate(False)

tk.Label(topbar, text="🎧", font=(FONT, 20), bg=BG, fg=FG).pack(
    side="left", padx=(16, 6), pady=8)
tk.Label(topbar, text="Audio Downloader Pro",
         font=(FONT, 15, "bold"), bg=BG, fg=FG).pack(side="left", pady=8)

ytdlp_ver_var = tk.StringVar(value=f"yt-dlp {get_ytdlp_version()}")
tk.Label(topbar, textvariable=ytdlp_ver_var,
         font=(FONT, 10), bg=BG, fg=FG3).pack(side="right", padx=(0, 6), pady=8)

update_notif_var = tk.StringVar(value="")
update_notif = tk.Label(topbar, textvariable=update_notif_var,
                        font=(FONT, 10), bg=BG, fg=WARNING, cursor="hand2")
update_notif.pack(side="right", padx=(0, 4), pady=8)
update_notif.bind("<ButtonPress-1>", lambda e: open_update_dialog())

styled_btn(topbar, "⟳ yt-dlp", open_update_dialog, small=True).pack(
    side="right", padx=(0, 10), pady=8)

def _silent_check(status, info):
    if status == "available":
        update_notif_var.set(f"↑ {info} available")
        ytdlp_ver_var.set(f"yt-dlp {get_ytdlp_version()}")

check_ytdlp_update(_silent_check)

separator(root, "x")

notebook = ttk.Notebook(root, style="TNotebook")
notebook.pack(fill="both", expand=True)


# ══════════════════════════════════════════
#  TAB 1 — QUEUE
# ══════════════════════════════════════════

tab_queue = tk.Frame(notebook, bg=BG)
notebook.add(tab_queue, text="  Queue  ")

input_bar = tk.Frame(tab_queue, bg=BG, pady=10)
input_bar.pack(fill="x", padx=16)

url_input = tk.Entry(
    input_bar, bg=BG2, fg=FG, insertbackground=FG,
    relief="flat", bd=0, font=(FONT, 12),
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT
)
url_input.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
url_input.insert(0, "Paste YouTube URL or playlist…")
url_input.bind("<FocusIn>", lambda e: (
    url_input.get() == "Paste YouTube URL or playlist…"
    and url_input.delete(0, tk.END)
))
url_input.bind("<Return>", lambda e: add_urls_from_box())

styled_btn(input_bar, "＋ Add", add_urls_from_box, accent=True).pack(side="left")

queue_frame = tk.Frame(tab_queue, bg=BG)
queue_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

q_cols = ("title", "duration", "channel", "status", "note")
queue_tree = ttk.Treeview(
    queue_frame, columns=q_cols, show="headings",
    style="Queue.Treeview", selectmode="browse"
)

for col, label, w, anchor in [
    ("title",    "Title",    360, "w"),
    ("duration", "Duration",  70, "center"),
    ("channel",  "Channel",  155, "w"),
    ("status",   "Status",    90, "center"),
    ("note",     "Info",     120, "w"),
]:
    queue_tree.heading(col, text=label, anchor=anchor)
    queue_tree.column(col, width=w, anchor=anchor, stretch=(col == "title"))

q_scroll = ttk.Scrollbar(queue_frame, orient="vertical",
                          command=queue_tree.yview,
                          style="Dark.Vertical.TScrollbar")
queue_tree.configure(yscrollcommand=q_scroll.set)
queue_tree.pack(side="left", fill="both", expand=True)
q_scroll.pack(side="right", fill="y")

# ── Right-click context menu ──────────────
queue_ctx = tk.Menu(root, tearoff=0,
    bg=BG3, fg=FG, activebackground=ACCENT, activeforeground="#fff",
    relief="flat", bd=1)
queue_ctx.add_command(label="⏹  Stop download", command=stop_selected_download)
queue_ctx.add_command(label="↩  Retry",          command=retry_selected)
queue_ctx.add_separator()
queue_ctx.add_command(label="🗑  Remove row",     command=lambda: [
    queue_tree.delete(iid) for iid in queue_tree.selection()
])

def show_queue_ctx(event):
    row = queue_tree.identify_row(event.y)
    if row:
        queue_tree.selection_set(row)
        queue_ctx.tk_popup(event.x_root, event.y_root)

queue_tree.bind("<Button-2>", show_queue_ctx)
queue_tree.bind("<Button-3>", show_queue_ctx)
queue_tree.bind("<Delete>",   lambda e: stop_selected_download())
queue_tree.bind("<BackSpace>", lambda e: stop_selected_download())

# Footer
separator(tab_queue, "x")
folder_row = tk.Frame(tab_queue, bg=BG, pady=6)
folder_row.pack(fill="x", padx=16)

tk.Label(folder_row, text="📁", font=(FONT, 13), bg=BG, fg=FG2).pack(side="left")
folder_label = tk.Label(
    folder_row, text=truncate(download_path, 44),
    font=(FONT, 11), bg=BG, fg=FG2, cursor="hand2"
)
folder_label.pack(side="left", padx=(4, 0))
folder_label.bind("<Button-1>", lambda e: choose_folder())

styled_btn(folder_row, "Change",     choose_folder,          small=True).pack(side="right")
styled_btn(folder_row, "Clear done", clear_done_rows,        small=True).pack(side="right", padx=(0, 6))
styled_btn(folder_row, "⏹ Stop",    stop_selected_download, small=True).pack(side="right", padx=(0, 6))
styled_btn(folder_row, "↩ Retry",   retry_selected,         small=True).pack(side="right", padx=(0, 6))


# ══════════════════════════════════════════
#  TAB 2 — SEARCH
# ══════════════════════════════════════════

tab_search = tk.Frame(notebook, bg=BG)
notebook.add(tab_search, text="  Search  ")

sbar = tk.Frame(tab_search, bg=BG, pady=10)
sbar.pack(fill="x", padx=16)

search_entry = tk.Entry(
    sbar, bg=BG2, fg=FG, insertbackground=FG,
    relief="flat", bd=0, font=(FONT, 12),
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT
)
search_entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
search_entry.bind("<Return>", do_search)

search_btn = styled_btn(sbar, "Search", do_search, accent=True)
search_btn.pack(side="left")

search_status = tk.Label(sbar, text="", font=(FONT, 11), bg=BG, fg=FG3)
search_status.pack(side="left", padx=(10, 0))

res_frame = tk.Frame(tab_search, bg=BG)
res_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

r_cols = ("title", "duration", "channel", "views", "url")
results_tree = ttk.Treeview(
    res_frame, columns=r_cols, show="headings",
    style="Results.Treeview", selectmode="browse"
)

for col, label, w, anchor in [
    ("title",    "Title",    360, "w"),
    ("duration", "Duration",  70, "center"),
    ("channel",  "Channel",  160, "w"),
    ("views",    "Views",    100, "w"),
    ("url",      "",           0, "w"),
]:
    results_tree.heading(col, text=label, anchor=anchor)
    results_tree.column(
        col, width=w, anchor=anchor,
        stretch=(col == "title"),
        minwidth=0 if col == "url" else 40
    )

r_scroll = ttk.Scrollbar(res_frame, orient="vertical",
                          command=results_tree.yview,
                          style="Dark.Vertical.TScrollbar")
results_tree.configure(yscrollcommand=r_scroll.set)
results_tree.pack(side="left", fill="both", expand=True)
r_scroll.pack(side="right", fill="y")

results_tree.bind("<Double-1>", play_preview)

action_row = tk.Frame(tab_search, bg=BG, pady=8)
action_row.pack(fill="x", padx=16)

styled_btn(action_row, "▶  Preview",           play_preview,     ).pack(side="left")
styled_btn(action_row, "⏹  Stop",              stop_preview, small=True).pack(side="left", padx=(6, 0))
styled_btn(action_row, "⬇  Download selected", download_selected, accent=True).pack(side="right")

separator(root, "x")


# ─────────────────────────────────────────
#  PLAYER BAR
# ─────────────────────────────────────────

player_bar = tk.Frame(root, bg=BG2, height=72)
player_bar.pack(fill="x", side="bottom")
player_bar.pack_propagate(False)

info_col = tk.Frame(player_bar, bg=BG2, width=220)
info_col.pack(side="left", fill="y", padx=(14, 0))
info_col.pack_propagate(False)

player_title_var  = tk.StringVar(value="Not playing")
player_artist_var = tk.StringVar(value="")

tk.Label(info_col, textvariable=player_title_var,
         font=(FONT, 12, "bold"), bg=BG2, fg=FG,
         anchor="w", wraplength=200, justify="left").pack(anchor="w", pady=(14, 0))
tk.Label(info_col, textvariable=player_artist_var,
         font=(FONT, 10), bg=BG2, fg=FG3,
         anchor="w").pack(anchor="w")

ctrl_col   = tk.Frame(player_bar, bg=BG2)
ctrl_col.pack(side="left", fill="y", padx=14)
ctrl_inner = tk.Frame(ctrl_col, bg=BG2)
ctrl_inner.pack(expand=True, anchor="center", pady=16)


def icon_btn(parent, text, cmd, size=13):
    b = tk.Label(
        parent, text=text,
        bg=BG2, fg=FG2,
        relief="flat", bd=0, font=(FONT, size), cursor="hand2",
        padx=8, pady=4
    )
    b.bind("<Enter>",         lambda e: b.config(fg=FG,  bg=BG3))
    b.bind("<Leave>",         lambda e: b.config(fg=FG2, bg=BG2))
    b.bind("<ButtonPress-1>", lambda e: cmd())
    return b


icon_btn(ctrl_inner, "⏮", lambda: player and player.set_position(0)).pack(side="left")

play_pause_btn = tk.Label(
    ctrl_inner, text="▶",
    bg=ACCENT, fg="#ffffff",
    relief="flat", bd=0, font=(FONT, 14), cursor="hand2",
    padx=12, pady=4
)
play_pause_btn.bind("<Enter>",         lambda e: play_pause_btn.config(bg=ACCENT2))
play_pause_btn.bind("<Leave>",         lambda e: play_pause_btn.config(bg=ACCENT))
play_pause_btn.bind("<ButtonPress-1>", lambda e: toggle_play_pause())
play_pause_btn.pack(side="left", padx=4)

icon_btn(ctrl_inner, "⏹", stop_preview).pack(side="left")

seek_col = tk.Frame(player_bar, bg=BG2)
seek_col.pack(side="left", fill="both", expand=True, padx=(6, 14))

time_row = tk.Frame(seek_col, bg=BG2)
time_row.pack(fill="x", pady=(12, 0))

elapsed_label = tk.Label(time_row, text="0:00", font=(FONT_MONO, 10), bg=BG2, fg=FG3)
elapsed_label.pack(side="left")

dur_label = tk.Label(time_row, text="0:00", font=(FONT_MONO, 10), bg=BG2, fg=FG3)
dur_label.pack(side="right")

seek_var = tk.DoubleVar(value=0)
seek_bar = ttk.Scale(seek_col, from_=0, to=1000, orient="horizontal", variable=seek_var)
seek_bar.pack(fill="x")
seek_bar.bind("<ButtonPress-1>",   on_seek_press)
seek_bar.bind("<ButtonRelease-1>", on_seek_release)

vol_col = tk.Frame(player_bar, bg=BG2, width=130)
vol_col.pack(side="right", fill="y", padx=(0, 14))
vol_col.pack_propagate(False)
vol_inner = tk.Frame(vol_col, bg=BG2)
vol_inner.pack(expand=True, anchor="center")

tk.Label(vol_inner, text="🔊", font=(FONT, 12), bg=BG2, fg=FG3).pack(side="left", padx=(0, 4))
ttk.Scale(vol_inner, from_=0, to=100, orient="horizontal",
          value=80, command=on_volume_change).pack(side="left")

style.configure("TScale",
    background=BG2, troughcolor=BG3,
    sliderthickness=12, sliderrelief="flat", borderwidth=0)


# ─────────────────────────────────────────
#  SHUTDOWN
# ─────────────────────────────────────────

def on_close():
    for data in queue_items.values():
        data["stop_event"].set()
    download_executor.shutdown(wait=False)
    search_executor.shutdown(wait=False)
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)

# ─────────────────────────────────────────
#  START
# ─────────────────────────────────────────

root.after(500, poll_player)
root.mainloop()
