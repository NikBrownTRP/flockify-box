#!/bin/bash
# go-librespot audio pipe — feeds raw PCM from go-librespot through
# ffmpeg's loudnorm filter (EBU R128, TP=-1.5 true-peak limiter) before
# sending to PipeWire. This eliminates the "overdriven" sound that
# go-librespot's direct ALSA/PulseAudio output produces.
#
# go-librespot writes raw f32le 44100Hz stereo to the named pipe.
# ffmpeg reads it, applies loudnorm, and outputs via PulseAudio to
# the default PipeWire sink.
#
# Run by go-librespot-audio.service, started before go-librespot.service.

set -euo pipefail

PIPE="/tmp/go-librespot-audio"
SAMPLE_RATE=44100
CHANNELS=2
FORMAT="f32le"

# Create the named pipe if it doesn't exist
[ -p "$PIPE" ] || mkfifo "$PIPE"

echo "[go-librespot-audio] Waiting for audio on $PIPE..."

# Loop forever — ffmpeg exits when go-librespot restarts (pipe closes),
# so we restart it automatically.
while true; do
    ffmpeg -hide_banner -loglevel warning \
        -f "$FORMAT" -ar "$SAMPLE_RATE" -ac "$CHANNELS" -i "$PIPE" \
        -af "loudnorm=I=-16:TP=-1.5:LRA=11,volume=1.0" \
        -f pulse -device default \
        -buffer_size 4096 \
        "go-librespot" \
        2>&1 | while read -r line; do echo "[go-librespot-audio] $line"; done

    echo "[go-librespot-audio] ffmpeg exited, restarting in 1s..."
    sleep 1
done
