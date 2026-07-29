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
- Uses the same scope as Encode / Rename

---

### History tabs
| Tab | Contents |
|-----|----------|
| **Encode History** | Last 300 encode results (newest first) |
| **Rename History** | Last 300 rename / dry-run results |
| **Gain History** | Last 300 gain / dry-run results |

Each history tab supports **Download Log** and **Clear History**.

History is kept in the **browser session** (cleared on refresh or container restart unless downloaded).

---

### UI
- Dark theme only (no light mode)
- Streamlit chrome / theme picker hidden
- Green primary actions (Start Encoding, Start Rename, Start Gain Scan, Confirm)
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

## Notes

- **Encode** is lossless. Re-encoding level 8 → level 8 is safe.
- After a successful encode, Flacarr stores `flacarr_level=8` so skips can work on later runs.
- **Rename** is intentionally conservative so Lidarr naming (`Rolling Stones, The`, title case, years) is not overwritten from tags.
- **Gain** depends on album-per-folder layout (normal for Lidarr libraries).
- Always prefer **Dry Run** the first time you use Rename or Gain on a large scope.
