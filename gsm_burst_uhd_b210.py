#!/usr/bin/env python3
# GSM-like bursty signal emulator for UHD USRP B210 (not standards-compliant)

import time
from dataclasses import dataclass
import numpy as np

try:
    import uhd  # UHD Python API
except Exception:
    uhd = None


@dataclass
class Params:
    # Frequencies
    center_freq_hz_a: float = 910e6
    center_freq_hz_b: float = 915e6

    # Sample/shape
    sample_rate: float = 1e6
    symbol_rate: float = 100e3
    rrc_beta: float = 0.35
    rrc_span_symbols: int = 8

    # Burst behavior
    # If you want ms-scale random on/off, use the random burst model below.
    burst_duration_s: float = 0.050
    burst_period_s: float = 0.200
    burst_jitter_s: float = 0.010

    # Random burst model (ms-scale) - enabled by default
    use_random_bursts: bool = True
    on_duration_min_s: float = 0.080
    on_duration_max_s: float = 0.200
    off_duration_min_s: float = 0.050
    off_duration_max_s: float = 0.120
    ramp_duration_s: float = 0.002

    # Hop behavior
    # Hop model
    use_random_hops: bool = True
    use_fixed_hops: bool = True
    fixed_hops_s: list = None  # e.g. [(2.0, 915e6)] => hop at t=2s
    hop_min_dwell_s: float = 0.5
    hop_max_dwell_s: float = 2.0
    hop_random_choice: bool = True  # True: random A/B each hop; False: toggle
    hop_prob_per_burst: float = 0.2  # used only if use_random_hops=False
    hop_jitter_s: float = 0.3        # used only if use_random_hops=False

    # Hop transient spike (baseband envelope)
    spike_db: float = 6.0
    spike_duration_s: float = 0.002
    settle_tau_s: float = 0.008

    # Between bursts
    use_noise_floor: bool = False
    noise_floor_db: float = -50.0

    # If you cannot retune on-the-fly, enable baseband hop offset
    use_baseband_hop: bool = False
    baseband_hop_offset_hz: float = 10e6

    # Live visualization
    enable_live_plot: bool = True
    plot_fft_size: int = 2048
    plot_update_every_chunks: int = 5
    plot_waterfall_rows: int = 200


def raised_cosine_ramp(n, n_ramp):
    if n_ramp <= 0:
        return np.ones(n)
    # If burst is shorter than 2*ramp, clamp ramp length
    n_ramp = min(n_ramp, n // 2) if n > 1 else 0
    if n_ramp <= 0:
        return np.ones(n)
    ramp = 0.5 * (1 - np.cos(np.pi * np.arange(n_ramp) / n_ramp))
    env = np.ones(n)
    env[:n_ramp] = ramp
    env[-n_ramp:] = ramp[::-1]
    return env


def rrc_taps(beta, sps, span):
    N = span * sps
    t = np.arange(-N / 2, N / 2 + 1) / sps
    taps = np.zeros_like(t, dtype=float)
    for i, ti in enumerate(t):
        if ti == 0.0:
            taps[i] = 1.0 - beta + (4 * beta / np.pi)
        elif abs(ti) == 1 / (4 * beta):
            taps[i] = (beta / np.sqrt(2)) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta)) +
                (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta))
            )
        else:
            taps[i] = (
                np.sin(np.pi * ti * (1 - beta)) +
                4 * beta * ti * np.cos(np.pi * ti * (1 + beta))
            ) / (np.pi * ti * (1 - (4 * beta * ti) ** 2))
    taps /= np.sqrt(np.sum(taps ** 2))
    return taps


def make_burst_schedule(params: Params, total_s: float):
    bursts = []
    t = 0.0
    if params.use_random_bursts:
        while t < total_s:
            on_dur = np.random.uniform(params.on_duration_min_s, params.on_duration_max_s)
            off_dur = np.random.uniform(params.off_duration_min_s, params.off_duration_max_s)
            start = t
            end = min(total_s, t + on_dur)
            if end > start:
                bursts.append((start, end))
            t += on_dur + off_dur
        return bursts

    while t < total_s:
        jitter = np.random.uniform(-params.burst_jitter_s, params.burst_jitter_s)
        start = max(0.0, t + jitter)
        end = start + params.burst_duration_s
        bursts.append((start, end))
        t += params.burst_period_s
    return bursts


