"""Transmit IQ stream through a USRP B210."""

import numpy as np

try:
    import uhd
except Exception:
    uhd = None

from config import Params, TX_DEVICE_ARGS
from signal_gen import build_iq_stream


def transmit(params: Params, stop_event=None, log=None, on_tx_power=None):
    """
    Build the IQ waveform and stream it continuously until stopped.

    Parameters
    ----------
    params      : Params  – signal / RF configuration
    stop_event  : threading.Event, optional – set to abort early
    log         : callable(str), optional – status callback
    on_tx_power : callable(float), optional – called with TX power in dBFS
    """
    if uhd is None:
        raise RuntimeError("UHD Python API not available.")

    def _log(msg):
        if log:
            log(msg)

    _log("Generating IQ waveform ...")
    iq = build_iq_stream(params, params.total_s)

    fs = params.sample_rate

    _log(f"Opening TX device ({TX_DEVICE_ARGS}) ...")
    usrp = uhd.usrp.MultiUSRP(TX_DEVICE_ARGS)
    usrp.set_tx_rate(fs, 0)
    usrp.set_tx_freq(params.center_freq_hz, 0)
    usrp.set_tx_gain(params.tx_gain_db, 0)
    usrp.set_tx_antenna("TX/RX", 0)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [0]
    tx_streamer = usrp.get_tx_stream(st_args)

    md = uhd.types.TXMetadata()
    md.start_of_burst = True
    md.end_of_burst = False

    spb = tx_streamer.get_max_num_samps()
    _log("Transmitting (loops until stopped) ...")

    try:
        while not (stop_event and stop_event.is_set()):
            for i in range(0, len(iq), spb):
                if stop_event and stop_event.is_set():
                    break

                chunk = iq[i:i + spb]
                tx_streamer.send(chunk, md)
                md.start_of_burst = False

                if on_tx_power and len(chunk) > 0:
                    mean_power = np.mean(np.abs(chunk) ** 2)
                    if mean_power > 0:
                        power_dbfs = 10 * np.log10(mean_power)
                        on_tx_power(power_dbfs)
    finally:
        md.end_of_burst = True
        tx_streamer.send(np.zeros(1, dtype=np.complex64), md)
        _log("TX done.")
