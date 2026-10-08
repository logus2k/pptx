# The AI Slide Assistant: one process serving the REST API, socket.io and the frontend (technical design section 1).
#   docker compose build      (builds the base image first when it is missing)
#   docker compose up -d      -> http://localhost:2720 (through the proxy: https://logus2k.com/slides/)
ARG BASE_IMAGE=slides-base:lo-2
FROM ${BASE_IMAGE} AS app

WORKDIR /slides
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY contracts ./contracts
# the names templates use for fonts installed under other names (the fonts themselves are mounted: docs/licenses.md)
COPY config/fonts.conf /etc/fonts/conf.d/60-slides.conf

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/slides/backend \
    SLIDES_PORT=2720 \
    SLIDES_DATA_DIR=/slides/data \
    SLIDES_CONFIG_FILE=/slides/config/config.json

# not root (security review L4): uid/gid 1000, the host account that owns ./data, so files stay manageable from the host;
# its own home for LibreOffice's profile
RUN groupadd -g 1000 slides && useradd -u 1000 -g 1000 -m -d /home/slides slides
USER slides

EXPOSE 2720
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:2720/api/health', timeout=4).status == 200 else 1)"

CMD ["python", "-u", "-m", "app"]

# The tests, in the image they test (make check): LibreOffice with Impress is here, so slide rendering is tested for real.
#   docker build --target test -t slides-test . && docker run --rm slides-test
FROM app AS test
USER root
COPY requirements-dev.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY config ./config
COPY templates ./templates
COPY fixtures ./fixtures
USER slides
# (no pytest cache: /slides is not the unprivileged user's to write)
ENV PYTEST_ADDOPTS="-p no:cacheprovider"
CMD ["python", "-m", "pytest", "-q", "-rs"]
