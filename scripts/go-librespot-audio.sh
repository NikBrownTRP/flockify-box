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
#
# Filter chain:
#   alimiter: true-peak limiter at -1.5 dBFS (same ceiling as mpv's
#             loudnorm TP=-1.5). No lookahead buffer, instant processing.
#   volume=-3dB: small headroom reduction to further prevent DAC/amp
#             inter-sample peak clipping.
#
# Output via pacat (PulseAudio pipe player) instead of ffmpeg's -f pulse
# which has buffering issues on PipeWire.
while true; do
    ffmpeg -hide_banner -loglevel warning \
        -f "$FORMAT" -ar "$SAMPLE_RATE" -ac "$CHANNELS" -i "$PIPE" \
        -af "alimiter=limit=0.85:attack=0.1:release=50:level=false,volume=-3dB" \
        -f s16le -ar "$SAMPLE_RATE" -ac "$CHANNELS" pipe:1 2>/dev/null \
    | pacat --format=s16le --rate="$SAMPLE_RATE" --channels="$CHANNELS" \
            --stream-name="go-librespot" --latency-msec=100

    echo "[go-librespot-audio] pipe closed, restarting in 1s..."
    sleep 1
done
