# Flacarr

Web-based toolkit for maintaining a FLAC (and mixed-format) music library.  
Runs as a Streamlit app on port **10069**, designed for Unraid via Docker Compose.

---

## Features

### Scope (sidebar)
Limit every job to:
- **Entire library**
- **One artist** (dropdown of folders under the library root)
- **One album** (artist → album)
- Or type a **relative path** manually (e.g. `Rolling Stones, The` or `Artist/Album (Year)`)

Library root is the path **inside the container** (typically `/mnt/user/Media/Music`).

---

### Full Process (new)
One-button pipeline that runs the three steps in order on the selected scope:

1. **Encode** → level 8
2. **Rename / Organize** → multi-disc CD folders
3. **Gain** → album + track ReplayGain

- **Dry Run** mode (default) previews every step without writing anything
- When Dry Run is off, all three steps modify files in a single pass
- Combined log + download; entries also appear in the individual history tabs (prefixed `(full)`)
- Uses the same sidebar scope and “Skip already level 8” option

---

### Encode (Level 8)
- Re-encode **FLAC only** to compression level 8 (in-place, recursive)
- Lossless; preserves bit depth (16-bit and 24-bit stay as they are)
- Ignores MP3 and other non-FLAC files
- Strips non-standard **ID3v2** tags on FLAC before encoding (keeps Vorbis tags and embedded art)
- Option: **Skip files already marked as level 8** (writes a `flacarr_level=8` tag after success)
- Spinner progress and downloadable log

---

### Rename / Organize
- **Preserves Lidarr-style names** — does not rebuild Artist / Album / title from tags
- Only adjusts the **`CD xx` folder** level:
  - **Single-disc** → no `CD xx` folder (removes one if present)
  - **Multi-disc** → ensures tracks sit under `CD 01`, `CD 02`, …
- Uses discnumber / totaldiscs tags only for that decision
- **Dry Run** preview before moving files
- Confirm step before applying moves
- Downloadable log

---

### Gain (ReplayGain)
- **Tag-only** — audio stream is never modified
- Always writes **album + track** ReplayGain
- Powered by **rsgain** (`rsgain easy`)
- Formats: **FLAC, MP3, Ogg, Opus, WavPack, M4A/AAC, WMA** (whatever rsgain supports)
- Options:
  - **Skip files that already have ReplayGain tags** (`-S`)
  - **Dry Run** (list files that would be processed; write nothing)
- Uses the same scope as Encode / Rename / Full Process

---

### History tabs
| Tab | Contents |
|-----|----------|
| **Encode History** | Last 300 encode results (newest first) |
| **Rename History** | Last 300 rename / dry-run results |
| **Gain History** | Last 300 gain / dry-run results |
| **Full History** | Last 300 full-process combined logs |

Each history tab supports **Download Log** and **Clear History**.

History is kept in the **browser session** (cleared on refresh or container restart unless downloaded).

---

### UI
- Dark theme only (no light mode)
- Streamlit chrome / theme picker hidden
- Green primary actions (Start Full Process, Start Encoding, Start Rename, Start Gain Scan, Confirm)
- Red Clear History buttons
- Green selected-tab highlight
- Left-aligned compact logo (`flacarr.jpg` in the app folder)

---

## Requirements (Docker image)
- `flac` — level 8 re-encode
- `rsgain` — ReplayGain tagging
- Python packages: `streamlit`, `mutagen`

---

## Run with Docker Compose (Unraid)

1. Copy the `Flacarr` folder to the server, e.g. `/mnt/user/appdata/flacarr`.

2. Ensure these files are present:
   ```text
   docker-compose.yml
   Dockerfile
   Flacarr.py
   flacarr.jpg          # app header logo
   Flacarr.png          # Unraid container icon
   requirements.txt
   ```

3. Edit `docker-compose.yml` if needed:
   - Music library volume (left side = host path)
   - `media` network (must already exist)
   - Icon path: `net.unraid.docker.icon`

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

4. Start:
   ```bash
   cd /mnt/user/appdata/flacarr
   docker compose up -d --build
   ```

   Or use **Compose Manager Plus**: Add Stack → Indirect Path → `/mnt/user/appdata/flacarr` → Compose Up.

5. Open:
   ```text
   http://YOUR-UNRAID-IP:10069
   ```

### Useful commands
```bash
docker compose logs -f          # follow logs
docker compose down             # stop
docker compose up -d --build    # rebuild after code changes
docker compose up -d --force-recreate   # recreate (e.g. after label/icon changes)
```

---

## Local run (without Docker)

Install system tools (`flac`, `rsgain`) yourself, then:

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

## Recommended Linux Workflow

Designed for a Lidarr + Navidrome library on Unraid / CachyOS (or any Linux host).  
All rips end as **FLAC compression level 8** with album + track ReplayGain.

1. **Whipper** – accurate CD rip  
   - Output: FLAC at compression level 5 (fast rip; level 8 is deferred)  
   - Uses MusicBrainz for initial metadata  
   - Place the resulting album folder into the Lidarr-watched music root (or a holding area)

2. **Flacarr** (this app – GUI on port 10069)  
   - Preferred: open the **Full Process** tab → Dry Run first, then run for real  
     (automatically chains Encode → Rename / Organize → Gain)  
   - Or run the three tabs individually:  
     1. **Encode** → re-encode every FLAC to level 8 (lossless, in-place; skip already-marked files)  
     2. **Rename / Organize** → dry-run first, then apply: ensure multi-disc albums use `CD 01` / `CD 02` folders and single-disc albums have none (preserves Lidarr-style folder names)  
     3. **Gain** → write album + track ReplayGain tags via `rsgain` (tag-only; optional skip if tags already present)

3. **Lidarr**  
   - Check / import the album  
   - Run its own rename if desired (Flacarr’s rename is deliberately minimal so Lidarr remains the source of truth for artist/album naming)

4. **MusicBrainz Picard**  
   - Final metadata polish + embedded album art  
   - Picard is fully compatible with the files after Whipper + Flacarr (Vorbis comments preserved; non-standard ID3v2 tags already stripped by Encode)

**Result:** Navidrome-ready library with consistent level-8 FLACs, proper multi-disc layout, ReplayGain, and clean tags/art.

> Tip: Always start with **Dry Run** (especially the Full Process tab) the first time you process a large artist or the entire library.

---

## Notes

- **Encode** is lossless. Re-encoding level 8 → level 8 is safe.
- After a successful encode, Flacarr stores `flacarr_level=8` so skips can work on later runs.
- **Rename** is intentionally conservative so Lidarr naming (`Rolling Stones, The`, title case, years) is not overwritten from tags.
- **Gain** depends on album-per-folder layout (normal for Lidarr libraries).
- Always prefer **Dry Run** the first time you use Rename or Gain on a large scope.
