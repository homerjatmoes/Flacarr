# Flacarr

Web-based toolkit for maintaining a music library.  
Runs as a Streamlit app on port **10069**, built for Unraid (Docker Compose).

**Lidarr** owns naming and multi-disc folder structure.  
**Flacarr** owns encode (level 8), ReplayGain, and orphan `.lrc` cleanup.

---

## What it does

| Tab | Purpose |
|-----|---------|
| **Full Process** | One pass: **Encode → Gain** on the selected scope |
| **Encode (Level 8)** | FLAC → level 8; lossless WAV → FLAC level 8 |
| **Gain** | Album + track ReplayGain tags (tag-only) via `rsgain` |
| **LRC Cleanup** | Find/delete orphan `.lrc` files with no matching audio |
| **Empty Folders** | Album folders with no audio (leftover `.lrc`/`.jpg`/`.txt`) |
| **Encode History** | Last 300 encode results |
| **Gain History** | Last 300 gain results |
| **Full History** | Last 300 full-process logs |
| **LRC History** | Last 300 LRC cleanup results |
| **Empty History** | Last 300 empty-folder cleanup results |

---

## Scope (sidebar)

Limit every job to:

- **Entire library**
- **One artist** (dropdown)
- **One album** (artist → album)
- Or type a **relative path** (e.g. `Rolling Stones, The`)

**Library root** is the path *inside the container* (usually `/mnt/user/Media/Music`).

The sidebar shows FLAC and WAV counts for the current scope.

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

Options on this tab:

- **Dry Run** — preview only; nothing written  
- Skip files already marked as level 8  
- Delete WAV after successful conversion  

---

## Gain (ReplayGain)

- **Tag-only** — audio data is never modified  
- Always computes **album + track** gain  
- Engine: **rsgain**  
- Formats: FLAC, MP3, Ogg, Opus, WavPack, M4A/AAC, WMA  

Options:

- Skip files that already have ReplayGain tags  
- Dry Run (list only)  

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

---

## History

- Up to **300** entries per history tab (newest first)  
- **Download Log** and **Clear History** on each  
- Stored in the browser session only (cleared on refresh / container restart unless downloaded)  

---

## UI

- Dark theme only (no light mode)  
- Green primary buttons; red Clear History buttons  
- Green selected-tab highlight  
- Compact left-aligned logo (`flacarr.jpg`)  

---

## Files in this project

```text
Flacarr.py           # main app
Dockerfile           # flac + rsgain + Python deps
docker-compose.yml   # Unraid stack (media network, icon labels)
requirements.txt     # streamlit, mutagen
flacarr.jpg          # in-app logo
Flacarr.png          # Unraid container icon
README.md
```

---

## Docker Compose (Unraid)

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

### Useful commands

```bash
docker compose logs -f
docker compose down
docker compose up -d --build
docker compose up -d --force-recreate
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
- Prefer **Dry Run** the first time you use Full Process or Gain on a large scope.  
- For multi-disc folder layout, use **Lidarr**, not Flacarr.  
