"""Pure-numpy signal generation -- no hardware dependencies."""

import numpy as np
from config import Params


def raised_cosine_ramp(n, n_ramp):
    if n_ramp <= 0:
        return np.ones(n)
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
    """Generate the full IQ stream (pure numpy)."""
    fs = params.sample_rate
    n_total = int(total_s * fs)
    iq = np.zeros(n_total, dtype=np.complex64)

    bursts = make_burst_schedule(params, total_s)

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

    return iq
