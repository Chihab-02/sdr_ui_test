#!/usr/bin/env python3
"""
Continuous receiver via USRP B210.
Captures in chunks, runs FFT analysis, writes JSON results to stdout.
Runs until SIGTERM/SIGINT.
"""

import json
import signal
import sys
import numpy as np
import uhd

from config import (CENTER_FREQ, SAMPLE_RATE, TONE_OFFSET, RX_GAIN,
                    TONE_SNR_MIN_DB, FREQ_TOLERANCE_HZ)

RUNNING = True
ANALYSIS_SAMPLES = 65536


def stop(sig, frame):
    global RUNNING
    RUNNING = False


def analyze(samples):
    N = len(samples)
    window = np.hanning(N)
    spectrum = np.fft.fftshift(np.fft.fft(samples * window))
    magnitude = 20 * np.log10(np.abs(spectrum) + 1e-12)
    freqs = np.fft.fftshift(np.fft.fftfreq(N, 1.0 / SAMPLE_RATE))

    peak_idx = np.argmax(magnitude)
    peak_freq = freqs[peak_idx]
    peak_power = magnitude[peak_idx]

    noise_mask = np.ones(N, dtype=bool)
    guard = int(N * FREQ_TOLERANCE_HZ / SAMPLE_RATE) * 2
    lo = max(0, peak_idx - guard)
    hi = min(N, peak_idx + guard)
    noise_mask[lo:hi] = False
    noise_floor = np.mean(magnitude[noise_mask])

    snr_db = peak_power - noise_floor
    freq_error = abs(peak_freq - TONE_OFFSET)
    tone_ok = snr_db >= TONE_SNR_MIN_DB and freq_error <= FREQ_TOLERANCE_HZ

    return {
        "status": "PASS" if tone_ok else "FAIL",
        "peak_freq_hz": round(float(peak_freq), 1),
        "expected_freq_hz": float(TONE_OFFSET),
        "freq_error_hz": round(float(freq_error), 1),
        "snr_db": round(float(snr_db), 2),
        "snr_threshold_db": float(TONE_SNR_MIN_DB),
        "peak_power_db": round(float(peak_power), 2),
        "noise_floor_db": round(float(noise_floor), 2),
    }


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    usrp = uhd.usrp.MultiUSRP()
    usrp.set_rx_rate(SAMPLE_RATE)
    usrp.set_rx_freq(uhd.libpyuhd.types.tune_request(CENTER_FREQ))
    usrp.set_rx_gain(RX_GAIN)

    print(f"[RX] Freq={CENTER_FREQ/1e6:.1f} MHz  Gain={RX_GAIN}  "
          f"Rate={SAMPLE_RATE/1e6:.1f} MS/s", file=sys.stderr)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    streamer = usrp.get_rx_stream(st_args)
    metadata = uhd.types.RXMetadata()

    stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
    stream_cmd.stream_now = True
    streamer.issue_stream_cmd(stream_cmd)

    chunk_size = streamer.get_max_num_samps()
    ring = np.zeros(ANALYSIS_SAMPLES, dtype=np.complex64)
    ring_pos = 0

    print("[RX] Streaming (Ctrl+C to stop) ...", file=sys.stderr)
    sys.stderr.flush()

    while RUNNING:
        buf = np.zeros(chunk_size, dtype=np.complex64)
        nrecv = streamer.recv(buf, metadata)
        if metadata.error_code == uhd.types.RXMetadataErrorCode.overflow:
            continue
        if metadata.error_code != uhd.types.RXMetadataErrorCode.none:
            print(f"[RX] Error: {metadata.error_code}", file=sys.stderr)
            continue

        for i in range(nrecv):
            ring[ring_pos % ANALYSIS_SAMPLES] = buf[i]
            ring_pos += 1

    stop_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
    streamer.issue_stream_cmd(stop_cmd)

    print(f"[RX] Stopped. Total samples: {ring_pos}", file=sys.stderr)

    if ring_pos >= ANALYSIS_SAMPLES:
        ordered = np.roll(ring, -(ring_pos % ANALYSIS_SAMPLES))
        result = analyze(ordered)
    elif ring_pos > 0:
        result = analyze(ring[:ring_pos])
    else:
        result = {"status": "FAIL", "error": "No samples captured"}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