def make_hop_schedule(params: Params, total_s: float):
    hops = []
    t = 0.0
    cur = params.center_freq_hz_a

    if params.use_fixed_hops:
        if params.fixed_hops_s is None:
            params.fixed_hops_s = [(2.0, params.center_freq_hz_b)]
        for t_hop, f_hop in params.fixed_hops_s:
            if 0 < t_hop < total_s:
                hops.append((t_hop, f_hop))
        return hops

    if params.use_random_hops:
        while t < total_s:
            dwell = np.random.uniform(params.hop_min_dwell_s, params.hop_max_dwell_s)
            t += dwell
            if t >= total_s:
                break
            if params.hop_random_choice:
                cur = params.center_freq_hz_a if np.random.rand() < 0.5 else params.center_freq_hz_b
            else:
                cur = params.center_freq_hz_b if cur == params.center_freq_hz_a else params.center_freq_hz_a
            hops.append((t, cur))
        return hops

    while t < total_s:
        dwell = params.hop_min_dwell_s + np.random.uniform(0, params.hop_jitter_s)
        t += dwell
        if t >= total_s:
            break
        if np.random.rand() < params.hop_prob_per_burst:
            cur = params.center_freq_hz_b if cur == params.center_freq_hz_a else params.center_freq_hz_a
            hops.append((t, cur))
    return hops


def spike_envelope(n, fs, spike_db, spike_dur, settle_tau):
    t = np.arange(n) / fs
    env = np.ones(n)
    amp = 10 ** (spike_db / 20)
    env[t <= spike_dur] = amp
    idx = t > spike_dur
    env[idx] = 1.0 + (amp - 1.0) * np.exp(-(t[idx] - spike_dur) / settle_tau)
    return env


def generate_burst_iq(params: Params, n_samps: int):
    sps = int(params.sample_rate / params.symbol_rate)
    if sps < 2:
        raise ValueError("Sample rate must be >= 2x symbol rate.")
    n_syms = int(np.ceil(n_samps / sps)) + params.rrc_span_symbols
    syms = (2 * (np.random.randint(0, 2, n_syms) - 0.5) +
            1j * 2 * (np.random.randint(0, 2, n_syms) - 0.5)) / np.sqrt(2)
    up = np.zeros(n_syms * sps, dtype=complex)
    up[::sps] = syms
    taps = rrc_taps(params.rrc_beta, sps, params.rrc_span_symbols)
    shaped = np.convolve(up, taps, mode="same")
    return shaped[:n_samps]


def build_iq_stream(params: Params, total_s: float):
    fs = params.sample_rate
    n_total = int(total_s * fs)
    iq = np.zeros(n_total, dtype=np.complex64)

    bursts = make_burst_schedule(params, total_s)
    hops = make_hop_schedule(params, total_s)

    for (start, end) in bursts:
        i0 = int(start * fs)
        i1 = min(n_total, int(end * fs))
        n = i1 - i0
        if n <= 0:
            continue
        burst_iq = generate_burst_iq(params, n)
        n_ramp = int(params.ramp_duration_s * fs)
        env = raised_cosine_ramp(n, n_ramp)
        iq[i0:i1] += (burst_iq * env).astype(np.complex64)

    if params.use_noise_floor:
        noise_amp = 10 ** (params.noise_floor_db / 20)
        noise = (np.random.randn(n_total) + 1j * np.random.randn(n_total)) / np.sqrt(2)
        iq += (noise_amp * noise).astype(np.complex64)

    return iq, hops


def init_live_plot(params: Params):
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        raise RuntimeError("matplotlib is required for live plotting") from e

    plt.ion()
    fig, (ax_s, ax_f) = plt.subplots(2, 1, figsize=(10, 6))
    fig.suptitle("Live FFT Preview (Spectrum + Waterfall)")

    # Spectrum line
    s_line, = ax_s.plot([], [], lw=1.0)
    ax_s.set_ylabel("Power (dB)")
    ax_s.set_xlabel("FFT bin")

    # Waterfall
    wf = np.zeros((params.plot_waterfall_rows, params.plot_fft_size), dtype=np.float32)
    im = ax_f.imshow(
        wf,
        aspect="auto",
        origin="lower",
        interpolation="nearest"
    )
    ax_f.set_ylabel("Time")
    ax_f.set_xlabel("FFT bin")
    plt.tight_layout()
    return fig, ax_s, ax_f, s_line, im, wf


