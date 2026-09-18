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
# curl is here because attendee payloads commonly shell out to it.
# Leaving it in is deliberate: a stripped image would make exercise 1 fail for
# reasons that have nothing to do with the lesson.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
# Install from the LOCK — requirements.txt is deliberately loose and a
# rebuild would otherwise resolve whatever PyPI serves that day.
COPY requirements.txt requirements.lock ./
# The lock has no index directives, but torch here must come from the CPU wheel
# index (requirements.txt carries that). Installing the lock without these flags
# fails outright — so the pins come from the lock, the indexes from the .txt.
RUN pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      --extra-index-url https://pypi.org/simple \
      -r requirements.lock
COPY bot.py .
EXPOSE 8006
CMD ["python", "-u", "bot.py"]
