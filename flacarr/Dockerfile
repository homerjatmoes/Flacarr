FROM python:3.12-slim

# flac + rsgain from Debian repos (available on Trixie / python:3.12-slim)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        flac \
        rsgain \
        && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY Flacarr.py .
COPY flacarr.jpg .

EXPOSE 10069

# primaryColor green = selected tab underline + default accents
CMD ["streamlit", "run", "Flacarr.py", \
     "--server.port=10069", \
     "--server.address=0.0.0.0", \
     "--theme.base=dark", \
     "--theme.primaryColor=#3fb950", \
     "--client.toolbarMode=minimal", \
     "--browser.gatherUsageStats=false"]
