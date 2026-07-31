#!/usr/bin/env python3
"""
Flacarr - Streamlit web app
Encode FLAC (and lossless WAV) to level 8 + ReplayGain
Designed to run on Unraid (or any server) on port 10069

Features:
- Full Process: Encode → Gain pipeline
- Encode FLAC to level 8 (in-place); convert lossless WAV → FLAC level 8
- Skip files already marked as level 8
- ReplayGain via rsgain (album + track, tag-only, all supported formats)
- Dry-run modes
- Log download + rolling history
- Dark theme
"""

import os
import subprocess
import tempfile
import shutil
import wave
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

st.markdown("""
<style>
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

    .stApp, [data-testid="stAppViewContainer"] {
        background-color: #0e1117 !important;
        color: #fafafa !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #161b22;
        border-right: 1px solid #30363d;
    }
    h1, h2, h3, h4 {
        color: #58a6ff !important;
    }
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
    .stTabs [role="tablist"] button[aria-selected="true"] {
        color: #3fb950 !important;
        border-bottom: 2px solid #3fb950 !important;
        box-shadow: none !important;
    }
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
    }
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
    .stSuccess, .stInfo, .stWarning, .stError {
        border-radius: 8px;
    }
    .stCodeBlock {
        background-color: #161b22 !important;
        border: 1px solid #30363d;
        border-radius: 8px;
    }
    .stDataFrame {
        border: 1px solid #30363d;
        border-radius: 8px;
    }
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
# Session state
# -------------------------------------------------
HISTORY_LIMIT = 300

if "encode_logs" not in st.session_state:
    st.session_state.encode_logs = []
if "encode_history" not in st.session_state:
    st.session_state.encode_history = []
if "gain_history" not in st.session_state:
    st.session_state.gain_history = []
if "full_history" not in st.session_state:
    st.session_state.full_history = []
if "lrc_history" not in st.session_state:
    st.session_state.lrc_history = []
if "empty_history" not in st.session_state:
    st.session_state.empty_history = []
if "empty_scan_results" not in st.session_state:
    st.session_state.empty_scan_results = []  # list of (path_str, files)


def append_history(history_key: str, entries: list[str]) -> None:
    if not entries:
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamped = [f"[{stamp}] {line}" for line in entries]
    combined = stamped + st.session_state[history_key]
    st.session_state[history_key] = combined[:HISTORY_LIMIT]


# -------------------------------------------------
# Helpers
# -------------------------------------------------

def get_tag(audio, key, default=""):
    value = audio.get(key)
    if value:
        return str(value[0]).strip()
    return default


def is_already_level8(file_path: Path) -> bool:
    try:
        audio = FLAC(file_path)
        return get_tag(audio, "flacarr_level") == "8"
    except Exception:
        return False


def strip_id3_tags(file_path: Path) -> None:
    try:
        from mutagen.id3 import ID3
        id3 = ID3(file_path)
        id3.delete(file_path)
    except Exception:
        pass


def flac_error_message(stderr: str) -> str:
    if not stderr:
        return "Unknown flac error"
    lines = [
        ln.strip() for ln in stderr.splitlines()
        if ln.strip().startswith("ERROR") or "has an ID3" in ln
    ]
    if lines:
        return " | ".join(lines)
    for ln in reversed(stderr.splitlines()):
        if ln.strip() and "Copyright" not in ln and "warranty" not in ln.lower():
            return ln.strip()[:300]
    return "flac failed"


def convert_to_level8(file_path: Path) -> tuple[bool, str]:
    """Re-encode a FLAC to compression level 8 in-place."""
    try:
        saved_tags = {}
        saved_pictures = []
        try:
            original = FLAC(file_path)
            for key in original.keys():
                saved_tags[key] = list(original[key])
            saved_pictures = list(original.pictures)
        except Exception:
            pass

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


def is_lossless_wav(file_path: Path) -> bool:
    """
    True if the file is a standard uncompressed PCM WAV (lossless).
    Python's wave module only opens uncompressed WAV; compressed/weird
    containers raise wave.Error.
    """
    try:
        with wave.open(str(file_path), "rb") as w:
            # Basic sanity: at least one channel, positive rate/frames
            if w.getnchannels() < 1 or w.getframerate() < 1:
                return False
            return True
    except Exception:
        return False


def convert_wav_to_flac(file_path: Path, delete_wav: bool = True) -> tuple[bool, str]:
    """
    Encode a lossless WAV to FLAC level 8.
    Writes <name>.flac next to the WAV; optionally removes the WAV on success.
    """
    try:
        if not is_lossless_wav(file_path):
            return False, "not a standard lossless PCM WAV (skipped)"

        flac_path = file_path.with_suffix(".flac")
        if flac_path.exists():
            return False, f"target already exists: {flac_path.name}"

        cmd = [
            "flac",
            "--compression-level-8",
            "--best",
            "--force",
            "--no-padding",
            "--silent",
            "-o", str(flac_path),
            str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            flac_path.unlink(missing_ok=True)
            return False, flac_error_message(result.stderr)

        try:
            audio = FLAC(flac_path)
            audio["flacarr_level"] = ["8"]
            audio.save()
        except Exception:
            pass

        if delete_wav:
            try:
                file_path.unlink()
            except Exception as e:
                return True, f"OK (WAV left in place: {e})"

        return True, "OK (WAV → FLAC)"
    except Exception as e:
        return False, str(e)


GAIN_EXTENSIONS = {
    ".flac", ".mp3", ".ogg", ".oga", ".opus", ".wv", ".m4a", ".aac", ".wma"
}

# Audio extensions that can "own" a sidecar .lrc (same stem, same folder)
LRC_AUDIO_EXTENSIONS = {
    ".flac", ".mp3", ".ogg", ".oga", ".opus", ".wv", ".m4a", ".aac", ".wma",
    ".wav", ".aiff", ".aif", ".ape", ".alac"
}


def find_orphan_lrcs(folder: Path) -> list[Path]:
    """
    Find .lrc files with no matching audio file in the same directory.
    Match is by stem (exact, then case-insensitive).
    Lidarr renames that change punctuation leave true orphans.
    """
    orphans: list[Path] = []
    for lrc in folder.rglob("*.lrc"):
        if not lrc.is_file():
            continue
        parent = lrc.parent
        stem = lrc.stem
        matched = False

        # Exact stem + known audio extension
        for ext in LRC_AUDIO_EXTENSIONS:
            if (parent / f"{stem}{ext}").is_file():
                matched = True
                break

        # Case-insensitive stem match in the same folder
        if not matched:
            stem_lower = stem.lower()
            try:
                for audio in parent.iterdir():
                    if (
                        audio.is_file()
                        and audio.suffix.lower() in LRC_AUDIO_EXTENSIONS
                        and audio.stem.lower() == stem_lower
                    ):
                        matched = True
                        break
            except Exception:
                pass

        if not matched:
            orphans.append(lrc)

    return sorted(orphans)


def subtree_has_audio(dir_path: Path) -> bool:
    """True if any audio file exists under dir_path (recursive)."""
    try:
        for p in dir_path.rglob("*"):
            if p.is_file() and p.suffix.lower() in LRC_AUDIO_EXTENSIONS:
                return True
    except Exception:
        pass
    return False


def list_subtree_files(dir_path: Path, limit: int = 40) -> list[str]:
    """Relative file paths under dir_path (for display)."""
    files: list[str] = []
    try:
        for p in sorted(dir_path.rglob("*")):
            if p.is_file():
                try:
                    files.append(str(p.relative_to(dir_path)))
                except ValueError:
                    files.append(p.name)
                if len(files) >= limit:
                    files.append("…")
                    break
    except Exception:
        pass
    return files


def find_silent_album_folders(scope: Path, library_root: Path) -> list[tuple[Path, list[str]]]:
    """
    Find Lidarr-style album folders with no audio in their subtree.
    - Library root scope → Artist/Album
    - Artist scope → each album under that artist
    - Album scope → that folder only (if silent)
    """
    results: list[tuple[Path, list[str]]] = []

    def consider(album_path: Path) -> None:
        if not album_path.is_dir():
            return
        if album_path.name.startswith("."):
            return
        if subtree_has_audio(album_path):
            return
        results.append((album_path, list_subtree_files(album_path)))

    try:
        rel = scope.resolve().relative_to(library_root.resolve())
        depth = 0 if str(rel) == "." else len(rel.parts)
    except Exception:
        depth = 0

    try:
        if depth == 0:
            for artist in sorted(scope.iterdir()):
                if not artist.is_dir() or artist.name.startswith("."):
                    continue
                for album in sorted(artist.iterdir()):
                    consider(album)
        elif depth == 1:
            for album in sorted(scope.iterdir()):
                consider(album)
        else:
            consider(scope)
    except Exception:
        pass

    return results


def run_rsgain(target: Path, skip_existing: bool, dry_run: bool) -> tuple[int, str]:
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


def collect_encode_targets(folder: Path) -> list[Path]:
    """FLAC files + lossless-looking WAV files under folder."""
    files = list(folder.rglob("*.flac"))
    files += list(folder.rglob("*.wav"))
    files += list(folder.rglob("*.WAV"))
    # de-dupe while preserving order
    seen = set()
    out = []
    for f in files:
        key = str(f.resolve())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


# -------------------------------------------------
# Sidebar – path / scope only
# -------------------------------------------------
with st.sidebar:
    st.header("Library Path")

    root_input = st.text_input(
        "Library root",
        value="/mnt/user/Media/Music",
        help="Base music library path (must be accessible inside the container)"
    )
    root = Path(root_input) if root_input else None

    artists = []
    if root and root.exists() and root.is_dir():
        try:
            artists = sorted(
                [p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
            )
        except Exception:
            artists = []

    st.subheader("Scope")
    scope_mode = st.radio(
        "Process",
        options=["Entire library", "One artist", "One album"],
        index=0,
        help="Limit Encode / Gain / Full Process to a smaller part of the library"
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
                albums = []
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

    if folder and folder.exists() and folder.is_dir():
        st.success(f"Target: `{scope_label or folder.name}`")
        flac_count = len(list(folder.rglob("*.flac")))
        wav_count = len(list(folder.rglob("*.wav"))) + len(list(folder.rglob("*.WAV")))
        st.info(f"**{flac_count}** FLAC • **{wav_count}** WAV in scope")
    elif folder:
        st.error("Path does not exist or is not accessible")
        folder = None
    elif root:
        st.warning("Choose a scope above")
    else:
        st.warning("Enter a valid library root")


# -------------------------------------------------
# Tabs
# -------------------------------------------------
(
    tab_full, tab_encode, tab_gain, tab_lrc, tab_empty,
    tab_enc_hist, tab_gain_hist, tab_full_hist, tab_lrc_hist, tab_empty_hist
) = st.tabs([
    "Full Process",
    "Encode (Level 8)",
    "Gain",
    "LRC Cleanup",
    "Empty Folders",
    "Encode History",
    "Gain History",
    "Full History",
    "LRC History",
    "Empty History",
])


# ========== FULL PROCESS ==========
with tab_full:
    st.subheader("Full Process — Encode → Gain")
    st.markdown("""
    Runs the post-rip pipeline on the selected scope:

    1. **Encode** — FLAC → level 8; lossless WAV → FLAC level 8
    2. **Gain** — album + track ReplayGain tags via `rsgain` (tag-only)

    Naming / multi-disc folders are handled by **Lidarr**.

    **Use Dry Run the first time. When Dry Run is off, both steps modify files.**
    """)

    full_dry = st.checkbox(
        "Dry Run (preview only — no encodes or tags written)",
        value=True,
        key="full_dry_run"
    )
    full_skip_level8 = st.checkbox(
        "Skip files already marked as level 8",
        value=True,
        key="full_skip_level8",
        help="Flacarr writes flacarr_level=8 after a successful encode"
    )
    full_gain_skip = st.checkbox(
        "Skip files that already have ReplayGain tags",
        value=True,
        key="full_gain_skip"
    )
    full_delete_wav = st.checkbox(
        "Delete WAV after successful FLAC conversion",
        value=True,
        key="full_delete_wav"
    )

    if not full_dry:
        st.warning("⚠️ Dry Run is **off**. This will re-encode audio and write ReplayGain tags.")

    if st.button("Start Full Process", type="primary", key="btn_full"):
        if not folder or not folder.exists():
            st.error("Please choose a valid scope in the sidebar.")
        else:
            combined_logs = []
            combined_logs.append(f"=== FULL PROCESS  |  scope: {scope_label or folder}  |  dry={full_dry} ===")
            combined_logs.append("")

            # 1. ENCODE
            combined_logs.append("--- 1. ENCODE (Level 8) ---")
            files = collect_encode_targets(folder)
            total = len(files)
            enc_success = enc_skipped = enc_failed = 0

            if total == 0:
                combined_logs.append("No FLAC/WAV files found — skipping Encode.")
            else:
                log_placeholder = st.empty()
                with st.spinner(f"{'Previewing' if full_dry else 'Encoding'} {total} files…"):
                    for f in files:
                        rel = f.relative_to(folder)
                        suffix = f.suffix.lower()

                        if suffix == ".flac" and full_skip_level8 and is_already_level8(f):
                            combined_logs.append(f"↷ SKIPPED (already level 8): {rel}")
                            enc_skipped += 1
                        elif full_dry:
                            if suffix == ".flac":
                                combined_logs.append(f"DRY  would encode FLAC: {rel}")
                            else:
                                lossless = is_lossless_wav(f)
                                if lossless:
                                    combined_logs.append(f"DRY  would convert WAV→FLAC: {rel}")
                                else:
                                    combined_logs.append(f"DRY  skip WAV (not lossless PCM): {rel}")
                                    enc_skipped += 1
                                    log_placeholder.code("\n".join(combined_logs[-25:]), language=None)
                                    continue
                            enc_success += 1
                        else:
                            if suffix == ".flac":
                                ok, msg = convert_to_level8(f)
                            else:
                                ok, msg = convert_wav_to_flac(f, delete_wav=full_delete_wav)
                            if ok:
                                enc_success += 1
                                combined_logs.append(f"✓ {rel}" + (f" — {msg}" if msg != "OK" else ""))
                            else:
                                enc_failed += 1
                                combined_logs.append(f"✗ {rel} → {msg}")

                        log_placeholder.code("\n".join(combined_logs[-25:]), language=None)

            combined_logs.append(
                f"Encode summary: {enc_success} ok • {enc_skipped} skipped • {enc_failed} failed (total {total})"
            )
            combined_logs.append("")

            # 2. GAIN
            combined_logs.append("--- 2. GAIN (ReplayGain) ---")
            with st.spinner("Running ReplayGain…"):
                code, output = run_rsgain(folder, skip_existing=full_gain_skip, dry_run=full_dry)
            gain_lines = output.splitlines() if output else []
            if gain_lines:
                combined_logs.extend(gain_lines[:400])
                if len(gain_lines) > 400:
                    combined_logs.append(f"... ({len(gain_lines) - 400} more lines truncated)")
            else:
                combined_logs.append("(no rsgain output)")
            combined_logs.append(f"Gain exit code: {code}")
            combined_logs.append("")
            combined_logs.append("=== FULL PROCESS COMPLETE ===")

            append_history("encode_history", [
                f"(full) {ln}" for ln in combined_logs
                if ln.startswith(("✓", "✗", "↷", "DRY")) or "Encode summary" in ln
            ])
            append_history("gain_history", [f"(full) {ln}" for ln in gain_lines] if gain_lines else ["(full) no gain output"])
            append_history("full_history", combined_logs)

            if full_dry:
                st.success("Dry Run finished — nothing was modified.")
            else:
                st.success(
                    f"Full Process finished — Encode: {enc_success} ok / {enc_skipped} skip / {enc_failed} fail  •  "
                    f"Gain exit {code}"
                )
            st.code("\n".join(combined_logs), language=None)
            make_log_download(combined_logs, "full_process")


# ========== ENCODE ==========
with tab_encode:
    st.subheader("Convert to FLAC compression level 8")
    st.markdown("""
    - **FLAC** → re-encode to level 8 **in-place** (lossless; bit depth preserved)
    - **WAV** → if standard lossless PCM, convert to FLAC level 8
    - MP3 and other lossy formats are ignored
    - Strips non-standard ID3v2 tags from FLAC before encoding

    **Use Dry Run the first time. When Dry Run is off, files will be modified.**
    """)

    enc_dry = st.checkbox(
        "Dry Run (preview only — no files modified)",
        value=True,
        key="enc_dry_run"
    )
    skip_level8 = st.checkbox(
        "Skip files already marked as level 8",
        value=True,
        key="enc_skip_level8",
        help="Flacarr writes flacarr_level=8 after a successful encode"
    )
    delete_wav = st.checkbox(
        "Delete WAV after successful FLAC conversion",
        value=True,
        key="enc_delete_wav"
    )

    if not enc_dry:
        st.warning("⚠️ Dry Run is **off**. This will re-encode FLAC and/or convert WAV files.")

    if st.button("Start Encoding", type="primary", key="btn_encode"):
        if not folder or not folder.exists():
            st.error("Please choose a valid scope in the sidebar.")
        else:
            files = collect_encode_targets(folder)
            total = len(files)

            if total == 0:
                st.warning("No FLAC or WAV files found.")
            else:
                log_placeholder = st.empty()
                logs = []
                success = skipped = failed = 0

                with st.spinner(f"{'Previewing' if enc_dry else 'Encoding'} {total} files…"):
                    for f in files:
                        rel = f.relative_to(folder)
                        suffix = f.suffix.lower()

                        if suffix == ".flac" and skip_level8 and is_already_level8(f):
                            logs.append(f"↷ SKIPPED (already level 8): {rel}")
                            skipped += 1
                        elif enc_dry:
                            if suffix == ".flac":
                                logs.append(f"DRY  would encode FLAC: {rel}")
                                success += 1
                            else:
                                if is_lossless_wav(f):
                                    logs.append(f"DRY  would convert WAV→FLAC: {rel}")
                                    success += 1
                                else:
                                    logs.append(f"↷ SKIPPED WAV (not lossless PCM): {rel}")
                                    skipped += 1
                        elif suffix == ".flac":
                            ok, msg = convert_to_level8(f)
                            if ok:
                                success += 1
                                logs.append(f"✓ {rel}")
                            else:
                                failed += 1
                                logs.append(f"✗ {rel} → {msg}")
                        else:
                            ok, msg = convert_wav_to_flac(f, delete_wav=delete_wav)
                            if ok:
                                success += 1
                                logs.append(f"✓ {rel} — {msg}")
                            else:
                                if "not a standard lossless" in msg or "already exists" in msg:
                                    skipped += 1
                                    logs.append(f"↷ SKIPPED: {rel} → {msg}")
                                else:
                                    failed += 1
                                    logs.append(f"✗ {rel} → {msg}")

                        log_placeholder.code("\n".join(logs[-30:]), language=None)

                st.session_state.encode_logs = logs
                append_history("encode_history", logs)
                if enc_dry:
                    st.success(
                        f"Dry Run finished — **{success}** would convert • **{skipped}** skipped • "
                        f"**{failed}** failed (total {total}). Nothing was modified."
                    )
                else:
                    st.success(
                        f"Done — **{success}** converted • **{skipped}** skipped • **{failed}** failed "
                        f"(total {total})"
                    )
                make_log_download(logs, "encode")


# ========== GAIN ==========
with tab_gain:
    st.subheader("ReplayGain (tag-only)")
    st.markdown("""
    - **Tag-only** — audio stream is not modified
    - **Album + track** gain for every supported file
    - Formats: FLAC, MP3, Ogg, Opus, WavPack, M4A/AAC, WMA

    **Use Dry Run the first time. When Dry Run is off, ReplayGain tags will be written.**
    """)

    gain_skip = st.checkbox(
        "Skip files that already have ReplayGain tags",
        value=True,
        key="gain_skip_existing"
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
            prefix = "(dry-run) " if gain_dry else ""
            append_history("gain_history", [prefix + ln for ln in lines] if lines else [prefix + "No output"])

            if code == 0:
                st.success("Gain scan finished." + (" (dry run — nothing written)" if gain_dry else " Tags written."))
            else:
                st.error(f"rsgain exited with code {code}")

            if lines:
                st.code("\n".join(lines[-200:]), language=None)
                make_log_download(lines, "gain")


# ========== LRC CLEANUP ==========
with tab_lrc:
    st.subheader("Orphan .lrc cleanup")
    st.markdown("""
    Finds **`.lrc`** files that no longer have a matching audio file in the same folder
    (same base name). Typical after **Lidarr** renames change punctuation or case.

    Matching: exact stem, then case-insensitive stem, against common audio extensions.

    **Use Dry Run the first time. When Dry Run is off, orphan `.lrc` files will be deleted.**
    """)

    lrc_dry = st.checkbox(
        "Dry Run (list only — do not delete)",
        value=True,
        key="lrc_dry_run"
    )

    if not lrc_dry:
        st.warning("⚠️ Dry Run is **off**. Orphan `.lrc` files will be **permanently deleted**.")

    if st.button("Scan for Orphan LRCs", type="primary", key="btn_lrc"):
        if not folder or not folder.exists():
            st.error("Please choose a valid scope in the sidebar.")
        else:
            with st.spinner("Scanning for orphan .lrc files…"):
                orphans = find_orphan_lrcs(folder)

            logs: list[str] = []
            logs.append(f"=== LRC CLEANUP  |  scope: {scope_label or folder}  |  dry={lrc_dry} ===")
            logs.append(f"Found **{len(orphans)}** orphan .lrc file(s)")
            logs.append("")

            if not orphans:
                logs.append("Nothing to clean up.")
                append_history("lrc_history", logs)
                st.success("No orphan .lrc files found.")
                st.code("\n".join(logs), language=None)
                make_log_download(logs, "lrc_cleanup")
            else:
                deleted = failed = 0
                log_placeholder = st.empty()

                if lrc_dry:
                    for p in orphans:
                        try:
                            rel = p.relative_to(folder)
                        except ValueError:
                            rel = p
                        logs.append(f"DRY  would delete: {rel}")
                    logs.append("")
                    logs.append(f"Dry Run summary: {len(orphans)} would be deleted. Nothing was modified.")
                    append_history("lrc_history", logs)
                    st.success(f"Dry Run — **{len(orphans)}** orphan .lrc file(s) would be deleted.")
                else:
                    for p in orphans:
                        try:
                            rel = p.relative_to(folder)
                        except ValueError:
                            rel = p
                        try:
                            p.unlink()
                            deleted += 1
                            logs.append(f"✓ deleted: {rel}")
                        except Exception as e:
                            failed += 1
                            logs.append(f"✗ {rel} → {e}")
                        log_placeholder.code("\n".join(logs[-40:]), language=None)
                    logs.append("")
                    logs.append(f"Delete summary: {deleted} deleted • {failed} failed • {len(orphans)} total")
                    append_history("lrc_history", logs)
                    st.success(f"Done — **{deleted}** deleted • **{failed}** failed.")

                st.code("\n".join(logs), language=None)
                make_log_download(logs, "lrc_cleanup")


# ========== EMPTY FOLDERS ==========
with tab_empty:
    st.subheader("Album folders with no audio")
    st.markdown("""
    Finds **album folders** under the current scope that contain **no audio files**
    (but may still have `.lrc`, `.jpg`, `.txt`, etc.). Lidarr will not remove those
    because they are not empty.

    Structure expected: `Artist / Album (Year) / …`

    **Use Dry Run the first time. When Dry Run is off, selected folders are deleted recursively.**
    """)

    empty_dry = st.checkbox(
        "Dry Run (list only — do not delete)",
        value=True,
        key="empty_dry_run"
    )

    if not empty_dry:
        st.warning("⚠️ Dry Run is **off**. Selected folders will be **permanently deleted** (including all leftover files).")

    col_a, col_b = st.columns(2)
    with col_a:
        scan_clicked = st.button("Scan for Empty Albums", type="primary", key="btn_empty_scan")
    with col_b:
        clear_scan = st.button("Clear scan results", type="secondary", key="btn_empty_clear")

    if clear_scan:
        st.session_state.empty_scan_results = []
        st.rerun()

    if scan_clicked:
        if not folder or not folder.exists():
            st.error("Please choose a valid scope in the sidebar.")
        elif not root or not root.exists():
            st.error("Library root is required to detect album folder depth.")
        else:
            with st.spinner("Scanning for album folders with no audio…"):
                found = find_silent_album_folders(folder, root)
            # Store as serializable strings
            st.session_state.empty_scan_results = [
                (str(p), files) for p, files in found
            ]
            st.success(f"Found **{len(found)}** album folder(s) with no audio.")

    results = st.session_state.empty_scan_results
    if results:
        st.markdown("---")
        st.write(f"**{len(results)}** folder(s) with no audio:")

        # Build labels for multiselect
        labels = []
        label_to_path = {}
        for path_str, files in results:
            p = Path(path_str)
            try:
                rel = str(p.relative_to(root)) if root else path_str
            except Exception:
                rel = path_str
            n = len([f for f in files if f != "…"])
            extra = "+" if "…" in files else ""
            label = f"{rel}  ({n}{extra} leftover file(s))"
            labels.append(label)
            label_to_path[label] = path_str

        selected = st.multiselect(
            "Select folders to remove",
            options=labels,
            default=[],
            key="empty_multiselect",
            help="Review leftover files below before deleting."
        )

        # Show contents of selected folders
        if selected:
            st.markdown("#### Contents of selected folders")
            path_to_files = {path_str: files for path_str, files in results}
            for label in selected:
                path_str = label_to_path[label]
                files = path_to_files.get(path_str, [])
                st.markdown(f"**`{path_str}`**")
                if files:
                    st.code("\n".join(files), language=None)
                else:
                    st.caption("(completely empty)")

        if st.button("Remove selected folders", type="primary", key="btn_empty_delete"):
            if not selected:
                st.warning("No folders selected.")
            else:
                logs: list[str] = []
                logs.append(
                    f"=== EMPTY FOLDERS  |  scope: {scope_label or folder}  |  dry={empty_dry} ==="
                )
                logs.append(f"Selected: {len(selected)}")
                logs.append("")

                removed = failed = 0
                log_placeholder = st.empty()

                for label in selected:
                    path_str = label_to_path[label]
                    p = Path(path_str)
                    try:
                        rel = str(p.relative_to(root)) if root else path_str
                    except Exception:
                        rel = path_str

                    files = next((f for ps, f in results if ps == path_str), [])

                    if empty_dry:
                        logs.append(f"DRY  would delete folder: {rel}")
                        for f in files[:20]:
                            logs.append(f"       · {f}")
                        if len(files) > 20:
                            logs.append(f"       · … ({len(files) - 20} more)")
                        removed += 1
                    else:
                        try:
                            if p.exists():
                                shutil.rmtree(p)
                            removed += 1
                            logs.append(f"✓ deleted folder: {rel}")
                        except Exception as e:
                            failed += 1
                            logs.append(f"✗ {rel} → {e}")
                    log_placeholder.code("\n".join(logs[-40:]), language=None)

                logs.append("")
                if empty_dry:
                    logs.append(f"Dry Run summary: {removed} folder(s) would be deleted. Nothing was modified.")
                    st.success(f"Dry Run — **{removed}** folder(s) would be deleted.")
                else:
                    logs.append(f"Delete summary: {removed} deleted • {failed} failed")
                    st.success(f"Done — **{removed}** deleted • **{failed}** failed.")
                    # Drop removed paths from scan results
                    gone = {label_to_path[l] for l in selected}
                    st.session_state.empty_scan_results = [
                        (ps, f) for ps, f in results if ps not in gone
                    ]

                append_history("empty_history", logs)
                st.code("\n".join(logs), language=None)
                make_log_download(logs, "empty_folders")
    else:
        st.caption("Click **Scan for Empty Albums** to search the current scope.")


# ========== HISTORIES ==========
with tab_enc_hist:
    st.subheader("Encode History")
    hist = st.session_state.encode_history
    if not hist:
        st.info("No encode history yet.")
    else:
        st.caption(f"Showing last **{len(hist)}** of up to {HISTORY_LIMIT} entries (newest first)")
        st.code("\n".join(hist), language=None)
        make_log_download(hist, "encode_history")
        if st.button("Clear Encode History", type="secondary", key="clear_enc_hist"):
            st.session_state.encode_history = []
            st.rerun()

with tab_gain_hist:
    st.subheader("Gain History")
    hist = st.session_state.gain_history
    if not hist:
        st.info("No gain history yet.")
    else:
        st.caption(f"Showing last **{len(hist)}** of up to {HISTORY_LIMIT} entries (newest first)")
        st.code("\n".join(hist), language=None)
        make_log_download(hist, "gain_history")
        if st.button("Clear Gain History", type="secondary", key="clear_gain_hist"):
            st.session_state.gain_history = []
            st.rerun()

with tab_full_hist:
    st.subheader("Full Process History")
    hist = st.session_state.full_history
    if not hist:
        st.info("No full-process history yet.")
    else:
        st.caption(f"Showing last **{len(hist)}** of up to {HISTORY_LIMIT} entries (newest first)")
        st.code("\n".join(hist), language=None)
        make_log_download(hist, "full_history")
        if st.button("Clear Full History", type="secondary", key="clear_full_hist"):
            st.session_state.full_history = []
            st.rerun()

with tab_lrc_hist:
    st.subheader("LRC Cleanup History")
    hist = st.session_state.lrc_history
    if not hist:
        st.info("No LRC cleanup history yet.")
    else:
        st.caption(f"Showing last **{len(hist)}** of up to {HISTORY_LIMIT} entries (newest first)")
        st.code("\n".join(hist), language=None)
        make_log_download(hist, "lrc_history")
        if st.button("Clear LRC History", type="secondary", key="clear_lrc_hist"):
            st.session_state.lrc_history = []
            st.rerun()

with tab_empty_hist:
    st.subheader("Empty Folders History")
    hist = st.session_state.empty_history
    if not hist:
        st.info("No empty-folder history yet.")
    else:
        st.caption(f"Showing last **{len(hist)}** of up to {HISTORY_LIMIT} entries (newest first)")
        st.code("\n".join(hist), language=None)
        make_log_download(hist, "empty_history")
        if st.button("Clear Empty History", type="secondary", key="clear_empty_hist"):
            st.session_state.empty_history = []
            st.rerun()
