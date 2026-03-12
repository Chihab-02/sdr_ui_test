#!/usr/bin/env python3
"""Continuous tone transmitter via USRP B210. Runs until SIGTERM/SIGINT."""

import signal
import sys
import numpy as np
import uhd

from config import CENTER_FREQ, SAMPLE_RATE, TONE_OFFSET, TX_GAIN

RUNNING = True


def stop(sig, frame):
    global RUNNING
    RUNNING = False


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    usrp = uhd.usrp.MultiUSRP()
    usrp.set_tx_rate(SAMPLE_RATE)
    usrp.set_tx_freq(uhd.libpyuhd.types.tune_request(CENTER_FREQ))
    usrp.set_tx_gain(TX_GAIN)

    print(f"[TX] Freq={CENTER_FREQ/1e6:.1f} MHz  Tone={TONE_OFFSET/1e3:.0f} kHz  "
          f"Gain={TX_GAIN}  Rate={SAMPLE_RATE/1e6:.1f} MS/s")

    chunk = 4096
    t = np.arange(chunk) / SAMPLE_RATE
    tone = (0.8 * np.exp(2j * np.pi * TONE_OFFSET * t)).astype(np.complex64)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    streamer = usrp.get_tx_stream(st_args)
    metadata = uhd.types.TXMetadata()

    print("[TX] Streaming (Ctrl+C to stop) ...")
    sys.stdout.flush()

    while RUNNING:
        streamer.send(tone, metadata)

    metadata.end_of_burst = True
    streamer.send(np.zeros(chunk, dtype=np.complex64), metadata)
    print("[TX] Stopped.")


if __name__ == "__main__":
    main()