def update_live_plot(params: Params, s_line, im, wf, samples):
    import numpy as np

    # FFT -> power (dB)
    nfft = params.plot_fft_size
    if len(samples) < nfft:
        pad = np.zeros(nfft - len(samples), dtype=samples.dtype)
        x = np.concatenate([samples, pad])
    else:
        x = samples[:nfft]
    window = np.hanning(len(x))
    spec = np.fft.fftshift(np.fft.fft(x * window, nfft))
    pwr = 20 * np.log10(np.maximum(np.abs(spec), 1e-12))

    # Spectrum line
    s_line.set_data(np.arange(len(pwr)), pwr)
    s_line.axes.set_xlim(0, len(pwr))

    # Update waterfall
    wf[:-1, :] = wf[1:, :]
    wf[-1, :] = pwr
    im.set_data(wf)
    im.set_clim(vmin=np.percentile(wf, 10), vmax=np.percentile(wf, 99))


def transmit_uhd_b210(samples, center_freq_hz, sample_rate, tx_gain_db):
    if uhd is None:
        raise RuntimeError("UHD Python API not available. Install uhd-python or use your own TX wrapper.")

    usrp = uhd.usrp.MultiUSRP()
    usrp.set_tx_rate(sample_rate, 0)
    usrp.set_tx_freq(center_freq_hz, 0)
    usrp.set_tx_gain(tx_gain_db, 0)
    usrp.set_tx_antenna("TX/RX", 0)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [0]
    tx_streamer = usrp.get_tx_stream(st_args)

    md = uhd.types.TXMetadata()
    md.start_of_burst = True
    md.end_of_burst = False

    spb = tx_streamer.get_max_num_samps()
    for i in range(0, len(samples), spb):
        chunk = samples[i:i + spb]
        tx_streamer.send(chunk, md)
        md.start_of_burst = False

    md.end_of_burst = True
    tx_streamer.send(np.zeros(1, dtype=np.complex64), md)


def run(params: Params, total_s: float = 12.0, tx_gain_db: float = 0.0, stop_event=None):
    fs = params.sample_rate
    iq, hops = build_iq_stream(params, total_s)

    # Apply baseband hop spike envelope
    for t_hop, _new_f in hops:
        idx = int(t_hop * fs)
        spike_n = int((params.spike_duration_s + 5 * params.settle_tau_s) * fs)
        spike_n = min(spike_n, len(iq) - idx)
        if spike_n > 0:
            env = spike_envelope(spike_n, fs, params.spike_db,
                                 params.spike_duration_s, params.settle_tau_s)
            iq[idx:idx + spike_n] *= env.astype(np.float32)

    # Stream and retune on hop boundaries
    cur_freq = params.center_freq_hz_a
    hop_iter = iter(sorted(hops, key=lambda x: x[0]))
    next_hop = next(hop_iter, None)

    if uhd is None:
        raise RuntimeError("UHD Python API not available. Install uhd-python to transmit.")

    usrp = uhd.usrp.MultiUSRP()
    usrp.set_tx_rate(fs, 0)
    usrp.set_tx_freq(cur_freq, 0)
    usrp.set_tx_gain(tx_gain_db, 0)
    usrp.set_tx_antenna("TX/RX", 0)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [0]
    tx_streamer = usrp.get_tx_stream(st_args)

    md = uhd.types.TXMetadata()
    md.start_of_burst = True
    md.end_of_burst = False

    spb = tx_streamer.get_max_num_samps()
    if params.enable_live_plot:
        fig, ax_s, ax_f, s_line, im, wf = init_live_plot(params)
        chunk_count = 0
    for i in range(0, len(iq), spb):
        t = i / fs
        if next_hop and t >= next_hop[0]:
            cur_freq = next_hop[1]
            usrp.set_tx_freq(cur_freq, 0)
            next_hop = next(hop_iter, None)

        chunk = iq[i:i + spb]
        if params.use_baseband_hop and cur_freq == params.center_freq_hz_b:
            n = len(chunk)
            tvec = (np.arange(n) + i) / fs
            offset = np.exp(1j * 2 * np.pi * params.baseband_hop_offset_hz * tvec)
            chunk = (chunk * offset).astype(np.complex64)

        if stop_event and stop_event.is_set():
            break

        if params.enable_live_plot:
            if (chunk_count % params.plot_update_every_chunks) == 0:
                update_live_plot(params, s_line, im, wf, chunk)
                import matplotlib.pyplot as plt
                plt.pause(0.001)
            chunk_count += 1

        tx_streamer.send(chunk, md)
        md.start_of_burst = False

    md.end_of_burst = True
    tx_streamer.send(np.zeros(1, dtype=np.complex64), md)


if __name__ == "__main__":
    p = Params()
    run(p, total_s=12.0, tx_gain_db=50.0)
