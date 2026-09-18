# Base pinned by DIGEST at the Sept 5 freeze. The tag is kept so a human
# can see what this is; the digest is what Docker resolves.
#
# This is not bookkeeping. `jupyterhub:5` floated, a rebuild on 19 Aug
# pulled a jupyter-server that exits when run as root, and EVERY notebook
# spawn started failing — silently, with a healthy-looking startup log.
# Gate 5 found it. Nothing else would have.
#
# Refresh with `make freeze`, which reports whether these are still pinned.
FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
WORKDIR /app
# From the LOCK, not the .txt. This service had to be rebuilt on 12 Sept 2026
# for the scoreboard's workshop split, and a rebuild against the loose .txt
# resolves whatever PyPI serves that day — which is the exact risk the freeze
# note warns about. The lock was frozen 25 Aug from a working install.
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY app.py .
COPY static/ ./static/
EXPOSE 8003
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
