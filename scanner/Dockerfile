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

COPY requirements.txt requirements.lock ./
# Install from the LOCK. The .txt is kept for humans to read; the lock is
# what builds, so every user gets identical bytes. An upgrade here does
# not break the lab -- it silently repairs the vulnerability being taught.
RUN pip install --no-cache-dir -r requirements.lock

# ---------------------------------------------------------------------------
# TWO picklescan versions, in separate venvs.
#
#   old = 0.0.15  exercise 4's truncation AND 7z bypasses both work (fail-open)
#   new = 1.0.5   both are caught — what /scan/upgrade switches to
#
# Measured, not guessed. See app.py for the matrix. PINNED HARD: exercise 4 is
# entirely a story about the difference between these two releases, and a
# floating version would silently delete the lesson.
# ---------------------------------------------------------------------------
RUN python -m venv /opt/ps-old && /opt/ps-old/bin/pip install --no-cache-dir picklescan==0.0.15 \
 && python -m venv /opt/ps-new && /opt/ps-new/bin/pip install --no-cache-dir picklescan==1.0.5 py7zr

# py7zr goes in the NEW venv only. picklescan 1.0.5 needs it to open a 7z
# archive; without it the scan raises and exercise 4 route B comes back
# "not_scanned" instead of "flagged", which loses the whole point of the
# upgrade. Deliberately NOT installed in ps-old: 0.0.15 has no 7z support at
# all, and that absence IS route B's bypass.

COPY runner.py /opt/runner.py
COPY app.py .
EXPOSE 8004
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004"]
