# Flacarr

Web-based toolkit for maintaining a music library.  
Runs as a Streamlit app on port **10069**, designed for Docker (including Unraid Compose).

**Lidarr** owns naming and multi-disc folder structure.  
**Flacarr** owns encode (level 8), ReplayGain, orphan `.lrc` cleanup, empty-folder cleanup, and free-text tag removal (Description / Comment / Notes).

Flacarr is AI coded with human review.

---

## What it does

| Tab | Purpose |
|-----|---------|
| **Full Process** | One pass: **Encode → Gain** on the selected scope |
| **Encode (Level 8)** | FLAC → level 8; lossless WAV → FLAC level 8 |
| **Gain** | Album + track ReplayGain tags (tag-only) via `rsgain` |
| **LRC Cleanup** | Find/delete orphan `.lrc` files with no matching audio |
| **Empty Folders** | Album folders with no audio (leftover `.lrc`/`.jpg`/`.txt`) |
| **Text Tags** | Remove Description / Comment / Notes tags (tag-only) |
| **History** | Saved log artifacts (complete / action / errors / dry_run) |

---

## Scope (sidebar)

Limit every job to:

- **Entire library**
- **One artist** (dropdown)
- **One album** (artist → album)
- Or type a **relative path** (e.g. `Rolling Stones, The`)

**Library root** is the path *inside the container* (usually `/mnt/user/Media/Music` on Unraid, or your bind-mounted path).

The sidebar shows FLAC and WAV counts for the current scope.

### ReplayGain parallel jobs

Sidebar control: **Parallel jobs (cores)** (slider, 1 → all visible CPUs).

- Passed to `rsgain` as `-m`
- Default: all CPUs the container can see
- Lower this on full-library runs to leave headroom for other services (Navidrome, Lidarr, etc.)

---

## Full Process

Runs in order:

1. **Encode** — FLAC re-encode to level 8; lossless WAV → FLAC level 8  
2. **Gain** — album + track ReplayGain (`rsgain easy`)

Options:

- **Dry Run** — preview only; nothing written  
- **Skip files already marked as level 8**  
- **Skip files that already have ReplayGain tags**  
- **Delete WAV after successful FLAC conversion**

---

## Encode (Level 8)

- **FLAC** — re-encode **in-place** to compression level 8 (lossless; 16-bit and 24-bit preserved)  
- **WAV** — if standard **uncompressed PCM** (lossless), convert to FLAC level 8  
- Non-PCM / unusual WAV containers are **skipped**  
- **MP3 and other lossy formats are ignored**  
- Non-standard **ID3v2** tags are stripped from FLAC before encoding (Vorbis tags and art kept)  
- After success, writes tag `flacarr_level=8` for later skips  

Options:

- **Dry Run** — preview only; nothing written  
- Skip files already marked as level 8  
- Delete WAV after successful conversion  

---

## Gain (ReplayGain)

- **Tag-only** — audio data is never modified  
- Always computes **album + track** gain  
- Engine: **rsgain**  
- Formats: FLAC, MP3, Ogg, Opus, WavPack, M4A/AAC, WMA  
- Live log stream while running  
- Parallelism controlled from the sidebar (see above)  

Options:

- **Dry Run** — list files that would be processed (honors skip-existing by checking tags)  
- Skip files that already have ReplayGain / R128 tags  

---

## LRC Cleanup

After **Lidarr** renames (punctuation, letter case, etc.), sidecar `.lrc` files from LRCGET may no longer match the audio name.

- Scans the selected scope for `.lrc` files with **no matching audio** in the same folder  
- Match: same stem (exact, then case-insensitive) against common audio extensions  
- **Dry Run** (default) lists orphans only  
- With Dry Run off, orphans are **deleted**  

Does **not** rename `.lrc` files to match new audio names — only removes true orphans.

---

## Empty Folders

Lidarr only removes **completely empty** directories. Album folders that still hold `.lrc`, `.jpg`, `.txt`, etc. (but **no audio**) are left behind.

- Scans for **album folders** (`Artist / Album`) with **no audio** in the subtree  
- Lists leftover file names for each  
- **Multiselect** which folders to remove  
- **Dry Run** (default) previews only  
- With Dry Run off, selected folders are deleted recursively  
- **Scan** and **Remove** both write downloadable logs (History + Last run results)  

### Ignored paths

These are never treated as artists/albums:

- **Hidden folders** (names starting with `.`, e.g. `.whipper_logs`)  
- **`Artist Pictures`**  
- **`Podcasts`**  

(case-insensitive)

---

## Text Tags

Removes free-text tags that are not used in this workflow:

- **Description** (`DESCRIPTION`)
- **Comment** (`COMMENT`, and ID3 `COMM` on MP3)
- **Notes** (`NOTES` / `NOTE`)

