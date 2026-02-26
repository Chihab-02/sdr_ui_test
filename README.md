# SDR UI Test — B210 Antenna Tester

Transmit a burst waveform from one USRP B210 and receive it on two channels of another B210 to test two antennas simultaneously.

## Hardware Setup

- **TX device** — USRP B210 (serial configured in `config.py` as `TX_DEVICE_ARGS`)
- **RX device** — USRP B210 (serial configured in `config.py` as `RX_DEVICE_ARGS`)
  - Channel 0 (`RX2` port) → Antenna 1
  - Channel 1 (`RX2` port) → Antenna 2

## How It Works

1. The transmitter generates a shaped burst IQ waveform (RRC-filtered QPSK) and streams it continuously on a single frequency.
2. The receiver captures samples on both RX channels simultaneously.
3. The UI tracks the **max received power** (dBFS) on each antenna over a configurable test window (default 15 s).
4. Each antenna has its own pass threshold. If the max power meets the threshold, it gets a green checkmark. If the timer runs out without passing, it gets a red cross.
5. If both antennas pass early, streaming stops immediately.

## Configuration

Edit `config.py` to change:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `TX_DEVICE_ARGS` | `serial=000000503` | TX USRP serial |
| `RX_DEVICE_ARGS` | `serial=2601247` | RX USRP serial |
| `center_freq_hz` | 910 MHz | Transmit/receive frequency |
| `tx_gain_db` | 70 dB | TX gain |
| `rx_gain_db` | 30 dB | RX gain |
| `antenna1_threshold_dbfs` | -30 dBFS | Antenna 1 pass threshold |
| `antenna2_threshold_dbfs` | -40 dBFS | Antenna 2 pass threshold |
| `test_duration_s` | 15 s | Test timeout |

## Requirements

- Python 3.8+
- UHD Python API (`uhd`)
- NumPy
- Tkinter (included with most Python installations)

## Install

```bash
pip install -r requirements.txt
```

> **Note:** The `uhd` Python package requires the UHD driver to be installed on your system. See [Ettus UHD installation](https://files.ettus.com/manual/page_install.html).

## Run

```bash
python ui.py
```

## Project Structure

| File | Purpose |
|------|---------|
| `ui.py` | Tkinter GUI — test button, power readouts, pass/fail |
| `transmitter.py` | TX streaming loop using UHD |
| `receiver.py` | Dual-channel RX streaming using UHD |
| `signal_gen.py` | IQ waveform generation (RRC-shaped QPSK bursts) |
| `config.py` | All parameters and device serials |
