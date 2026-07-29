#!/usr/bin/env python3
"""
Flacarr - Streamlit web app
Encode FLAC to level 8 + conditional rename/organize
Designed to run on Unraid (or any server) on port 10069

Features:
- Encode to FLAC level 8 (in-place, recursive)
- Skip files already marked as level 8
- Conditional rename (no CD folder on single-disc)
- Dry-run for rename
- Log download
- Dark mode / improved styling
"""

import os
import subprocess
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
import streamlit as st

try:
    from mutagen.flac import FLAC
except ImportError:
    st.error("mutagen is not installed. Run:  pip install mutagen")
    st.stop()

# -------------------------------------------------
# Page config + dark styling
# -------------------------------------------------
st.set_page_config(
    page_title="Flacarr",
    page_icon="flacarr.jpg",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom dark theme CSS + hide Streamlit chrome
st.markdown("""
<style>
    /* Hide Streamlit default menu, toolbar, theme picker, decoration, footer */
    #MainMenu {visibility: hidden !important; height: 0 !important;}
    header {visibility: hidden !important; height: 0 !important;}
    footer {visibility: hidden !important; height: 0 !important;}
    [data-testid="stToolbar"] {display: none !important; height: 0 !important;}
    [data-testid="stDecoration"] {display: none !important; height: 0 !important;}
    [data-testid="stStatusWidget"] {display: none !important;}
    [data-testid="stHeader"] {display: none !important; height: 0 !important;}
    [data-testid="stAppToolbar"] {display: none !important; height: 0 !important;}
    [data-testid="baseButton-headerNoPadding"] {display: none !important;}
    .stDeployButton {display: none !important;}
    div[data-testid="stToolbar"] {display: none !important;}

    /* Force dark look even if system prefers light */
    .stApp, [data-testid="stAppViewContainer"] {
        background-color: #0e1117 !important;
        color: #fafafa !important;
    }
    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #161b22;
        border-right: 1px solid #30363d;
    }
    /* Headers */
    h1, h2, h3, h4 {
        color: #58a6ff !important;
    }
    /* Tab highlight → green (cover Streamlit / Baseweb variants) */
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs div[data-baseweb="tab-highlight"],
    [data-baseweb="tab-highlight"] {
        background-color: #3fb950 !important;
        background-image: none !important;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"],
    .stTabs button[aria-selected="true"],
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #3fb950 !important;
        border-bottom-color: #3fb950 !important;
    }
    .stTabs [data-baseweb="tab"]:hover,
    button[data-baseweb="tab"]:hover {
        color: #56d364 !important;
    }
    /* Some Streamlit versions use a red underline via border on the tab list */
    .stTabs [role="tablist"] button[aria-selected="true"] {
        color: #3fb950 !important;
        border-bottom: 2px solid #3fb950 !important;
        box-shadow: none !important;
    }
    /* All buttons base */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
    }
    /* Primary actions (Start Encoding / Start Rename / Start Gain / Confirm) → green + black text */
    .stButton > button[kind="primary"],
    .stButton > button[data-testid="baseButton-primary"],
    button[data-testid="baseButton-primary"] {
        background-color: #3fb950 !important;
        background-image: none !important;
        color: #000000 !important;
        border: 1px solid #3fb950 !important;
    }
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="baseButton-primary"]:hover,
    button[data-testid="baseButton-primary"]:hover {
        background-color: #56d364 !important;
        color: #000000 !important;
        border-color: #56d364 !important;
    }
    /* Secondary buttons (Clear History) → red */
    .stButton > button[kind="secondary"],
    .stButton > button[data-testid="baseButton-secondary"],
    button[data-testid="baseButton-secondary"] {
        background-color: #da3633 !important;
        background-image: none !important;
        color: #ffffff !important;
        border: 1px solid #da3633 !important;
    }
    .stButton > button[kind="secondary"]:hover,
    .stButton > button[data-testid="baseButton-secondary"]:hover,
    button[data-testid="baseButton-secondary"]:hover {
        background-color: #f85149 !important;
        color: #ffffff !important;
        border-color: #f85149 !important;
    }
    /* Success / info boxes */
    .stSuccess, .stInfo, .stWarning, .stError {
        border-radius: 8px;
    }
    /* Code / log blocks */
    .stCodeBlock {
        background-color: #161b22 !important;
        border: 1px solid #30363d;
        border-radius: 8px;
    }
    /* Dataframe */
    .stDataFrame {
        border: 1px solid #30363d;
        border-radius: 8px;
    }
    /* Caption */
    .stCaption {
        color: #8b949e !important;
    }
</style>
""", unsafe_allow_html=True)

# Logo header (left-aligned, compact)
_logo = Path(__file__).parent / "flacarr.jpg"
if _logo.exists():
    st.image(str(_logo), width=220)
else:
    st.title("Flacarr")

# -------------------------------------------------
# Session state for logs / history (last 300 each)
# -------------------------------------------------
HISTORY_LIMIT = 300

if "encode_logs" not in st.session_state:
    st.session_state.encode_logs = []
if "rename_logs" not in st.session_state:
    st.session_state.rename_logs = []
if "encode_history" not in st.session_state:
    st.session_state.encode_history = []
if "rename_history" not in st.session_state:
    st.session_state.rename_history = []
if "gain_history" not in st.session_state:
    st.session_state.gain_history = []


def append_history(history_key: str, entries: list[str]) -> None:
    """Append log lines to a rolling history (max HISTORY_LIMIT)."""
    if not entries:
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamped = [f"[{stamp}] {line}" for line in entries]
    combined = stamped + st.session_state[history_key]
    st.session_state[history_key] = combined[:HISTORY_LIMIT]

# -------------------------------------------------
# Helper functions
# -------------------------------------------------

def get_tag(audio, key, default=""):
    value = audio.get(key)
    if value:
        return str(value[0]).strip()
    return default


def is_already_level8(file_path: Path) -> bool:
    """Check if file was previously processed by Flacarr (custom tag)."""
    try:
        audio = FLAC(file_path)
        comment = get_tag(audio, "flacarr_level")
        return comment == "8"
    except Exception:
        return False


def mark_as_level8(file_path: Path):
    """Write a custom tag so future runs can skip this file."""
    try:
        audio = FLAC(file_path)
        audio["flacarr_level"] = ["8"]
        audio.save()
    except Exception:
        pass  # non-fatal


def build_target_path(file_path: Path, base_folder: Path) -> Path | None:
    """
    Preserve existing Lidarr-style paths.
    Only adjust the CD xx folder level based on discnumber / totaldiscs tags.
    Artist folder, Album (Year) folder, and filename are left completely untouched.
    """
    try:
        audio = FLAC(file_path)
    except Exception:
        return None

    # Only read disc-related tags
    disc = get_tag(audio, "discnumber") or "1"
    disc = disc.split("/")[0].zfill(2)

    totaldiscs = get_tag(audio, "totaldiscs") or "1"
    try:
        totaldiscs_num = int(str(totaldiscs).split("/")[-1])
    except Exception:
        totaldiscs_num = 1

    try:
        rel = file_path.relative_to(base_folder)
    except ValueError:
        return None

    parts = list(rel.parts)

    # Need at least Artist / Album / filename
    if len(parts) < 3:
        return None

    filename = parts[-1]

    # Detect if there is already a CD/Disc folder just above the file
    parent_name = parts[-2]
    has_cd_folder = parent_name.upper().startswith(("CD ", "CD", "DISC ", "DISC"))

    if has_cd_folder:
        # Current: Artist / Album (Year) / CD xx / file
        if len(parts) < 4:
            return None
        artist = parts[0]
        album_folder = parts[1]
    else:
        # Current: Artist / Album (Year) / file
        artist = parts[0]
        album_folder = parts[1]

    # Build target – preserve artist + album folder + filename exactly
    if totaldiscs_num > 1:
        # Multi-disc → ensure CD xx folder exists
        target = base_folder / artist / album_folder / f"CD {disc}" / filename
    else:
        # Single-disc → no CD folder
        target = base_folder / artist / album_folder / filename

    return target


def strip_id3_tags(file_path: Path) -> None:
    """Remove non-standard ID3 tags from a FLAC file (keeps Vorbis comments)."""
    try:
        from mutagen.id3 import ID3
        id3 = ID3(file_path)
        id3.delete(file_path)
    except Exception:
        pass  # no ID3 tags, or already clean


def flac_error_message(stderr: str) -> str:
    """Pull the real error line out of flac's verbose stderr."""
    if not stderr:
        return "Unknown flac error"
    lines = [
        ln.strip() for ln in stderr.splitlines()
        if ln.strip().startswith("ERROR") or "has an ID3" in ln
    ]
    if lines:
        return " | ".join(lines)
    # fallback: last non-empty line
    for ln in reversed(stderr.splitlines()):
        if ln.strip() and "Copyright" not in ln and "warranty" not in ln.lower():
            return ln.strip()[:300]
    return "flac failed"


def convert_to_level8(file_path: Path) -> tuple[bool, str]:
    """Re-encode a single FLAC to compression level 8. Returns (success, message)."""
    try:
        # Save existing Vorbis / picture metadata so we can restore after encode
        saved_tags = {}
        saved_pictures = []
        try:
            original = FLAC(file_path)
            for key in original.keys():
                saved_tags[key] = list(original[key])
            saved_pictures = list(original.pictures)
        except Exception:
            pass

        # flac refuses files that contain ID3v2 tags
        strip_id3_tags(file_path)

        with tempfile.NamedTemporaryFile(suffix=".flac", dir=file_path.parent, delete=False) as tmp:
            temp_path = Path(tmp.name)

        cmd = [
            "flac",
            "--compression-level-8",
            "--best",
            "--force",
            "--no-padding",
            "--silent",
            "-o", str(temp_path),
            str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            temp_path.unlink(missing_ok=True)
            return False, flac_error_message(result.stderr)

        # Restore tags + embedded art on the new file
        try:
            new_audio = FLAC(temp_path)
            for key, value in saved_tags.items():
                new_audio[key] = value
            for pic in saved_pictures:
                new_audio.add_picture(pic)
            new_audio["flacarr_level"] = ["8"]
            new_audio.save()
        except Exception:
            pass

        temp_path.replace(file_path)
        return True, "OK"
    except Exception as e:
        return False, str(e)


# Audio extensions handled by rsgain (tag-only ReplayGain)
GAIN_EXTENSIONS = {
    ".flac", ".mp3", ".ogg", ".oga", ".opus", ".wv", ".m4a", ".aac", ".wma"
}


def run_rsgain(target: Path, skip_existing: bool, dry_run: bool) -> tuple[int, str]:
    """
    ReplayGain via rsgain: album + track, tag-only, all supported formats.
    Returns (returncode, combined output text).
    """
    if dry_run:
        files = [
            p for p in target.rglob("*")
            if p.is_file() and p.suffix.lower() in GAIN_EXTENSIONS
        ]
        lines = [
            f"DRY RUN — would process {len(files)} supported audio file(s) under {target}",
            "Mode: album + track ReplayGain (tag-only)",
            f"Skip existing: {'yes' if skip_existing else 'no'}",
            "Formats: FLAC, MP3, Ogg, Opus, WavPack, M4A/AAC, WMA",
            "",
        ]
        for p in files[:300]:
            try:
                rel = p.relative_to(target)
            except ValueError:
                rel = p
            lines.append(str(rel))
        if len(files) > 300:
            lines.append(f"... and {len(files) - 300} more")
        return 0, "\n".join(lines)

    cmd = ["rsgain", "easy", "-m", str(os.cpu_count() or 2)]
    if skip_existing:
        cmd.append("-S")
    cmd.append(str(target))

    result = subprocess.run(cmd, capture_output=True, text=True)
    out = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
    return result.returncode, out.strip()


def make_log_download(logs: list[str], prefix: str):
    """Create a downloadable log file."""
    if not logs:
        return
    content = "\n".join(logs)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.download_button(
        label="📥 Download Log",
        data=content,
        file_name=f"flacarr_{prefix}_{timestamp}.log",
        mime="text/plain",
        key=f"dl_{prefix}_{timestamp}"
    )


# -------------------------------------------------
# Sidebar – folder selection + options
# -------------------------------------------------
with st.sidebar:
    st.header("Library Path")

    # Root library path
    root_input = st.text_input(
        "Library root",
        value="/mnt/user/Media/Music",
        help="Base music library path (must be accessible inside the container)"
    )
    root = Path(root_input) if root_input else None

    artists = []
    albums = []
    if root and root.exists() and root.is_dir():
        try:
            artists = sorted(
                [p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
            )
        except Exception:
            artists = []

    # Scope: entire library / one artist / one album
    st.subheader("Scope")
    scope_mode = st.radio(
        "Process",
        options=["Entire library", "One artist", "One album"],
        index=0,
        help="Limit Encode and Rename to a smaller part of the library"
    )

    folder = None
    scope_label = ""

    if root and root.exists() and root.is_dir():
        if scope_mode == "Entire library":
            folder = root
            scope_label = "Entire library"

        elif scope_mode == "One artist":
            if artists:
                chosen_artist = st.selectbox("Artist", options=artists)
                if chosen_artist:
                    folder = root / chosen_artist
                    scope_label = chosen_artist
            else:
                st.warning("No artist folders found under the library root")

        elif scope_mode == "One album":
            if artists:
                chosen_artist = st.selectbox("Artist", options=artists, key="album_artist")
                artist_path = root / chosen_artist if chosen_artist else None
                if artist_path and artist_path.exists():
                    try:
                        albums = sorted(
                            [p.name for p in artist_path.iterdir()
                             if p.is_dir() and not p.name.startswith(".")]
                        )
                    except Exception:
                        albums = []
                if albums:
                    chosen_album = st.selectbox("Album", options=albums)
                    if chosen_album:
                        folder = artist_path / chosen_album
                        scope_label = f"{chosen_artist} / {chosen_album}"
                else:
                    st.warning("No album folders found for this artist")
            else:
                st.warning("No artist folders found under the library root")

        # Manual override
        st.markdown("---")
        manual = st.text_input(
            "Or type a relative path",
            value="",
            placeholder="Artist  or  Artist/Album (Year)",
            help="Overrides the selection above if filled in"
        )
        if manual.strip():
            folder = root / manual.strip()
            scope_label = manual.strip()

    # Status
    if folder and folder.exists() and folder.is_dir():
        st.success(f"Target: `{scope_label or folder.name}`")
        flac_count = len(list(folder.rglob("*.flac")))
        st.info(f"**{flac_count}** FLAC files in scope")
    elif folder:
        st.error("Path does not exist or is not accessible")
        folder = None
    elif root:
        st.warning("Choose a scope above")
    else:
        st.warning("Enter a valid library root")

    st.markdown("---")
    st.subheader("Encode Options")
    skip_level8 = st.checkbox(
        "Skip files already marked as level 8",
        value=True,
        help="Flacarr writes a small tag after successful conversion so future runs can skip them."
    )

# -------------------------------------------------
# Main area – Tabs
# -------------------------------------------------
tab_encode, tab_rename, tab_gain, tab_enc_hist, tab_ren_hist, tab_gain_hist = st.tabs([
    "Encode (Level 8)",
    "Rename / Organize",
    "Gain",
    "Encode History",
    "Rename History",
    "Gain History",
])

# ========== ENCODE TAB ==========
with tab_encode:
    st.subheader("Convert FLAC files to compression level 8")
    st.markdown("""
    - Works **in-place** (overwrites original files)
    - Recursive through all subfolders
    - Preserves bit depth (16-bit stays 16-bit, 24-bit stays 24-bit)
    - Only processes `.flac` files – MP3s and other formats are ignored
    - Optionally skips files already processed by Flacarr
    """)

    if st.button("Start Encoding", type="primary", key="btn_encode"):
        if not folder or not folder.exists():
            st.error("Please enter a valid folder path in the sidebar.")
        else:
            files = list(folder.rglob("*.flac"))
            total = len(files)

            if total == 0:
                st.warning("No FLAC files found.")
            else:
                log_placeholder = st.empty()
                logs = []
                success = 0
                skipped = 0
                failed = 0

                with st.spinner(f"Encoding {total} files…"):
                    for i, f in enumerate(files, 1):
                        rel = f.relative_to(folder)

                        if skip_level8 and is_already_level8(f):
                            logs.append(f"↷ SKIPPED (already level 8): {rel}")
                            skipped += 1
                        else:
                            ok, msg = convert_to_level8(f)
                            if ok:
                                success += 1
                                logs.append(f"✓ {rel}")
                            else:
                                failed += 1
                                logs.append(f"✗ {rel} → {msg}")

                        # Keep log view manageable
                        log_placeholder.code("\n".join(logs[-30:]), language=None)

                st.session_state.encode_logs = logs
                append_history("encode_history", logs)
                st.success(
                    f"Done — **{success}** converted • **{skipped}** skipped • **{failed}** failed "
                    f"(total {total})"
                )
                make_log_download(logs, "encode")


# ========== RENAME TAB ==========
with tab_rename:
    st.subheader("Conditional library naming")
    st.markdown("""
    **Rules (preserves your existing Lidarr names):**
    - Keeps Artist folder, Album (Year) folder, and filename exactly as they are
    - Single-disc → removes any unnecessary `CD xx` folder
    - Multi-disc → ensures files sit under `CD 01`, `CD 02`, etc.
    """)

    dry_run = st.checkbox("Dry Run (preview only – no files will be moved)", value=True)

    if st.button("Start Rename", type="primary", key="btn_rename"):
        if not folder or not folder.exists():
            st.error("Please enter a valid folder path in the sidebar.")
        elif not root or not root.exists():
            st.error("Library root is required for rename (needed to preserve Artist/Album structure).")
        else:
            files = list(folder.rglob("*.flac"))
            moves = []
            # Always use library root for path logic so Artist/Album names stay correct
            base = root

            for f in files:
                target = build_target_path(f, base)
                if target and target.resolve() != f.resolve():
                    moves.append((f, target))

            def rel_display(p: Path) -> str:
                try:
                    return str(p.relative_to(base))
                except ValueError:
                    return str(p)

            if not moves:
                st.info("All files already match the desired structure. Nothing to do.")
            else:
                st.write(f"Found **{len(moves)}** files to rename/move:")

                # Preview table
                preview_data = []
                for src, dst in moves[:80]:
                    preview_data.append({
                        "From": rel_display(src),
                        "To": rel_display(dst)
                    })
                st.dataframe(preview_data, use_container_width=True)

                if len(moves) > 80:
                    st.caption(f"... and {len(moves) - 80} more")

                if dry_run:
                    st.warning("Dry Run enabled – no files were moved.")
                    preview_logs = [f"{rel_display(src)}  →  {rel_display(dst)}" for src, dst in moves]
                    st.session_state.rename_logs = preview_logs
                    append_history("rename_history", [f"(dry-run) {line}" for line in preview_logs])
                    make_log_download(preview_logs, "rename_preview")
                else:
                    confirm = st.button("Confirm & Move Files", type="primary", key="btn_confirm_move")
                    if confirm:
                        log_placeholder = st.empty()
                        logs = []
                        success = 0
                        failed = 0

                        with st.spinner(f"Moving {len(moves)} files…"):
                            for i, (src, dst) in enumerate(moves, 1):
                                try:
                                    dst.parent.mkdir(parents=True, exist_ok=True)
                                    if dst.exists():
                                        logs.append(f"↷ SKIPPED (exists): {rel_display(dst)}")
                                        continue
                                    shutil.move(str(src), str(dst))
                                    success += 1
                                    logs.append(f"✓ {rel_display(src)}  →  {rel_display(dst)}")
                                except Exception as e:
                                    failed += 1
                                    logs.append(f"✗ {src.name} → {e}")

                                log_placeholder.code("\n".join(logs[-30:]), language=None)

                        st.session_state.rename_logs = logs
                        append_history("rename_history", logs)
                        st.success(f"Moved **{success}** of **{len(moves)}** files ({failed} failed).")
                        make_log_download(logs, "rename")


# ========== GAIN TAB ==========
with tab_gain:
    st.subheader("ReplayGain (tag-only)")
    st.markdown("""
    - **Tag-only** — audio stream is not modified
    - **Album + track** gain written for every supported file
    - Formats: FLAC, MP3, Ogg, Opus, WavPack, M4A/AAC, WMA (via rsgain)
    - Uses album-folder layout (same as your Lidarr structure)
    """)

    gain_skip = st.checkbox(
        "Skip files that already have ReplayGain tags",
        value=True,
        key="gain_skip_existing",
        help="Uses rsgain -S. If album tags are enabled, an album is rescanned if any track is missing gain tags."
    )
    gain_dry = st.checkbox(
        "Dry Run (list files only — do not write tags)",
        value=True,
        key="gain_dry_run"
    )

    if st.button("Start Gain Scan", type="primary", key="btn_gain"):
        if not folder or not folder.exists():
            st.error("Please choose a valid scope in the sidebar.")
        else:
            with st.spinner("Running ReplayGain scan…"):
                code, output = run_rsgain(folder, skip_existing=gain_skip, dry_run=gain_dry)

            lines = output.splitlines() if output else []
            st.session_state.gain_logs = lines
            prefix = "(dry-run) " if gain_dry else ""
            append_history("gain_history", [prefix + ln for ln in lines] if lines else [prefix + "No output"])

            if code == 0:
                st.success("Gain scan finished." + (" (dry run — nothing written)" if gain_dry else " Tags written."))
            else:
                st.error(f"rsgain exited with code {code}")

            if lines:
                st.code("\n".join(lines[-200:]), language=None)
                make_log_download(lines, "gain")


# ========== ENCODE HISTORY TAB ==========
with tab_enc_hist:
    st.subheader("Encode History")
    hist = st.session_state.encode_history
    if not hist:
        st.info("No encode history yet. Run an encode job to populate this list.")
    else:
        st.caption(f"Showing last **{len(hist)}** of up to {HISTORY_LIMIT} entries (newest first)")
        st.code("\n".join(hist), language=None)
        make_log_download(hist, "encode_history")
        if st.button("Clear Encode History", type="secondary", key="clear_enc_hist"):
            st.session_state.encode_history = []
            st.rerun()


# ========== RENAME HISTORY TAB ==========
with tab_ren_hist:
    st.subheader("Rename / Organize History")
    hist = st.session_state.rename_history
    if not hist:
        st.info("No rename history yet. Run a rename (or dry-run) to populate this list.")
    else:
        st.caption(f"Showing last **{len(hist)}** of up to {HISTORY_LIMIT} entries (newest first)")
        st.code("\n".join(hist), language=None)
        make_log_download(hist, "rename_history")
        if st.button("Clear Rename History", type="secondary", key="clear_ren_hist"):
            st.session_state.rename_history = []
            st.rerun()


# ========== GAIN HISTORY TAB ==========
with tab_gain_hist:
    st.subheader("Gain History")
    hist = st.session_state.gain_history
    if not hist:
        st.info("No gain history yet. Run a gain scan (or dry-run) to populate this list.")
    else:
        st.caption(f"Showing last **{len(hist)}** of up to {HISTORY_LIMIT} entries (newest first)")
        st.code("\n".join(hist), language=None)
        make_log_download(hist, "gain_history")
        if st.button("Clear Gain History", type="secondary", key="clear_gain_hist"):
            st.session_state.gain_history = []
            st.rerun()