- **Tag-only** — audio stream is never modified  
- Formats: FLAC, MP3, Ogg, Opus, WavPack, M4A/AAC, WMA  
- **Dry Run** (default) lists files that have any of these tags  
- With Dry Run off, matching tags are removed and the file is saved  

---

## Logs and downloads

After every job:

- **Preview** is limited to the last **100 lines** (scrollable)  
- Full output is available as downloads  
- Downloads stay on the tab until **Clear results**  

### Download sets

**Dry Run**

| File | Contents |
|------|----------|
| **Complete log** | Full run (headers, skips, summaries) |
| **Files that would be touched** | Only items that would be encoded / tagged / deleted |
| **ZIP** | Both files |

**Process run**

| File | Contents |
|------|----------|
| **Complete log** | Full run |
| **Files processed / deleted** | Successful actions only |
| **Error log only** | Failures only |
| **ZIP** | All three |

---

## History

Single **History** tab (session-only):

- Keeps the last **20** of each type: `complete` · `action` · `errors` · `dry_run`  
- Checkbox per artifact  
- **Download Selected** → ZIP of chosen logs  
- **Clear Selected**  
- **Clear All History** with confirmation  

Cleared on browser refresh / container restart unless you downloaded the files.

---

## Files in this project

```text
Flacarr.py           # main app
Dockerfile           # flac + rsgain + Python deps
docker-compose.yml   # Docker / Unraid stack
requirements.txt     # streamlit, mutagen
flacarr.jpg          # in-app logo
Flacarr.png          # optional container icon
README.md
```

---

## Docker (standard)

Requirements: Docker Engine and Docker Compose v2.

1. Clone or copy this repository:

   ```bash
   git clone https://github.com/homerjatmoes/Flacarr.git
   cd Flacarr
   ```

2. Edit `docker-compose.yml`:
   - Map your music library on the left side of the volume
   - Adjust port if `10069` is already in use
   - Remove or change the external `media` network if you are not on Unraid

   Minimal example:

   ```yaml
   services:
     flacarr:
       build: .
       container_name: flacarr
       ports:
         - "10069:10069"
       volumes:
         - /path/to/your/Music:/mnt/user/Media/Music
       restart: unless-stopped
   ```

3. Build and start:

   ```bash
   docker compose up -d --build
   ```

4. Open the app:

   ```text
   http://localhost:10069
   ```
   or `http://YOUR-SERVER-IP:10069` from another machine.

### Useful commands

```bash
docker compose logs -f
docker compose down
docker compose up -d --build
docker compose up -d --force-recreate
```

Set the **Library root** in the sidebar to the path *inside* the container (the right-hand side of the volume mount, e.g. `/mnt/user/Media/Music`).

---

## Docker on Unraid

1. Copy this folder to e.g. `/mnt/user/appdata/flacarr`.

2. Edit `docker-compose.yml` if needed:
   - Music volume (host path on the left)
   - External network `media` (must already exist)
   - Icon path for Unraid

   Example:

   ```yaml
   services:
     flacarr:
       build: .
       container_name: flacarr
       ports:
         - "10069:10069"
       volumes:
         - /mnt/user/Media/Music:/mnt/user/Media/Music
       restart: unless-stopped
       networks:
         - media
       labels:
         net.unraid.docker.icon: "/mnt/user/appdata/flacarr/Flacarr.png"
         net.unraid.docker.webui: "http://[IP]:[PORT:10069]"

   networks:
     media:
       external: true
   ```

3. Start:

   ```bash
   cd /mnt/user/appdata/flacarr
   docker compose up -d --build
   ```

   Or use **Compose Manager Plus** with Indirect Path → `/mnt/user/appdata/flacarr`.

4. Open:

   ```text
   http://YOUR-UNRAID-IP:10069
   ```

---

## Local run (without Docker)

Install `flac` and `rsgain` on the host, then:

```bash
pip install -r requirements.txt
streamlit run Flacarr.py \
  --server.port 10069 \
  --server.address 0.0.0.0 \
  --theme.base=dark \
  --theme.primaryColor=#3fb950 \
  --client.toolbarMode=minimal
```

---

## Notes

- WAV lossless detection uses Python’s `wave` module (standard PCM WAV only).  
- Re-encoding FLAC level 8 → level 8 is safe and lossless.  
- Prefer **Dry Run** the first time you use any job on a large scope.  
- Gain dry run with “skip existing” checks tags on each file (can take a few minutes on a full library).  
- For multi-disc folder layout, use **Lidarr**, not Flacarr.  
- History and “last results” are session-based; download logs you want to keep.  
- Hide maintenance folders with a leading `.` so Empty Folders and scans ignore them.  

---

## Disclaimer

This project takes **no responsibility** for file loss, data corruption, or any other damage that may result from its use.  

**Use at your own risk.** Always ensure you have a current backup of your music library before running encode, gain, cleanup, or any other operation that modifies or deletes files.
