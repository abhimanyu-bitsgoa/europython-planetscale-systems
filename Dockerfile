FROM ubuntu:24.04

# Avoid interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive

# Install System Tools + Python
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    make \
    dos2unix \
    curl \
    htop \
    procps \
    iproute2 \
    git \
    nano \
    vim \
    tmux \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 ships the C.UTF-8 locale built in (no `locales` package needed).
# Without a UTF-8 locale, terminals/Python fall back to ASCII and render the
# incident banners' ❌/✅/— as "_". This makes every shell UTF-8 by default.
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Symlink python to python3 for convenience
RUN ln -s /usr/bin/python3 /usr/bin/python

# Create Virtual Environment at /opt/venv
RUN python3 -m venv /opt/venv

# Activate venv globally by updating PATH
# This ensures every terminal session uses the venv by default
ENV PATH="/opt/venv/bin:$PATH"

# Install Python Workshop Libraries into the venv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /workspace

# Keep container running
CMD ["tail", "-f", "/dev/null"]
