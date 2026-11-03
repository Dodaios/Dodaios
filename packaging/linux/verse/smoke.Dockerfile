# Container of the nightly Linux smoke of the Unreal Verse
# (docs/verse/unreal/work-packages.md WP22.7, scripts/unreal/package.py linux-smoke).
# The packaged build is mounted read-only at /verse, this folder at /smoke and
# the result folder at /out, and scripts/ plus the bridge golden data under
# /repo for the fake bridge; the run itself has no network (loopback only).
FROM ubuntu:24.04
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates libvulkan1 mesa-vulkan-drivers vulkan-tools \
      xvfb x11-utils openbox sway wayland-utils python3 python3-pip procps coreutils \
 && rm -rf /var/lib/apt/lists/* \
 && pip3 install --no-cache-dir --break-system-packages "websockets==16.0" "jsonschema==4.26.0"
# The engine refuses to run as root.
RUN useradd --create-home --uid 1001 verse
USER verse
WORKDIR /home/verse
