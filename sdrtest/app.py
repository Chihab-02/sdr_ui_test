#!/usr/bin/env python3
"""
Flask web UI for B210 box validation.
Controls TX locally and RX on the Raspberry Pi via SSH.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, render_template, request

from config import (CENTER_FREQ, SAMPLE_RATE, TONE_OFFSET, TX_GAIN, RX_GAIN,
                    PI_HOST, PI_USER, PI_WORK_DIR, TONE_SNR_MIN_DB)

app = Flask(__name__)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5"]
SCRIPTS_TO_DEPLOY = ["config.py", "rx_tone.py"]

tx_proc = None
rx_proc = None
rx_result = None
rx_stderr_log = ""
deploy_done = False


def ssh_cmd(cmd):
    return ["ssh"] + SSH_OPTS + [f"{PI_USER}@{PI_HOST}", cmd]


def scp_file(local, remote):
    return ["scp"] + SSH_OPTS + [local, f"{PI_USER}@{PI_HOST}:{remote}"]


def deploy_to_pi():
    global deploy_done
    subprocess.run(ssh_cmd(f"mkdir -p {PI_WORK_DIR}"),
                   capture_output=True, timeout=10)
    for script in SCRIPTS_TO_DEPLOY:
        local_path = os.path.join(SCRIPT_DIR, script)
        r = subprocess.run(scp_file(local_path, f"{PI_WORK_DIR}/{script}"),
                           capture_output=True, timeout=15)
        if r.returncode != 0:
            return False, f"Failed to copy {script}: {r.stderr.decode()}"
    deploy_done = True
    return True, "Deployed"


def collect_rx_output():
    """Background thread that reads rx_proc output after it finishes."""
    global rx_result, rx_stderr_log
    if rx_proc is None:
        return
    stdout, stderr = rx_proc.communicate()
    rx_stderr_log = stderr.strip() if stderr else ""
    if stdout:
        try:
            rx_result = json.loads(stdout)
        except json.JSONDecodeError:
            rx_result = {"status": "FAIL", "error": f"Bad output: {stdout[:200]}"}


@app.route("/")
def index():
    return render_template("index.html",
                           center_freq=CENTER_FREQ,
                           sample_rate=SAMPLE_RATE,
                           tone_offset=TONE_OFFSET,
                           tx_gain=TX_GAIN,
                           rx_gain=RX_GAIN,
                           pi_host=PI_HOST,
                           snr_threshold=TONE_SNR_MIN_DB)


@app.route("/status")
def status():
    tx_running = tx_proc is not None and tx_proc.poll() is None
    rx_running = rx_proc is not None and rx_proc.poll() is None
    return jsonify({
        "tx_running": tx_running,
        "rx_running": rx_running,
        "deployed": deploy_done,
        "rx_result": rx_result,
        "rx_log": rx_stderr_log,
    })


@app.route("/deploy", methods=["POST"])
def deploy():
    ok, msg = deploy_to_pi()
    return jsonify({"success": ok, "message": msg})


@app.route("/tx/start", methods=["POST"])
def tx_start():
    global tx_proc
    if tx_proc and tx_proc.poll() is None:
        return jsonify({"success": False, "message": "TX already running"})
    tx_proc = subprocess.Popen(
        [sys.executable, os.path.join(SCRIPT_DIR, "tx_tone.py")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    return jsonify({"success": True, "message": "TX started"})


@app.route("/tx/stop", methods=["POST"])
def tx_stop():
    global tx_proc
    if tx_proc is None or tx_proc.poll() is not None:
        return jsonify({"success": False, "message": "TX not running"})
    tx_proc.send_signal(signal.SIGINT)
    try:
        tx_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        tx_proc.kill()
    tx_proc = None
    return jsonify({"success": True, "message": "TX stopped"})


@app.route("/rx/start", methods=["POST"])
def rx_start():
    global rx_proc, rx_result, rx_stderr_log
    if rx_proc and rx_proc.poll() is None:
        return jsonify({"success": False, "message": "RX already running"})

    if not deploy_done:
        ok, msg = deploy_to_pi()
        if not ok:
            return jsonify({"success": False, "message": msg})

    rx_result = None
    rx_stderr_log = ""
    rx_cmd = f"cd {PI_WORK_DIR} && python3 rx_tone.py"
    rx_proc = subprocess.Popen(
        ["ssh"] + SSH_OPTS + [f"{PI_USER}@{PI_HOST}", rx_cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    return jsonify({"success": True, "message": "RX started on Pi"})


@app.route("/rx/stop", methods=["POST"])
def rx_stop():
    global rx_proc
    if rx_proc is None or rx_proc.poll() is None:
        pass

    if rx_proc and rx_proc.poll() is None:
        # Send Ctrl+C via SSH by killing the SSH process, which forwards SIGHUP
        rx_proc.send_signal(signal.SIGINT)
        t = threading.Thread(target=collect_rx_output, daemon=True)
        t.start()
        t.join(timeout=10)
        if rx_proc.poll() is None:
            rx_proc.kill()
            rx_proc.wait()
        return jsonify({"success": True, "message": "RX stopped"})

    return jsonify({"success": False, "message": "RX not running"})


@app.route("/test/run", methods=["POST"])
def run_test():
    """One-click: deploy, start RX, wait, start TX, wait, stop both, return results."""
    global tx_proc, rx_proc, rx_result, rx_stderr_log

    # Clean up any existing processes
    for p in [tx_proc, rx_proc]:
        if p and p.poll() is None:
            p.send_signal(signal.SIGINT)
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    rx_result = None
    rx_stderr_log = ""

    # Deploy
    ok, msg = deploy_to_pi()
    if not ok:
        return jsonify({"success": False, "message": f"Deploy failed: {msg}"})

    # Start RX
    rx_cmd = f"cd {PI_WORK_DIR} && python3 rx_tone.py"
    rx_proc = subprocess.Popen(
        ["ssh"] + SSH_OPTS + [f"{PI_USER}@{PI_HOST}", rx_cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    time.sleep(3)

    # Start TX
    tx_proc = subprocess.Popen(
        [sys.executable, os.path.join(SCRIPT_DIR, "tx_tone.py")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    time.sleep(4)

    # Stop TX
    tx_proc.send_signal(signal.SIGINT)
    try:
        tx_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        tx_proc.kill()
    tx_proc = None

    time.sleep(1)

    # Stop RX and collect
    rx_proc.send_signal(signal.SIGINT)
    try:
        stdout, stderr = rx_proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        rx_proc.kill()
        stdout, stderr = rx_proc.communicate()

    rx_stderr_log = stderr.strip() if stderr else ""
    if stdout:
        try:
            rx_result = json.loads(stdout)
        except json.JSONDecodeError:
            rx_result = {"status": "FAIL", "error": f"Bad output: {stdout[:200]}"}
    else:
        rx_result = {"status": "FAIL", "error": "No output from receiver"}

    rx_proc = None
    return jsonify({"success": True, "result": rx_result, "rx_log": rx_stderr_log})


if __name__ == "__main__":
    print(f"B210 Box Validation UI: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
