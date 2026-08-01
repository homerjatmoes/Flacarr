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

import io
import os
import subprocess
import tempfile
import shutil
import uuid
import wave
import zipfile
from datetime import datetime
from pathlib import Path
import streamlit as st

try:
    from mutagen.flac import FLAC
    from mutagen import File as MutagenFile
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
        background-color: #0a0a0a !important;
        color: #fafafa !important;
    }
    [data-testid="stAppViewContainer"] > .main,
    .main .block-container {
        background-color: #0a0a0a !important;
    }
    .flacarr-dryrun-note {
        color: #f0c000 !important;
        font-size: 1.2rem !important;
        font-weight: 700 !important;
        line-height: 1.4 !important;
        margin: 0.4rem 0 0.8rem 0 !important;
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
ARTIFACTS_PER_TYPE = 20
LOG_PREVIEW_LINES = 100

if "empty_scan_results" not in st.session_state:
    st.session_state.empty_scan_results = []  # list of (path_str, files)
if "log_artifacts" not in st.session_state:
    # Each: {id, type, job, dry_run, ts, content, lines}
    st.session_state.log_artifacts = []
if "last_results" not in st.session_state:
    # job_key -> {complete, action, errors, dry_run}
    st.session_state.last_results = {}
if "hist_clear_confirm" not in st.session_state:
    st.session_state.hist_clear_confirm = False


def push_log_artifacts(
    job: str,
    dry_run: bool,
    complete: list[str],
    action: list[str],
    errors: list[str],
) -> None:
    """Store downloadable log artifacts (max ARTIFACTS_PER_TYPE per type)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    arts: list[dict] = list(st.session_state.log_artifacts)

    def _add(atype: str, lines: list[str]) -> None:
        if not lines:
            return
        arts.insert(
            0,
            {
                "id": str(uuid.uuid4())[:8],
                "type": atype,
                "job": job,
                "dry_run": dry_run,
                "ts": ts,
                "content": "\n".join(lines),
                "line_count": len(lines),
            },
        )

    if dry_run:
        _add("dry_run", complete)
        _add("action", action)
    else:
        _add("complete", complete)
        _add("action", action)
        _add("errors", errors)

    # Keep newest ARTIFACTS_PER_TYPE per type
    counts: dict[str, int] = {}
    trimmed: list[dict] = []
    for a in arts:
        t = a["type"]
        counts[t] = counts.get(t, 0) + 1
        if counts[t] <= ARTIFACTS_PER_TYPE:
            trimmed.append(a)
    st.session_state.log_artifacts = trimmed


def store_last_results(
    job_key: str,
    complete: list[str],
    action: list[str],
    errors: list[str],
    dry_run: bool,
) -> None:
    st.session_state.last_results[job_key] = {
        "complete": complete,
        "action": action,
        "errors": errors,
        "dry_run": dry_run,
    }


def show_scrollable_log(lines: list[str], max_lines: int = LOG_PREVIEW_LINES) -> None:
    """Show at most max_lines in a fixed-height scrollable code block."""
    if not lines:
        st.caption("No log lines.")
        return
    tail = lines[-max_lines:]
    st.code("\n".join(tail), language=None)
    if len(lines) > max_lines:
        st.caption(
            f"Preview: last **{max_lines}** of **{len(lines)}** lines — "
            "download **Complete log** for the full output."
        )


# -------------------------------------------------
# Helpers
# -------------------------------------------------

def get_tag(audio, key, default=""):
    value = audio.get(key)
    if value:
        return str(value[0]).strip()
    return default


def has_replaygain_tags(file_path: Path) -> bool:
    """True if file already has ReplayGain (or R128) tags."""
    try:
        audio = MutagenFile(file_path, easy=False)
        if audio is None:
            return False
        keys: list[str] = []
        if getattr(audio, "tags", None) is not None:
            keys.extend(str(k) for k in audio.tags.keys())
        # FLAC / Vorbis-style
        try:
            keys.extend(str(k) for k in audio.keys())
        except Exception:
            pass
        blob = " ".join(keys).upper()
        return "REPLAYGAIN" in blob or "R128_" in blob
    except Exception:
        return False


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

# Formats scanned for Description tags
DESC_EXTENSIONS = {
    ".flac", ".mp3", ".ogg", ".oga", ".opus", ".wv", ".m4a", ".aac", ".wma"
}


def _iter_tag_containers(audio):
    """Yield mutable tag mapping objects from a mutagen file."""
    if audio is None:
        return
    # FLAC / VorbisComment style (audio itself is dict-like)
    if hasattr(audio, "keys") and hasattr(audio, "__delitem__"):
        try:
            list(audio.keys())
            yield audio
        except Exception:
            pass
    tags = getattr(audio, "tags", None)
    if tags is not None and tags is not audio:
        if hasattr(tags, "keys") and hasattr(tags, "__delitem__"):
            yield tags


# Free-text tags the user does not use (Vorbis / common names)
TEXT_TAG_NAMES = {"DESCRIPTION", "COMMENT", "NOTES", "NOTE"}


def _is_text_tag_key(key_str: str) -> bool:
    """Match DESCRIPTION / COMMENT / NOTES / NOTE, and ID3 COMM frames."""
    u = key_str.upper()
    if u in TEXT_TAG_NAMES:
        return True
    # ID3 comment frames: COMM, COMM::eng, etc.
    if u == "COMM" or u.startswith("COMM:"):
        return True
    return False


def _tag_value_preview(container, key) -> str:
    try:
        val = container.get(key)
        if isinstance(val, list) and val:
            return str(val[0])[:120]
        if val is not None:
            return str(val)[:120]
    except Exception:
        pass
    return ""


def find_text_tag_entries(file_path: Path) -> list[tuple[str, str]]:
    """
    Return list of (key, value_preview) for Description / Comment / Notes tags.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    try:
        audio = MutagenFile(file_path, easy=False)
        if audio is None:
            return found
        for container in _iter_tag_containers(audio):
            for key in list(container.keys()):
                key_str = str(key)
                if not _is_text_tag_key(key_str):
                    continue
                if key_str in seen:
                    continue
                seen.add(key_str)
                found.append((key_str, _tag_value_preview(container, key)))
    except Exception:
        pass
    return found


def remove_text_tags(file_path: Path) -> tuple[bool, str, list[str]]:
    """
    Remove Description / Comment / Notes tags (tag-only; audio stream untouched).
    Returns (ok, message, list of removed keys).
    """
    try:
        audio = MutagenFile(file_path, easy=False)
        if audio is None:
            return False, "unsupported or unreadable", []

        removed: list[str] = []
        for container in _iter_tag_containers(audio):
            for key in list(container.keys()):
                key_str = str(key)
                if _is_text_tag_key(key_str):
                    try:
                        del container[key]
                        removed.append(key_str)
                    except Exception:
                        pass

        if not removed:
            return True, "no text tags", []

        audio.save()
        # de-dupe while preserving order
        uniq: list[str] = []
        for k in removed:
            if k not in uniq:
                uniq.append(k)
        return True, f"removed {', '.join(uniq)}", uniq
    except Exception as e:
        return False, str(e), []


def collect_files_with_text_tags(folder: Path) -> list[tuple[Path, list[tuple[str, str]]]]:
    """Scan folder for audio files that have Description / Comment / Notes tags."""
    hits: list[tuple[Path, list[tuple[str, str]]]] = []
    for p in folder.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in DESC_EXTENSIONS:
            continue
        entries = find_text_tag_entries(p)
        if entries:
            hits.append((p, entries))
    return hits


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


# Top-level / folder names to never treat as artists or albums (case-insensitive)
EMPTY_IGNORE_NAMES = {
    "artist pictures",
    "podcasts",
}


def is_ignored_dir_name(name: str) -> bool:
    """Hidden (.) folders and configured ignore names."""
    if not name or name.startswith("."):
        return True
    return name.strip().lower() in EMPTY_IGNORE_NAMES


def is_ignored_path(path: Path, library_root: Path | None = None) -> bool:
    """True if path or any component under library_root should be skipped."""
    if is_ignored_dir_name(path.name):
        return True
    if library_root is None:
        return False
    try:
        rel = path.resolve().relative_to(library_root.resolve())
    except Exception:
        return False
    return any(is_ignored_dir_name(part) for part in rel.parts)


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
    """Relative file paths under dir_path (for display). Skips hidden path parts."""
    files: list[str] = []
    try:
        for p in sorted(dir_path.rglob("*")):
            if not p.is_file():
                continue
            # Skip files inside hidden subfolders
            try:
                rel = p.relative_to(dir_path)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                files.append(str(rel))
            except ValueError:
                if p.name.startswith("."):
                    continue
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

    Skips hidden folders (e.g. .whipper_logs), Artist Pictures, and Podcasts.
    """
    results: list[tuple[Path, list[str]]] = []

    def consider(album_path: Path) -> None:
        if not album_path.is_dir():
            return
        if is_ignored_path(album_path, library_root):
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
                if not artist.is_dir() or is_ignored_dir_name(artist.name):
                    continue
                for album in sorted(artist.iterdir()):
                    if not album.is_dir() or is_ignored_dir_name(album.name):
                        continue
                    consider(album)
        elif depth == 1:
            if is_ignored_path(scope, library_root):
                return results
            for album in sorted(scope.iterdir()):
                if not album.is_dir() or is_ignored_dir_name(album.name):
                    continue
                consider(album)
        else:
            consider(scope)
    except Exception:
        pass

    return results


def run_rsgain(
    target: Path,
    skip_existing: bool,
    dry_run: bool,
    log_placeholder=None,
    jobs: int | None = None,
) -> tuple[int, str]:
    """
    Run ReplayGain. Dry-run lists files that would be processed and honors skip_existing
    by checking tags. Live run streams output into log_placeholder when provided.
    jobs: max parallel rsgain workers (-m); defaults to all visible CPUs.
    """
    max_cpus = os.cpu_count() or 2
    worker_count = max(1, min(int(jobs or max_cpus), max_cpus))

    if dry_run:
        files = [
            p for p in target.rglob("*")
            if p.is_file() and p.suffix.lower() in GAIN_EXTENSIONS
        ]
        if skip_existing:
            to_process = [p for p in files if not has_replaygain_tags(p)]
            skipped = len(files) - len(to_process)
        else:
            to_process = files
            skipped = 0

        lines = [
            f"DRY RUN — would process {len(to_process)} supported audio file(s) under {target}",
            f"Already tagged (skipped): {skipped}" if skip_existing else "Skip existing: no",
            "Mode: album + track ReplayGain (tag-only)",
            f"Skip existing: {'yes' if skip_existing else 'no'}",
            f"Parallel jobs (-m): {worker_count} of {max_cpus} CPUs",
            "Formats: FLAC, MP3, Ogg, Opus, WavPack, M4A/AAC, WMA",
            "",
        ]
        total = len(to_process)
        for i, p in enumerate(to_process, 1):
            try:
                rel = p.relative_to(target)
            except ValueError:
                rel = p
            lines.append(str(rel))
            if log_placeholder is not None and (i % 25 == 0 or i == total):
                log_placeholder.code("\n".join(lines[-LOG_PREVIEW_LINES:]), language=None)
        return 0, "\n".join(lines)

    cmd = ["rsgain", "easy", "-m", str(worker_count)]
    if skip_existing:
        cmd.append("-S")
    cmd.append(str(target))

    # Stream output so the UI is not blank while rsgain runs
    lines: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line.rstrip("\n"))
            if log_placeholder is not None:
                log_placeholder.code("\n".join(lines[-LOG_PREVIEW_LINES:]), language=None)
        code = proc.wait()
    except Exception as e:
        return 1, f"Failed to run rsgain: {e}"

    return code, "\n".join(lines).strip()


def make_log_download(logs: list[str], prefix: str, label: str = "📥 Download Log"):
    """Single log download button (legacy helper)."""
    if not logs:
        return
    content = "\n".join(logs)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.download_button(
        label=label,
        data=content,
        file_name=f"flacarr_{prefix}_{timestamp}.log",
        mime="text/plain",
        key=f"dl_{prefix}_{timestamp}"
    )


def offer_split_log_downloads(
    complete: list[str],
    action: list[str],
    errors: list[str],
    prefix: str,
    dry_run: bool,
    persist: bool = True,
) -> None:
    """
    Offer separate download buttons + a ZIP.
    Also stores artifacts in History and last_results (when persist=True).
    """
    if persist:
        push_log_artifacts(prefix, dry_run, complete, action, errors)
        store_last_results(prefix, complete, action, errors, dry_run)

    # Stable keys from stored result so buttons survive until Clear results
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    complete_txt = "\n".join(complete) if complete else "(empty)"
    action_txt = "\n".join(action) if action else "(none)"
    errors_txt = "\n".join(errors) if errors else "(none)"

    action_label = (
        "📋 Files that would be touched"
        if dry_run
        else "📋 Files processed / deleted"
    )

    st.markdown("#### Download logs")
    if dry_run:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.download_button(
                label="📄 Complete log",
                data=complete_txt,
                file_name=f"flacarr_{prefix}_complete_{stamp}.log",
                mime="text/plain",
                key=f"dl_{prefix}_complete",
            )
        with c2:
            st.download_button(
                label=action_label,
                data=action_txt,
                file_name=f"flacarr_{prefix}_action_{stamp}.log",
                mime="text/plain",
                key=f"dl_{prefix}_action",
            )
        with c3:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"flacarr_{prefix}_complete_{stamp}.log", complete_txt)
                zf.writestr(f"flacarr_{prefix}_action_{stamp}.log", action_txt)
            st.download_button(
                label="📦 ZIP (all logs)",
                data=buf.getvalue(),
                file_name=f"flacarr_{prefix}_logs_{stamp}.zip",
                mime="application/zip",
                key=f"dl_{prefix}_zip",
            )
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.download_button(
                label="📄 Complete log",
                data=complete_txt,
                file_name=f"flacarr_{prefix}_complete_{stamp}.log",
                mime="text/plain",
                key=f"dl_{prefix}_complete",
            )
        with c2:
            st.download_button(
                label=action_label,
                data=action_txt,
                file_name=f"flacarr_{prefix}_action_{stamp}.log",
                mime="text/plain",
                key=f"dl_{prefix}_action",
            )
        with c3:
            st.download_button(
                label="⚠ Error log only",
                data=errors_txt,
                file_name=f"flacarr_{prefix}_errors_{stamp}.log",
                mime="text/plain",
                key=f"dl_{prefix}_errors",
            )
        with c4:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"flacarr_{prefix}_complete_{stamp}.log", complete_txt)
                zf.writestr(f"flacarr_{prefix}_action_{stamp}.log", action_txt)
                zf.writestr(f"flacarr_{prefix}_errors_{stamp}.log", errors_txt)
            st.download_button(
                label="📦 ZIP (all logs)",
                data=buf.getvalue(),
                file_name=f"flacarr_{prefix}_logs_{stamp}.zip",
                mime="application/zip",
                key=f"dl_{prefix}_zip",
            )


def render_persisted_results(job_key: str) -> None:
    """Show last run preview + downloads until user clears."""
    data = st.session_state.last_results.get(job_key)
    if not data:
        return
    st.markdown("---")
    st.markdown("#### Last run results")
    show_scrollable_log(data.get("complete") or [])
    offer_split_log_downloads(
        complete=data.get("complete") or [],
        action=data.get("action") or [],
        errors=data.get("errors") or [],
        prefix=job_key,
        dry_run=bool(data.get("dry_run")),
        persist=False,
    )
    if st.button("Clear results", type="secondary", key=f"clear_res_{job_key}"):
        st.session_state.last_results.pop(job_key, None)
        st.rerun()


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

    st.markdown("---")
    st.subheader("ReplayGain")
    _cpu_max = os.cpu_count() or 2
    gain_jobs = st.slider(
        "Parallel jobs (cores)",
        min_value=1,
        max_value=_cpu_max,
        value=_cpu_max,
        step=1,
        help=(
            "Passed to rsgain as -m. Lower this on full-library runs if you want "
            "to leave headroom for other containers (Navidrome, Lidarr, etc.)."
        ),
        key="gain_jobs_slider",
    )
    st.caption(f"Using **{gain_jobs}** of **{_cpu_max}** visible CPUs")

    st.markdown("---")
    st.markdown(
        '[GitHub: homerjatmoes/Flacarr](https://github.com/homerjatmoes/Flacarr)',
        unsafe_allow_html=False,
    )
    st.markdown(
        '<p style="color:#888888;font-size:0.8rem;line-height:1.35;margin-top:0.5rem;">'
        "This project takes no responsibility for file loss, data corruption, "
        "or any other damage that may result from its use. "
        "<strong>Use at your own risk.</strong> Always ensure you have a current "
        "backup of your music library before proceeding."
        "</p>",
        unsafe_allow_html=True,
    )


# -------------------------------------------------
# Tabs
# -------------------------------------------------
tab_full, tab_encode, tab_gain, tab_lrc, tab_empty, tab_desc, tab_history = st.tabs([
    "Full Process",
    "Encode (Level 8)",
    "Gain",
    "LRC Cleanup",
    "Empty Folders",
    "Text Tags",
    "History",
])


# ========== FULL PROCESS ==========
with tab_full:
    st.subheader("Full Process — Encode → Gain → Text Tags")
    st.markdown("""
    Runs the post-rip pipeline on the selected scope:

    1. **Encode** — FLAC → level 8; lossless WAV → FLAC level 8
    2. **Gain** — album + track ReplayGain tags via `rsgain` (tag-only)
    3. **Text Tags** *(optional)* — remove Description / Comment / Notes
    """)
    st.markdown(
        '<p class="flacarr-dryrun-note">Use Dry Run the first time. When Dry Run is off, enabled steps modify files.</p>',
        unsafe_allow_html=True,
    )

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
    full_text_tags = st.checkbox(
        "Remove Description / Comment / Notes tags",
        value=True,
        key="full_text_tags",
        help="Same cleanup as the Text Tags tab (DESCRIPTION, COMMENT, NOTES, NOTE, ID3 COMM)",
    )

    if not full_dry:
        st.warning(
            "⚠️ Dry Run is **off**. Enabled steps will re-encode audio, write ReplayGain tags, "
            "and/or remove text tags."
        )

    if st.button("Start Full Process", type="primary", key="btn_full"):
        if not folder or not folder.exists():
            st.error("Please choose a valid scope in the sidebar.")
        else:
            combined_logs: list[str] = []
            action_logs: list[str] = []
            error_logs: list[str] = []

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
                            line = f"↷ SKIPPED (already level 8): {rel}"
                            combined_logs.append(line)
                            enc_skipped += 1
                        elif full_dry:
                            if suffix == ".flac":
                                line = f"DRY  would encode FLAC: {rel}"
                                combined_logs.append(line)
                                action_logs.append(line)
                                enc_success += 1
                            else:
                                lossless = is_lossless_wav(f)
                                if lossless:
                                    line = f"DRY  would convert WAV→FLAC: {rel}"
                                    combined_logs.append(line)
                                    action_logs.append(line)
                                    enc_success += 1
                                else:
                                    line = f"DRY  skip WAV (not lossless PCM): {rel}"
                                    combined_logs.append(line)
                                    enc_skipped += 1
                        else:
                            if suffix == ".flac":
                                ok, msg = convert_to_level8(f)
                            else:
                                ok, msg = convert_wav_to_flac(f, delete_wav=full_delete_wav)
                            if ok:
                                enc_success += 1
                                line = f"✓ {rel}" + (f" — {msg}" if msg != "OK" else "")
                                combined_logs.append(line)
                                action_logs.append(line)
                            else:
                                enc_failed += 1
                                line = f"✗ {rel} → {msg}"
                                combined_logs.append(line)
                                error_logs.append(line)

                        log_placeholder.code("\n".join(combined_logs[-25:]), language=None)

            enc_summary = (
                f"Encode summary: {enc_success} ok • {enc_skipped} skipped • {enc_failed} failed (total {total})"
            )
            combined_logs.append(enc_summary)
            combined_logs.append("")

            # 2. GAIN — full output in complete log; live preview while running
            combined_logs.append("--- 2. GAIN (ReplayGain) ---")
            gain_placeholder = st.empty()
            with st.spinner("Running ReplayGain…"):
                code, output = run_rsgain(
                    folder,
                    skip_existing=full_gain_skip,
                    dry_run=full_dry,
                    log_placeholder=gain_placeholder,
                    jobs=gain_jobs,
                )
            gain_lines = output.splitlines() if output else []
            if gain_lines:
                combined_logs.extend(gain_lines)
                if full_dry:
                    for gl in gain_lines:
                        g = gl.strip()
                        if not g:
                            continue
                        if g.startswith((
                            "DRY", "[", "Mode:", "Skip", "Formats:", "===",
                            "Already tagged",
                        )):
                            continue
                        if "/" in g or g.endswith((
                            ".flac", ".mp3", ".ogg", ".opus", ".m4a", ".wav", ".wv", ".wma", ".aac"
                        )):
                            action_logs.append(f"GAIN would process: {g}")
            else:
                combined_logs.append("(no rsgain output)")
            combined_logs.append(f"Gain exit code: {code}")
            if code != 0:
                error_logs.append(f"Gain exit code: {code}")
                if gain_lines:
                    error_logs.extend(gain_lines[-50:])
            combined_logs.append("")

            # 3. TEXT TAGS (optional)
            text_ok = text_fail = 0
            if full_text_tags:
                combined_logs.append("--- 3. TEXT TAGS (Description / Comment / Notes) ---")
                with st.spinner("Scanning text tags…"):
                    hits = collect_files_with_text_tags(folder)
                combined_logs.append(f"Files with matching tags: {len(hits)}")
                if not hits:
                    combined_logs.append("Nothing to clean up.")
                else:
                    text_placeholder = st.empty()
                    for i, (path, entries) in enumerate(hits, 1):
                        try:
                            rel = path.relative_to(folder)
                        except ValueError:
                            rel = path
                        keys = ", ".join(k for k, _ in entries)
                        if full_dry:
                            line = f"DRY  would remove [{keys}]: {rel}"
                            combined_logs.append(line)
                            action_logs.append(line)
                            text_ok += 1
                        else:
                            success, msg, removed = remove_text_tags(path)
                            if success and removed:
                                line = f"✓ removed [{', '.join(removed)}]: {rel}"
                                combined_logs.append(line)
                                action_logs.append(line)
                                text_ok += 1
                            elif success:
                                line = f"↷ skipped (none found): {rel}"
                                combined_logs.append(line)
                            else:
                                line = f"✗ {rel} → {msg}"
                                combined_logs.append(line)
                                error_logs.append(line)
                                text_fail += 1
                        if i % 20 == 0 or i == len(hits):
                            text_placeholder.code(
                                "\n".join(combined_logs[-LOG_PREVIEW_LINES:]), language=None
                            )
                    if full_dry:
                        combined_logs.append(
                            f"Text tags summary: {text_ok} would be cleaned"
                        )
                    else:
                        combined_logs.append(
                            f"Text tags summary: {text_ok} cleaned • {text_fail} failed"
                        )
                combined_logs.append("")
            else:
                combined_logs.append("--- 3. TEXT TAGS — skipped (checkbox off) ---")
                combined_logs.append("")

            combined_logs.append("=== FULL PROCESS COMPLETE ===")

            if full_dry:
                st.success("Dry Run finished — nothing was modified.")
            else:
                text_note = ""
                if full_text_tags:
                    text_note = f"  •  Text tags: {text_ok} cleaned / {text_fail} fail"
                st.success(
                    f"Full Process finished — Encode: {enc_success} ok / {enc_skipped} skip / {enc_failed} fail  •  "
                    f"Gain exit {code}{text_note}"
                )

            show_scrollable_log(combined_logs)
            push_log_artifacts("full_process", full_dry, combined_logs, action_logs, error_logs)
            store_last_results("full_process", combined_logs, action_logs, error_logs, full_dry)

    render_persisted_results("full_process")


# ========== ENCODE ==========
with tab_encode:
    st.subheader("Convert to FLAC compression level 8")
    st.markdown("""
    - **FLAC** → re-encode to level 8 **in-place** (lossless; bit depth preserved)
    - **WAV** → if standard lossless PCM, convert to FLAC level 8
    - MP3 and other lossy formats are ignored
    - Strips non-standard ID3v2 tags from FLAC before encoding
    """)
    st.markdown(
        '<p class="flacarr-dryrun-note">Use Dry Run the first time. When Dry Run is off, files will be modified.</p>',
        unsafe_allow_html=True,
    )

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
                logs: list[str] = []
                action_logs: list[str] = []
                error_logs: list[str] = []
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
                                line = f"DRY  would encode FLAC: {rel}"
                                logs.append(line)
                                action_logs.append(line)
                                success += 1
                            else:
                                if is_lossless_wav(f):
                                    line = f"DRY  would convert WAV→FLAC: {rel}"
                                    logs.append(line)
                                    action_logs.append(line)
                                    success += 1
                                else:
                                    logs.append(f"↷ SKIPPED WAV (not lossless PCM): {rel}")
                                    skipped += 1
                        elif suffix == ".flac":
                            ok, msg = convert_to_level8(f)
                            if ok:
                                success += 1
                                line = f"✓ {rel}"
                                logs.append(line)
                                action_logs.append(line)
                            else:
                                failed += 1
                                line = f"✗ {rel} → {msg}"
                                logs.append(line)
                                error_logs.append(line)
                        else:
                            ok, msg = convert_wav_to_flac(f, delete_wav=delete_wav)
                            if ok:
                                success += 1
                                line = f"✓ {rel} — {msg}"
                                logs.append(line)
                                action_logs.append(line)
                            else:
                                if "not a standard lossless" in msg or "already exists" in msg:
                                    skipped += 1
                                    logs.append(f"↷ SKIPPED: {rel} → {msg}")
                                else:
                                    failed += 1
                                    line = f"✗ {rel} → {msg}"
                                    logs.append(line)
                                    error_logs.append(line)

                        log_placeholder.code("\n".join(logs[-30:]), language=None)

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
                show_scrollable_log(logs)
                push_log_artifacts("encode", enc_dry, logs, action_logs, error_logs)
                store_last_results("encode", logs, action_logs, error_logs, enc_dry)

    render_persisted_results("encode")


# ========== GAIN ==========
with tab_gain:
    st.subheader("ReplayGain (tag-only)")
    st.markdown("""
    - **Tag-only** — audio stream is not modified
    - **Album + track** gain for every supported file
    - Formats: FLAC, MP3, Ogg, Opus, WavPack, M4A/AAC, WMA
    """)
    st.markdown(
        '<p class="flacarr-dryrun-note">Use Dry Run the first time. When Dry Run is off, ReplayGain tags will be written.</p>',
        unsafe_allow_html=True,
    )

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

    if st.button("Start Gain", type="primary", key="btn_gain"):
        if not folder or not folder.exists():
            st.error("Please choose a valid scope in the sidebar.")
        else:
            log_placeholder = st.empty()
            with st.spinner("Running ReplayGain…"):
                code, output = run_rsgain(
                    folder,
                    skip_existing=gain_skip,
                    dry_run=gain_dry,
                    log_placeholder=log_placeholder,
                    jobs=gain_jobs,
                )

            lines = output.splitlines() if output else []

            action_logs: list[str] = []
            error_logs: list[str] = []
            if gain_dry:
                for gl in lines:
                    g = gl.strip()
                    if not g:
                        continue
                    if g.startswith((
                        "DRY", "[", "Mode:", "Skip", "Formats:", "===", "Already tagged",
                    )):
                        continue
                    if "/" in g or g.endswith((
                        ".flac", ".mp3", ".ogg", ".opus", ".m4a", ".wav", ".wv", ".wma", ".aac"
                    )):
                        action_logs.append(g)
            if code != 0:
                error_logs.append(f"Gain exit code: {code}")
                error_logs.extend(lines[-50:] if lines else [])

            if code == 0:
                st.success(
                    "Gain finished."
                    + (" (dry run — nothing written)" if gain_dry else " Tags written.")
                )
            else:
                st.error(f"rsgain exited with code {code}")

            complete = lines if lines else ["(no rsgain output)"]
            show_scrollable_log(complete)
            push_log_artifacts("gain", gain_dry, complete, action_logs, error_logs)
            store_last_results("gain", complete, action_logs, error_logs, gain_dry)

    render_persisted_results("gain")


# ========== LRC CLEANUP ==========
with tab_lrc:
    st.subheader("Orphan .lrc cleanup")
    st.markdown("""
    Finds **`.lrc`** files that no longer have a matching audio file in the same folder
    (same base name). Typical after **Lidarr** renames change punctuation or case.

    Matching: exact stem, then case-insensitive stem, against common audio extensions.
    """)
    st.markdown(
        '<p class="flacarr-dryrun-note">Use Dry Run the first time. When Dry Run is off, orphan `.lrc` files will be deleted.</p>',
        unsafe_allow_html=True,
    )

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

            action_logs: list[str] = []
            error_logs: list[str] = []

            if not orphans:
                logs.append("Nothing to clean up.")
                st.success("No orphan .lrc files found.")
                show_scrollable_log(logs)
                push_log_artifacts("lrc_cleanup", lrc_dry, logs, action_logs, error_logs)
                store_last_results("lrc_cleanup", logs, action_logs, error_logs, lrc_dry)
            else:
                deleted = failed = 0
                log_placeholder = st.empty()

                if lrc_dry:
                    for p in orphans:
                        try:
                            rel = p.relative_to(folder)
                        except ValueError:
                            rel = p
                        line = f"DRY  would delete: {rel}"
                        logs.append(line)
                        action_logs.append(line)
                    logs.append("")
                    logs.append(f"Dry Run summary: {len(orphans)} would be deleted. Nothing was modified.")
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
                            line = f"✓ deleted: {rel}"
                            logs.append(line)
                            action_logs.append(line)
                        except Exception as e:
                            failed += 1
                            line = f"✗ {rel} → {e}"
                            logs.append(line)
                            error_logs.append(line)
                        log_placeholder.code("\n".join(logs[-LOG_PREVIEW_LINES:]), language=None)
                    logs.append("")
                    logs.append(f"Delete summary: {deleted} deleted • {failed} failed • {len(orphans)} total")
                    st.success(f"Done — **{deleted}** deleted • **{failed}** failed.")

                show_scrollable_log(logs)
                push_log_artifacts("lrc_cleanup", lrc_dry, logs, action_logs, error_logs)
                store_last_results("lrc_cleanup", logs, action_logs, error_logs, lrc_dry)

    render_persisted_results("lrc_cleanup")


# ========== EMPTY FOLDERS ==========
with tab_empty:
    st.subheader("Album folders with no audio")
    st.markdown("""
    Finds **album folders** under the current scope that contain **no audio files**
    (but may still have `.lrc`, `.jpg`, `.txt`, etc.). Lidarr will not remove those
    because they are not empty.

    Structure expected: `Artist / Album (Year) / …`

    **Ignored:** hidden folders (`.…`), `Artist Pictures`, `Podcasts`
    """)
    st.markdown(
        '<p class="flacarr-dryrun-note">Use Dry Run the first time. When Dry Run is off, selected folders are deleted recursively.</p>',
        unsafe_allow_html=True,
    )

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

            # Always write a scan log (so downloads / History work even before delete)
            scan_logs: list[str] = [
                f"=== EMPTY FOLDERS SCAN  |  scope: {scope_label or folder} ===",
                f"Found {len(found)} album folder(s) with no audio",
                "Ignored: hidden folders, Artist Pictures, Podcasts",
                "",
            ]
            scan_action: list[str] = []
            for p, files in found:
                try:
                    rel = str(p.relative_to(root))
                except Exception:
                    rel = str(p)
                n = len([f for f in files if f != "…"])
                extra = "+" if "…" in files else ""
                line = f"EMPTY: {rel}  ({n}{extra} leftover file(s))"
                scan_logs.append(line)
                scan_action.append(line)
                for f in files[:15]:
                    if f != "…":
                        scan_logs.append(f"       · {f}")
                if len(files) > 15:
                    scan_logs.append("       · …")
            if not found:
                scan_logs.append("Nothing to clean up.")
            push_log_artifacts("empty_folders", True, scan_logs, scan_action, [])
            store_last_results("empty_folders", scan_logs, scan_action, [], True)

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
                action_logs: list[str] = []
                error_logs: list[str] = []
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
                        line = f"DRY  would delete folder: {rel}"
                        logs.append(line)
                        action_logs.append(line)
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
                            line = f"✓ deleted folder: {rel}"
                            logs.append(line)
                            action_logs.append(line)
                        except Exception as e:
                            failed += 1
                            line = f"✗ {rel} → {e}"
                            logs.append(line)
                            error_logs.append(line)
                    log_placeholder.code("\n".join(logs[-40:]), language=None)

                logs.append("")
                if empty_dry:
                    logs.append(f"Dry Run summary: {removed} folder(s) would be deleted. Nothing was modified.")
                    st.success(f"Dry Run — **{removed}** folder(s) would be deleted.")
                else:
                    logs.append(f"Delete summary: {removed} deleted • {failed} failed")
                    st.success(f"Done — **{removed}** deleted • **{failed}** failed.")
                    gone = {label_to_path[l] for l in selected}
                    st.session_state.empty_scan_results = [
                        (ps, f) for ps, f in results if ps not in gone
                    ]

                show_scrollable_log(logs)
                push_log_artifacts("empty_folders", empty_dry, logs, action_logs, error_logs)
                store_last_results("empty_folders", logs, action_logs, error_logs, empty_dry)
    else:
        st.caption("Click **Scan for Empty Albums** to search the current scope.")

    render_persisted_results("empty_folders")


# ========== TEXT TAG REMOVAL (Description / Comment / Notes) ==========
with tab_desc:
    st.subheader("Remove Description, Comment & Notes")
    st.markdown("""
    Removes free-text tags you do not use:

    - **Description** (`DESCRIPTION`)
    - **Comment** (`COMMENT`, and ID3 `COMM` on MP3)
    - **Notes** (`NOTES` / `NOTE`)

    Tag-only — the audio stream is never modified.

    Formats: FLAC, MP3, Ogg, Opus, WavPack, M4A/AAC, WMA
    """)
    st.markdown(
        '<p class="flacarr-dryrun-note">Use Dry Run the first time. When Dry Run is off, these tags will be removed.</p>',
        unsafe_allow_html=True,
    )

    desc_dry = st.checkbox(
        "Dry Run (list only — do not modify tags)",
        value=True,
        key="desc_dry_run",
    )

    if not desc_dry:
        st.warning(
            "⚠️ Dry Run is **off**. Description, Comment, and Notes tags will be **removed**."
        )

    if st.button("Start Text Tag Cleanup", type="primary", key="btn_desc"):
        if not folder or not folder.exists():
            st.error("Please choose a valid scope in the sidebar.")
        else:
            with st.spinner("Scanning for Description / Comment / Notes tags…"):
                hits = collect_files_with_text_tags(folder)

            logs: list[str] = [
                f"=== TEXT TAG CLEANUP  |  scope: {scope_label or folder}  |  dry={desc_dry} ===",
                "Targets: DESCRIPTION, COMMENT, NOTES, NOTE (+ ID3 COMM)",
                f"Files with matching tags: {len(hits)}",
                "",
            ]
            action_logs: list[str] = []
            error_logs: list[str] = []
            ok_count = fail_count = 0
            log_placeholder = st.empty()

            if not hits:
                logs.append("Nothing to clean up.")
                st.success("No Description / Comment / Notes tags found in scope.")
            else:
                for i, (path, entries) in enumerate(hits, 1):
                    try:
                        rel = path.relative_to(folder)
                    except ValueError:
                        rel = path
                    keys = ", ".join(k for k, _ in entries)
                    preview = entries[0][1] if entries else ""
                    preview_note = f" — {preview[:60]}" if preview else ""

                    if desc_dry:
                        line = f"DRY  would remove [{keys}]: {rel}{preview_note}"
                        logs.append(line)
                        action_logs.append(line)
                        ok_count += 1
                    else:
                        success, msg, removed = remove_text_tags(path)
                        if success and removed:
                            line = f"✓ removed [{', '.join(removed)}]: {rel}"
                            logs.append(line)
                            action_logs.append(line)
                            ok_count += 1
                        elif success:
                            line = f"↷ skipped (none found): {rel}"
                            logs.append(line)
                        else:
                            line = f"✗ {rel} → {msg}"
                            logs.append(line)
                            error_logs.append(line)
                            fail_count += 1

                    if i % 20 == 0 or i == len(hits):
                        log_placeholder.code(
                            "\n".join(logs[-LOG_PREVIEW_LINES:]), language=None
                        )

                logs.append("")
                if desc_dry:
                    logs.append(
                        f"Dry Run summary: {ok_count} file(s) would be cleaned. Nothing was modified."
                    )
                    st.success(
                        f"Dry Run — **{ok_count}** file(s) have Description / Comment / Notes tags."
                    )
                else:
                    logs.append(
                        f"Summary: {ok_count} cleaned • {fail_count} failed • {len(hits)} total"
                    )
                    st.success(f"Done — **{ok_count}** cleaned • **{fail_count}** failed.")

            show_scrollable_log(logs)
            push_log_artifacts("text_tags", desc_dry, logs, action_logs, error_logs)
            store_last_results("text_tags", logs, action_logs, error_logs, desc_dry)

    render_persisted_results("text_tags")


# ========== HISTORY ==========
with tab_history:
    st.subheader("Log history")
    st.markdown(
        f"Keeps the last **{ARTIFACTS_PER_TYPE}** of each type: "
        "`complete` · `action` · `errors` · `dry_run`."
    )

    arts = st.session_state.log_artifacts
    if not arts:
        st.info("No saved logs yet. Run a job to generate downloadable history.")
    else:
        # counts by type
        counts: dict[str, int] = {}
        for a in arts:
            counts[a["type"]] = counts.get(a["type"], 0) + 1
        st.caption(
            " · ".join(f"**{t}**: {n}" for t, n in sorted(counts.items()))
        )

        selected_ids: list[str] = []
        for a in arts:
            label = (
                f"[{a['ts']}]  {a['job']}  ·  {a['type']}"
                f"{'  ·  dry' if a.get('dry_run') else ''}"
                f"  ·  {a.get('line_count', '?')} lines"
            )
            if st.checkbox(label, key=f"hist_cb_{a['id']}"):
                selected_ids.append(a["id"])

        c1, c2, c3 = st.columns(3)
        with c1:
            dl_clicked = st.button(
                "Download Selected",
                type="primary",
                key="hist_dl_selected",
                disabled=not selected_ids,
            )
        with c2:
            clr_sel = st.button(
                "Clear Selected",
                type="secondary",
                key="hist_clr_selected",
                disabled=not selected_ids,
            )
        with c3:
            clr_all = st.button(
                "Clear All History",
                type="secondary",
                key="hist_clr_all",
            )

        if dl_clicked and selected_ids:
            chosen = [a for a in arts if a["id"] in selected_ids]
            buf = io.BytesIO()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for a in chosen:
                    name = (
                        f"flacarr_{a['job']}_{a['type']}_"
                        f"{a['ts'].replace(':', '').replace(' ', '_')}.log"
                    )
                    zf.writestr(name, a.get("content") or "(empty)")
            st.download_button(
                label="📦 Save ZIP of selected logs",
                data=buf.getvalue(),
                file_name=f"flacarr_history_{stamp}.zip",
                mime="application/zip",
                key=f"hist_zip_{stamp}",
                type="primary",
            )

        if clr_sel and selected_ids:
            st.session_state.log_artifacts = [
                a for a in arts if a["id"] not in selected_ids
            ]
            st.rerun()

        if clr_all:
            st.session_state.hist_clear_confirm = True

        if st.session_state.hist_clear_confirm:
            st.warning("This will permanently clear **all** saved log history in this session.")
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("Yes — clear all history", type="secondary", key="hist_clr_yes"):
                    st.session_state.log_artifacts = []
                    st.session_state.hist_clear_confirm = False
                    st.rerun()
            with cc2:
                if st.button("Cancel", type="primary", key="hist_clr_no"):
                    st.session_state.hist_clear_confirm = False
                    st.rerun()
