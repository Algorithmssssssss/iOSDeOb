FROM python:3.12-slim

ENV HOME=/tmp
WORKDIR /app

# Pinned radare2 release (Debian's packaged version is stale). radare2
# publishes its .deb releases per-arch as amd64/arm64, which matches
# Docker's own TARGETARCH naming — so this picks the right one whether
# building on Apple Silicon (arm64) or a Linux amd64 host/CI runner.
ARG TARGETARCH
ARG R2_VERSION=6.2.2
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -sL -o /tmp/radare2.deb "https://github.com/radareorg/radare2/releases/download/${R2_VERSION}/radare2_${R2_VERSION}_${TARGETARCH}.deb" && \
    apt-get install -y --no-install-recommends /tmp/radare2.deb && \
    rm /tmp/radare2.deb && \
    apt-get purge -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# r2ghidra: exposes Ghidra's actual decompiler (a native C++ core, no JVM
# involved) as radare2's `pdg` command — built from source via r2pm since
# there's no prebuilt arm64 package. Confirmed against Debian bookworm: the
# plain `radare2` .deb ships no pkg-config files, so r2ghidra's build can't
# find libradare2 without also installing `radare2-dev` (which has them).
# Both the plugin (~17MB) and its sleigh processor-spec data (~13MB) default
# to installing under $HOME — but $HOME is /tmp here, which is tmpfs-mounted
# fresh at container runtime and would silently swallow them — so we install
# to r2's own system plugin dir instead, which is a normal image layer.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential cmake pkg-config unzip curl ca-certificates && \
    curl -sL -o /tmp/radare2-dev.deb "https://github.com/radareorg/radare2/releases/download/${R2_VERSION}/radare2-dev_${R2_VERSION}_${TARGETARCH}.deb" && \
    apt-get install -y --no-install-recommends /tmp/radare2-dev.deb && \
    rm /tmp/radare2-dev.deb && \
    HOME=/root r2pm -U && \
    HOME=/root r2pm -ci r2ghidra && \
    HOME=/root r2pm -ci r2ghidra-sleigh && \
    R2_PLUGDIR="$(r2 -H R2_LIBR_PLUGINS)" && \
    mv /root/.local/share/radare2/plugins/core_ghidra.so "$R2_PLUGDIR/" && \
    mv /root/.local/share/radare2/plugins/r2ghidra_sleigh "$R2_PLUGDIR/r2ghidra_sleigh" && \
    apt-get purge -y git build-essential cmake pkg-config unzip curl radare2-dev && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /root/.local/share/radare2

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker ./worker

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=INFO", "--concurrency=1"]
