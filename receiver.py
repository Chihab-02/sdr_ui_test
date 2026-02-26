"""Receive IQ samples from a USRP B210 on two channels."""

import numpy as np

try:
    import uhd
except Exception:
    uhd = None

from config import Params, RX_DEVICE_ARGS

NUM_RX_CHANNELS = 2


def receive(params: Params, stop_event=None, on_samples=None, log=None):
    """
    Continuously receive IQ samples from both RX channels.

    Parameters
    ----------
    params      : Params
    stop_event  : threading.Event, optional – set to stop receiving
    on_samples  : callable(int, np.ndarray), optional – called with
                  (channel_index, samples) for each chunk per channel
    log         : callable(str), optional – status callback
    """
    if uhd is None:
        raise RuntimeError("UHD Python API not available.")

    def _log(msg):
        if log:
            log(msg)

    fs = params.sample_rate
    center_freq = params.center_freq_hz

    _log(f"Opening RX device ({RX_DEVICE_ARGS}) ...")
    usrp = uhd.usrp.MultiUSRP(RX_DEVICE_ARGS)
    usrp.set_time_now(uhd.types.TimeSpec(0.0))

    rx_antennas = ["RX2", "RX2"]
    for ch in range(NUM_RX_CHANNELS):
        usrp.set_rx_rate(fs, ch)
        usrp.set_rx_freq(center_freq, ch)
        usrp.set_rx_gain(params.rx_gain_db, ch)
        usrp.set_rx_antenna(rx_antennas[ch], ch)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = list(range(NUM_RX_CHANNELS))
    rx_streamer = usrp.get_rx_stream(st_args)

    md = uhd.types.RXMetadata()
    spb = rx_streamer.get_max_num_samps()
    recv_buf = np.zeros((NUM_RX_CHANNELS, spb), dtype=np.complex64)

    stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
    stream_cmd.stream_now = False
    stream_cmd.time_spec = usrp.get_time_now() + uhd.types.TimeSpec(0.2)
    rx_streamer.issue_stream_cmd(stream_cmd)

    _log(f"Receiving on {NUM_RX_CHANNELS} channels ...")
    try:
        while not (stop_event and stop_event.is_set()):
            n_recv = rx_streamer.recv(recv_buf, md, timeout=1.0)
            if md.error_code != uhd.types.RXMetadataErrorCode.none:
                if md.error_code == uhd.types.RXMetadataErrorCode.timeout:
                    continue
                _log(f"RX metadata error: {md.error_code}")
                continue
            if n_recv > 0 and on_samples:
                for ch in range(NUM_RX_CHANNELS):
                    on_samples(ch, recv_buf[ch, :n_recv].copy())
    finally:
        stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
        rx_streamer.issue_stream_cmd(stream_cmd)
        _log("RX done.")
