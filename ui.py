#!/usr/bin/env python3
"""Antenna-test UI: transmit on lutetia, receive on MyB210 (2 channels)."""

import time
import threading
import tkinter as tk
from tkinter import messagebox

import numpy as np

from config import Params
from transmitter import transmit
from receiver import receive

CHECKMARK = "\u2714"
CROSSMARK = "\u2718"


class AntennaTestApp:
    def __init__(self, root):
        self.root = root
        self.root.title("B210 Antenna Tester")
        self.root.resizable(False, False)

        self.stop_event = threading.Event()
        self.tx_thread = None
        self.rx_thread = None
        self.params = Params()

        self.max_power = {0: -200.0, 1: -200.0}
        self.passed = {0: False, 1: False}
        self.thresholds = {
            0: self.params.antenna1_threshold_dbfs,
            1: self.params.antenna2_threshold_dbfs,
        }
        self.test_start_time = None
        self.timer_id = None

        frame = tk.Frame(root, padx=40, pady=30)
        frame.pack()

        self.status_label = tk.Label(frame, text="Idle", font=("Helvetica", 14))
        self.status_label.pack(pady=(0, 20))

        # ── power readouts ────────────────────────────────────────
        power_frame = tk.Frame(frame)
        power_frame.pack(pady=(0, 20))

        # TX Power
        tk.Label(power_frame, text="TX Power:", font=("Helvetica", 12)).grid(
            row=0, column=0, sticky="e", padx=(0, 8))
        self.tx_power_label = tk.Label(
            power_frame, text="-- dBFS", font=("Helvetica", 12, "bold"),
            fg="#1565C0", width=16, anchor="w")
        self.tx_power_label.grid(row=0, column=1)

        # Separator
        tk.Frame(power_frame, height=2, bg="#BDBDBD").grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=10)

        # Antenna 1 (ch 0 — TX/RX port)
        tk.Label(power_frame, text="Antenna 1:", font=("Helvetica", 12)).grid(
            row=2, column=0, sticky="e", padx=(0, 8))
        self.rx1_power_label = tk.Label(
            power_frame, text="-- dBFS", font=("Helvetica", 12, "bold"),
            fg="#424242", width=16, anchor="w")
        self.rx1_power_label.grid(row=2, column=1)
        self.rx1_status_label = tk.Label(
            power_frame, text="", font=("Helvetica", 14, "bold"), width=4)
        self.rx1_status_label.grid(row=2, column=2, padx=(8, 0))
        tk.Label(power_frame,
                 text=f"threshold: {self.thresholds[0]:.0f} dBFS",
                 font=("Helvetica", 9), fg="#757575").grid(
            row=2, column=3, padx=(6, 0), sticky="w")

        # Antenna 2 (ch 1 — RX2 port)
        tk.Label(power_frame, text="Antenna 2:", font=("Helvetica", 12)).grid(
            row=3, column=0, sticky="e", padx=(0, 8), pady=(6, 0))
        self.rx2_power_label = tk.Label(
            power_frame, text="-- dBFS", font=("Helvetica", 12, "bold"),
            fg="#424242", width=16, anchor="w")
        self.rx2_power_label.grid(row=3, column=1, pady=(6, 0))
        self.rx2_status_label = tk.Label(
            power_frame, text="", font=("Helvetica", 14, "bold"), width=4)
        self.rx2_status_label.grid(row=3, column=2, padx=(8, 0), pady=(6, 0))
        tk.Label(power_frame,
                 text=f"threshold: {self.thresholds[1]:.0f} dBFS",
                 font=("Helvetica", 9), fg="#757575").grid(
            row=3, column=3, padx=(6, 0), sticky="w", pady=(6, 0))

        # Timer / countdown
        self.timer_label = tk.Label(
            power_frame, text="", font=("Helvetica", 10), fg="#757575")
        self.timer_label.grid(row=4, column=0, columnspan=4, pady=(10, 0))

        # ── buttons ───────────────────────────────────────────────
        btn_frame = tk.Frame(frame)
        btn_frame.pack()

        self.test_btn = tk.Button(
            btn_frame, text="Test", width=12, height=2,
            bg="#4CAF50", fg="white", font=("Helvetica", 12, "bold"),
            command=self.start_test,
        )
        self.test_btn.pack(side=tk.LEFT, padx=10)

        self.stop_btn = tk.Button(
            btn_frame, text="Stop", width=12, height=2,
            bg="#f44336", fg="white", font=("Helvetica", 12, "bold"),
            command=self.stop_test, state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=10)

    # ── actions ──────────────────────────────────────────────────────

    def start_test(self):
        if self._is_running():
            return

        self.stop_event.clear()
        self.max_power = {0: -200.0, 1: -200.0}
        self.passed = {0: False, 1: False}
        self.test_start_time = time.monotonic()

        self.test_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self._set_status("Running ...", "green")
        self._reset_rx_display(0)
        self._reset_rx_display(1)
        self.tx_power_label.config(text="-- dBFS")

        self.rx_thread = threading.Thread(
            target=self._run_rx, args=(self.params,), daemon=True,
        )
        self.tx_thread = threading.Thread(
            target=self._run_tx, args=(self.params,), daemon=True,
        )
        self.rx_thread.start()
        self.tx_thread.start()
        self._tick_timer()

    def stop_test(self):
        self.stop_event.set()
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
        self.timer_label.config(text="")
        self._set_status("Stopping ...", "orange")

    # ── timer ─────────────────────────────────────────────────────

    def _tick_timer(self):
        if self.test_start_time is None or self.stop_event.is_set():
            return
        elapsed = time.monotonic() - self.test_start_time
        remaining = max(0.0, self.params.test_duration_s - elapsed)
        self.timer_label.config(text=f"Time remaining: {remaining:.1f}s")

        if remaining <= 0:
            self._finish_test()
            return

        self.timer_id = self.root.after(100, self._tick_timer)

    def _finish_test(self):
        """Called when time runs out or both antennas pass."""
        self.stop_event.set()
        for ch in (0, 1):
            if not self.passed[ch]:
                self._set_channel_fail(ch)
        if self.passed[0] and self.passed[1]:
            self._set_status("PASSED — both antennas verified", "#2E7D32")
        else:
            self._set_status("DONE — see results", "#C62828")
        self.timer_label.config(text="")

    # ── worker threads ───────────────────────────────────────────────

    def _run_tx(self, params):
        try:
            transmit(
                params,
                stop_event=self.stop_event,
                log=self._log,
                on_tx_power=self._on_tx_power,
            )
        except Exception as e:
            self._show_error(f"TX error: {e}")
        finally:
            self._maybe_done()

    def _run_rx(self, params):
        try:
            receive(
                params,
                stop_event=self.stop_event,
                on_samples=self._on_rx_samples,
                log=self._log,
            )
        except Exception as e:
            self._show_error(f"RX error: {e}")
        finally:
            self._maybe_done()

    def _on_tx_power(self, power_dbfs):
        self.root.after(0, lambda: self.tx_power_label.config(
            text=f"{power_dbfs:+.1f} dBFS"))

    def _on_rx_samples(self, channel, samples):
        if self.passed.get(channel, False):
            return
        mean_power = np.mean(np.abs(samples) ** 2)
        if mean_power > 0:
            power_dbfs = 10 * np.log10(mean_power)
        else:
            power_dbfs = -200.0

        if power_dbfs > self.max_power[channel]:
            self.max_power[channel] = power_dbfs
            p = power_dbfs
            self.root.after(0, lambda: self._update_rx_channel(channel, p))

    # ── UI updaters ────────────────────────────────────────────────

    def _reset_rx_display(self, channel):
        label = self.rx1_power_label if channel == 0 else self.rx2_power_label
        status = self.rx1_status_label if channel == 0 else self.rx2_status_label
        label.config(text="-- dBFS", fg="#424242")
        status.config(text="")

    def _update_rx_channel(self, channel, max_dbfs):
        label = self.rx1_power_label if channel == 0 else self.rx2_power_label
        status = self.rx1_status_label if channel == 0 else self.rx2_status_label
        threshold = self.thresholds[channel]

        label.config(text=f"{max_dbfs:+.1f} dBFS (max)")

        if max_dbfs >= threshold:
            label.config(fg="#2E7D32")
            status.config(text=CHECKMARK, fg="#2E7D32")
            self.passed[channel] = True
            if self.passed[0] and self.passed[1]:
                self._finish_test()
        else:
            label.config(fg="#424242")
            status.config(text="")

    def _set_channel_fail(self, channel):
        label = self.rx1_power_label if channel == 0 else self.rx2_power_label
        status = self.rx1_status_label if channel == 0 else self.rx2_status_label
        label.config(fg="#C62828")
        status.config(text=CROSSMARK, fg="#C62828")

    # ── helpers ───────────────────────────────────────────────────────

    def _is_running(self):
        return (
            (self.tx_thread and self.tx_thread.is_alive())
            or (self.rx_thread and self.rx_thread.is_alive())
        )

    def _maybe_done(self):
        self.root.after(100, self._check_threads_done)

    def _check_threads_done(self):
        if self._is_running():
            self.root.after(100, self._check_threads_done)
            return
        self._on_done()

    def _on_done(self):
        if str(self.test_btn.cget("state")) == "normal":
            return
        self.test_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.test_start_time = None
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
        self.timer_label.config(text="")
        if self.status_label.cget("text") == "Stopping ...":
            self.status_label.config(text="Stopped", fg="#F57C00")

    def _set_status(self, text, color="black"):
        self.root.after(0, lambda: self.status_label.config(text=text, fg=color))

    def _log(self, msg):
        print(msg)

    def _show_error(self, msg):
        self.root.after(0, lambda: messagebox.showerror("Error", msg))


if __name__ == "__main__":
    root = tk.Tk()
    AntennaTestApp(root)
    root.mainloop()
