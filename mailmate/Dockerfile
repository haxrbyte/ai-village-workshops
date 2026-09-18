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
# Install from the LOCK, not requirements.txt. The .txt is deliberately loose
# (fastapi>=0.115), so any rebuild resolves whatever PyPI serves that day —
# the same failure class as the floating jupyterhub:5 tag that silently broke
# every spawn. requirements.txt is kept for a human reading intent; the lock is
# what actually gets installed. Regenerate with `make freeze`.
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app.py tools.py canned.py ./
COPY static/ ./static/
EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
