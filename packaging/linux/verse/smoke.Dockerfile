# Container of the nightly Linux smoke of the Unreal Verse
# (docs/verse/unreal/work-packages.md WP22.7, scripts/unreal/package.py linux-smoke).
# The packaged build is mounted read-only at /verse, this folder at /smoke and
# the result folder at /out; the run itself has no network.
FROM ubuntu:24.04
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates libvulkan1 mesa-vulkan-drivers vulkan-tools \
      xvfb x11-utils openbox weston wayland-utils python3 procps coreutils \
 && rm -rf /var/lib/apt/lists/*
# The engine refuses to run as root.
RUN useradd --create-home --uid 1001 verse
USER verse
WORKDIR /home/verse
