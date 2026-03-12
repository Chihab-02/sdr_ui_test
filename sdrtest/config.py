"""
Shared SDR config for B210 TX/RX box validation.

WARNING: Direct coax connection -- keep TX_GAIN low or use a 30dB attenuator
to avoid damaging the B210 RX front-end.
"""

CENTER_FREQ = 884e6
SAMPLE_RATE = 1e6
TONE_OFFSET = 100e3

TX_GAIN = 0
RX_GAIN = 0

DURATION = 2.0

TONE_SNR_MIN_DB = 15.0
FREQ_TOLERANCE_HZ = 5e3

PI_HOST = "192.168.68.87"
PI_USER = "dragon"
PI_WORK_DIR = "/home/pi/sdrtest"

NUM_SAMPLES = int(SAMPLE_RATE * DURATION)
