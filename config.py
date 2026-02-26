from dataclasses import dataclass, field


# ── Device identifiers ──────────────────────────────────────────────
TX_DEVICE_ARGS = "serial=000000503"   # lutetia  (transmitter)
RX_DEVICE_ARGS = "serial=2601247"     # MyB210   (receiver)


@dataclass
class Params:
    # Frequency
    center_freq_hz: float = 910e6

    # Sample / pulse-shape
    sample_rate: float = 1e6
    symbol_rate: float = 100e3
    rrc_beta: float = 0.35
    rrc_span_symbols: int = 8

    # Burst timing (deterministic model)
    burst_duration_s: float = 0.050
    burst_period_s: float = 0.200
    burst_jitter_s: float = 0.010

    # Random burst model (ms-scale) -- enabled by default
    use_random_bursts: bool = True
    on_duration_min_s: float = 0.080
    on_duration_max_s: float = 0.200
    off_duration_min_s: float = 0.050
    off_duration_max_s: float = 0.120
    ramp_duration_s: float = 0.002

    # Inter-burst noise floor
    use_noise_floor: bool = False
    noise_floor_db: float = -50.0

    # TX / RX gains
    tx_gain_db: float = 70.0
    rx_gain_db: float = 30.0

    # Per-antenna pass thresholds (max power must reach this)
    antenna1_threshold_dbfs: float = -30.0
    antenna2_threshold_dbfs: float = -40.0

    # Test duration (seconds of RX after init)
    test_duration_s: float = 15.0

    # Duration of IQ waveform buffer
    total_s: float = 12.0
