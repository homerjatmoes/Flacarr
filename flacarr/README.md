# Flacarr

Simple web tool for FLAC libraries. Runs on port **10069**.

## Features

### Encode (Level 8)
- Convert all FLAC files to compression level 8 (in-place, recursive)
- Preserves bit depth (16-bit and 24-bit)
- Ignores MP3 and other non-FLAC files
- Option to **skip files already marked as level 8**
- Downloadable log

### Rename / Organize
- Conditional naming:
  - Single-disc → `Artist/Album (Year)/01 - Track.flac`
  - Multi-disc → `Artist/Album (Year)/CD 01/01 - Track.flac`
- Dry-run / preview mode
- Downloadable log

### UI
- Dark theme
- Progress bars and live logs

## Run with Docker Compose (Unraid)

1. Copy the whole `Flacarr` folder to your Unraid server (e.g. `/mnt/user/appdata/flacarr`).

2. Edit `docker-compose.yml` if your music path is different:
   ```yaml
   volumes:
     - /mnt/user/Media/Music:/mnt/user/Media/Music
   ```

3. Start it:
   ```bash
   cd /mnt/user/appdata/flacarr
   docker compose up -d --build
   ```

4. Open in your browser:
   ```
   http://YOUR-UNRAID-IP:10069
   ```

5. In the Flacarr sidebar, enter the path **as seen inside the container**  
   (usually `/mnt/user/Media/Music`).

### Useful commands

```bash
# Stop
docker compose down

# View logs
docker compose logs -f

# Rebuild after code changes
docker compose up -d --build
```

## Local run (without Docker)

```bash
pip install -r requirements.txt
streamlit run Flacarr.py --server.port 10069 --server.address 0.0.0.0
```

## Notes

- After a successful encode, Flacarr writes a small tag (`flacarr_level=8`) so future runs can skip those files.
- Re-encoding is lossless. Level 8 → level 8 is safe and fast.
