#!/usr/bin/env python3
"""
Box validation orchestrator.
Deploys scripts to the Pi, runs RX remotely and TX locally, collects results.
"""

import json
import os
import subprocess
import sys
import time

from config import PI_HOST, PI_USER, PI_WORK_DIR, DURATION


SCRIPTS_TO_DEPLOY = ["config.py", "rx_tone.py"]
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5"]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def ssh_cmd(cmd):
    return ["ssh"] + SSH_OPTS + [f"{PI_USER}@{PI_HOST}", cmd]


def scp_file(local, remote):
    return ["scp"] + SSH_OPTS + [local, f"{PI_USER}@{PI_HOST}:{remote}"]


def run(cmd, **kwargs):
    print(f"  > {' '.join(cmd)}")
    return subprocess.run(cmd, **kwargs)


def main():
    print("=" * 60)
    print("  B210 Box Validation Test")
    print("=" * 60)

    # Step 1: Check SSH connectivity
    print("\n[1/5] Checking SSH to Pi ...")
    r = run(ssh_cmd("echo ok"), capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        print(f"  FAIL: Cannot SSH to {PI_USER}@{PI_HOST}")
        print(f"  stderr: {r.stderr.strip()}")
        sys.exit(1)
    print("  OK")

    # Step 2: Deploy scripts
    print("\n[2/5] Deploying scripts to Pi ...")
    run(ssh_cmd(f"mkdir -p {PI_WORK_DIR}"))
    for script in SCRIPTS_TO_DEPLOY:
        local_path = os.path.join(SCRIPT_DIR, script)
        r = run(scp_file(local_path, f"{PI_WORK_DIR}/{script}"))
        if r.returncode != 0:
            print(f"  FAIL: Could not copy {script}")
            sys.exit(1)
    print("  OK")

    # Step 3: Start RX on Pi (background, with timeout)
    rx_timeout = int(DURATION + 10)
    rx_cmd = f"cd {PI_WORK_DIR} && timeout {rx_timeout} python3 rx_tone.py"
    print(f"\n[3/5] Starting receiver on Pi (timeout {rx_timeout}s) ...")
    rx_proc = subprocess.Popen(
        ["ssh"] + SSH_OPTS + [f"{PI_USER}@{PI_HOST}", rx_cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    time.sleep(3)

    # Step 4: Run TX locally
    print("\n[4/5] Starting transmitter locally ...")
    tx_result = run(
        [sys.executable, os.path.join(SCRIPT_DIR, "tx_tone.py")],
        capture_output=True, text=True, timeout=int(DURATION + 15)
    )
    print(tx_result.stdout)
    if tx_result.returncode != 0:
        print(f"  TX FAIL: {tx_result.stderr}")
        rx_proc.kill()
        sys.exit(1)

    # Step 5: Collect RX results
    print("[5/5] Collecting receiver results ...")
    try:
        rx_stdout, rx_stderr = rx_proc.communicate(timeout=rx_timeout)
    except subprocess.TimeoutExpired:
        rx_proc.kill()
        print("  FAIL: Receiver timed out")
        sys.exit(1)

    print(f"  RX log: {rx_stderr.strip()}")

    try:
        result = json.loads(rx_stdout)
    except json.JSONDecodeError:
        print(f"  FAIL: Could not parse RX output: {rx_stdout}")
        sys.exit(1)

    # Report
    print("\n" + "=" * 60)
    print(f"  RESULT:  {result['status']}")
    print(f"  Tone detected at:   {result['peak_freq_hz']/1e3:.1f} kHz")
    print(f"  Expected:           {result['expected_freq_hz']/1e3:.1f} kHz")
    print(f"  Frequency error:    {result['freq_error_hz']:.0f} Hz")
    print(f"  SNR:                {result['snr_db']:.1f} dB  (threshold: {result['snr_threshold_db']:.1f} dB)")
    print("=" * 60)

    sys.exit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
