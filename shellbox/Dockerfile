FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
WORKDIR /app
# Install from the LOCK, not requirements.txt — the .txt is loose on purpose
# and a rebuild would otherwise resolve whatever PyPI serves that day.
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app.py ./
EXPOSE 8007
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8007"]
