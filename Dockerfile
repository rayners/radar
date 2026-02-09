# Multi-stage build for Radar
# Build args:
#   LOCAL_EMBEDDINGS=true  - Include sentence-transformers (~500MB larger)
#   RSS_READER=true        - Include feedparser for RSS/Atom feed reader

ARG LOCAL_EMBEDDINGS=false
ARG RSS_READER=false

# =============================================================================
# Stage 1: Builder - Build the wheel from source
# =============================================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN pip install --no-cache-dir build

# Copy source files needed for build
COPY pyproject.toml README.md ./
COPY radar/ ./radar/

# Build the wheel
RUN python -m build --wheel --outdir /build/dist

# =============================================================================
# Stage 2: Runtime - Minimal production image
# =============================================================================
FROM python:3.11-slim AS runtime

ARG LOCAL_EMBEDDINGS
ARG RSS_READER

# Install runtime dependencies
# - curl: healthcheck
# - gh: GitHub CLI for GitHub integration
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --uid 1000 --shell /bin/bash radar

# Create data directories with correct ownership
RUN mkdir -p /home/radar/.local/share/radar \
             /home/radar/.config/radar \
             /home/radar/.config/khal \
             /home/radar/.config/vdirsyncer \
             /workspace \
    && chown -R radar:radar /home/radar /workspace

# Switch to non-root user
USER radar
WORKDIR /home/radar

# Copy wheel with correct ownership and install
COPY --from=builder --chown=radar:radar /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir --user /tmp/*.whl \
    && rm /tmp/*.whl

# Install khal + vdirsyncer for calendar integration
RUN pip install --no-cache-dir --user khal vdirsyncer

# Conditionally install local embeddings support
RUN if [ "$LOCAL_EMBEDDINGS" = "true" ]; then \
        pip install --no-cache-dir --user sentence-transformers>=2.2; \
    fi

# Conditionally install RSS/Atom feed reader support
RUN if [ "$RSS_READER" = "true" ]; then \
        pip install --no-cache-dir --user "feedparser>=6.0"; \
    fi

# Ensure user's pip bin is in PATH
ENV PATH="/home/radar/.local/bin:${PATH}"

# Expose web UI port
EXPOSE 8420

# Health check (allow 403 for auth-required scenarios)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -s -o /dev/null -w "%{http_code}" http://localhost:8420/ | grep -qE "^(200|403)$" || exit 1

# Default command: start daemon (web UI + scheduler)
CMD ["radar", "start", "-h", "0.0.0.0"]
