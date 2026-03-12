#!/usr/bin/env python3
"""Single UI — transmit a CW tone on SDR1 and view live spectrum on SDR2."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from collections import deque

import numpy as np

try:
    import uhd
except Exception:
    uhd = None

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from config import TX_DEVICE_ARGS, RX_DEVICE_ARGS

NFFT = 1024
PLOT_UPDATE_MS = 100
DETECTION_SNR_THRESHOLD_DB = 10  # peak must be this many dB above noise floor


class ToneTestApp:
    def __init__(self, root):
        self.root = root
        self.root.title("B210 Tone Test")
        self.root.configure(bg="#FAFAFA")

        self.stop_event = threading.Event()
        self.tx_thread = None
        self.rx_thread = None
        self.sample_queue = deque(maxlen=20)
        self.plot_timer_id = None

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TLabel", background="#FAFAFA", font=("Helvetica", 11))
        style.configure("Header.TLabel", font=("Helvetica", 18, "bold"), background="#FAFAFA")

        main = ttk.Frame(root, padding=15)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="B210 Tone Test", style="Header.TLabel").pack(pady=(0, 10))

        # ── Top row: TX params | RX params | Status / Buttons ──
        top = ttk.Frame(main)
        top.pack(fill=tk.X, pady=(0, 10))

        # TX parameters
        tx_frame = ttk.LabelFrame(top, text=f"TX  ({TX_DEVICE_ARGS})", padding=10)
        tx_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        tx_fields = [
            ("Center Freq (MHz)", "880.0"),
            ("Tone Offset (kHz)", "100.0"),
            ("Sample Rate (MHz)", "1.0"),
            ("TX Gain (dB)", "0"),
            ("Amplitude (0-1)", "0.5"),
        ]
        self.tx_entries = {}
        for i, (label, default) in enumerate(tx_fields):
            ttk.Label(tx_frame, text=label).grid(row=i, column=0, sticky="w", pady=3)
            entry = ttk.Entry(tx_frame, width=12, justify="right")
            entry.insert(0, default)
            entry.grid(row=i, column=1, sticky="e", padx=(10, 0), pady=3)
            self.tx_entries[label] = entry

        # RX parameters
        rx_frame = ttk.LabelFrame(top, text=f"RX  ({RX_DEVICE_ARGS})", padding=10)
        rx_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        rx_fields = [
            ("RX Gain (dB)", "0"),
        ]
        self.rx_entries = {}
        for i, (label, default) in enumerate(rx_fields):
            ttk.Label(rx_frame, text=label).grid(row=i, column=0, sticky="w", pady=3)
            entry = ttk.Entry(rx_frame, width=12, justify="right")
            entry.insert(0, default)
            entry.grid(row=i, column=1, sticky="e", padx=(10, 0), pady=3)
            self.rx_entries[label] = entry

        ttk.Label(rx_frame, text="Center Freq & Sample Rate\nare shared with TX",
                  font=("Helvetica", 9), foreground="#757575").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # Right panel: status + readouts + buttons
        right = ttk.Frame(top)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))

        # Status
        self.status_var = tk.StringVar(value="Idle")
        self.status_label = tk.Label(right, textvariable=self.status_var,
                                     font=("Helvetica", 14, "bold"),
                                     bg="#FAFAFA", fg="#424242")
        self.status_label.pack(anchor="w", pady=(0, 6))

        # TX power readout
        self.tx_power_var = tk.StringVar(value="TX Power: --")
        tk.Label(right, textvariable=self.tx_power_var,
                 font=("Helvetica", 11), bg="#FAFAFA", fg="#1565C0").pack(anchor="w")

        # Peak readouts
        self.peak_var = tk.StringVar(value="RX Peak: --")
        tk.Label(right, textvariable=self.peak_var,
                 font=("Helvetica", 12, "bold"), bg="#FAFAFA", fg="#D32F2F").pack(anchor="w", pady=(4, 0))

        self.peak_power_var = tk.StringVar(value="RX Power: --")
        tk.Label(right, textvariable=self.peak_power_var,
                 font=("Helvetica", 11), bg="#FAFAFA", fg="#1565C0").pack(anchor="w", pady=(2, 0))

        # Signal detection indicator
        det_frame = ttk.Frame(right)
        det_frame.pack(anchor="w", pady=(6, 10))

        self.snr_var = tk.StringVar(value="SNR: --")
        tk.Label(det_frame, textvariable=self.snr_var,
                 font=("Helvetica", 11), bg="#FAFAFA", fg="#424242").pack(side=tk.LEFT)

        self.detect_var = tk.StringVar(value="")
        self.detect_label = tk.Label(det_frame, textvariable=self.detect_var,
                                     font=("Helvetica", 13, "bold"),
                                     bg="#FAFAFA", fg="#424242")
        self.detect_label.pack(side=tk.LEFT, padx=(10, 0))

        # Buttons
        btn_frame = ttk.Frame(right)
        btn_frame.pack(anchor="w")

        self.start_btn = tk.Button(
            btn_frame, text="Start", width=14, height=2,
            bg="#4CAF50", fg="white", font=("Helvetica", 12, "bold"),
            activebackground="#388E3C", command=self.start_test)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_btn = tk.Button(
            btn_frame, text="Stop", width=14, height=2,
            bg="#f44336", fg="white", font=("Helvetica", 12, "bold"),
            activebackground="#C62828", command=self.stop_test, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT)

        # ── Spectrum plot ──
        self.fig = Figure(figsize=(10, 4), dpi=100, facecolor="#FAFAFA")
        self.ax = self.fig.add_subplot(111)
        self._reset_plot()
        self.fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.fig, master=main)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.line = None
        self.peak_marker = None
        self.tone_marker = None
        self.noise_line = None
        self.center_freq = 880e6
        self.sample_rate = 1e6
        self.tone_offset = 100e3

    # ── Read UI fields ──────────────────────────────────────────

    def _read_params(self):
        try:
            center_mhz = float(self.tx_entries["Center Freq (MHz)"].get())
            offset_khz = float(self.tx_entries["Tone Offset (kHz)"].get())
            rate_mhz = float(self.tx_entries["Sample Rate (MHz)"].get())
            tx_gain = float(self.tx_entries["TX Gain (dB)"].get())
            amp = float(self.tx_entries["Amplitude (0-1)"].get())
            rx_gain = float(self.rx_entries["RX Gain (dB)"].get())
        except ValueError:
            raise ValueError("All fields must be valid numbers.")

        if tx_gain < 0 or tx_gain > 89.75:
            raise ValueError("TX Gain must be between 0 and 89.75 dB.")
        if rx_gain < 0 or rx_gain > 76:
            raise ValueError("RX Gain must be between 0 and 76 dB.")
        if amp < 0 or amp > 1:
            raise ValueError("Amplitude must be between 0 and 1.")

        return {
            "center_freq": center_mhz * 1e6,
            "tone_offset": offset_khz * 1e3,
            "sample_rate": rate_mhz * 1e6,
            "tx_gain": tx_gain,
            "rx_gain": rx_gain,
            "amplitude": amp,
        }

    # ── Start / Stop ────────────────────────────────────────────

    def start_test(self):
        if self._is_running():
            return

        try:
            params = self._read_params()
        except ValueError as e:
            messagebox.showerror("Invalid Parameters", str(e))
            return

        if uhd is None:
            messagebox.showerror("Error", "UHD Python API not available.")
            return

        self.center_freq = params["center_freq"]
        self.sample_rate = params["sample_rate"]
        self.tone_offset = params["tone_offset"]
        self.stop_event.clear()
        self.sample_queue.clear()

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self._set_entries_state("disabled")
        self._set_status("Starting ...", "#FF8F00")
        self._reset_readouts()

        self.line = None
        self.peak_marker = None
        self.tone_marker = None
        self.noise_line = None
        self._reset_plot()
        self.canvas.draw()

        self.tx_thread = threading.Thread(target=self._run_tx, args=(params,), daemon=True)
        self.rx_thread = threading.Thread(target=self._run_rx, args=(params,), daemon=True)
        self.tx_thread.start()
        self.rx_thread.start()
        self._schedule_plot_update()

    def stop_test(self):
        if not self.stop_event.is_set():
            self.stop_event.set()
            self._set_status("Stopping ...", "#FF8F00")
            self.stop_btn.config(state=tk.DISABLED)
            self._poll_threads_stopped()

    def _poll_threads_stopped(self):
        """Poll until both threads have fully exited, then clean up."""
        if self._is_running():
            self.root.after(150, self._poll_threads_stopped)
            return
        self._on_fully_stopped()

    def _on_fully_stopped(self):
        """Called once both TX and RX threads are dead."""
        if self.plot_timer_id is not None:
            self.root.after_cancel(self.plot_timer_id)
            self.plot_timer_id = None
        self.tx_thread = None
        self.rx_thread = None
        self.sample_queue.clear()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self._set_entries_state("normal")
        self._set_status("Idle", "#424242")

    # ── TX thread ───────────────────────────────────────────────

    def _run_tx(self, p):
        try:
            usrp = uhd.usrp.MultiUSRP(TX_DEVICE_ARGS)
            usrp.set_tx_rate(p["sample_rate"], 0)
            usrp.set_tx_freq(p["center_freq"], 0)
            usrp.set_tx_gain(p["tx_gain"], 0)
            usrp.set_tx_antenna("TX/RX", 0)

            st_args = uhd.usrp.StreamArgs("fc32", "sc16")
            st_args.channels = [0]
            tx_streamer = usrp.get_tx_stream(st_args)
            spb = tx_streamer.get_max_num_samps()

            t = np.arange(spb) / p["sample_rate"]
            tone = (p["amplitude"] * np.exp(1j * 2 * np.pi * p["tone_offset"] * t)).astype(np.complex64)
            power_dbfs = 10 * np.log10(np.mean(np.abs(tone) ** 2) + 1e-20)

            md = uhd.types.TXMetadata()
            md.start_of_burst = True
            md.end_of_burst = False

            self.root.after(0, lambda: self.tx_power_var.set(f"TX Power: {power_dbfs:+.1f} dBFS"))

            while not self.stop_event.is_set():
                tx_streamer.send(tone, md)
                md.start_of_burst = False

            md.end_of_burst = True
            tx_streamer.send(np.zeros(1, dtype=np.complex64), md)

        except Exception as e:
            msg = str(e)
            self.root.after(0, lambda: messagebox.showerror("TX Error", msg))

    # ── RX thread ───────────────────────────────────────────────

    def _run_rx(self, p):
        try:
            usrp = uhd.usrp.MultiUSRP(RX_DEVICE_ARGS)
            usrp.set_rx_rate(p["sample_rate"], 0)
            usrp.set_rx_freq(p["center_freq"], 0)
            usrp.set_rx_gain(p["rx_gain"], 0)
            usrp.set_rx_antenna("RX2", 0)

            st_args = uhd.usrp.StreamArgs("fc32", "sc16")
            st_args.channels = [0]
            rx_streamer = usrp.get_rx_stream(st_args)

            spb = rx_streamer.get_max_num_samps()
            recv_buf = np.zeros(spb, dtype=np.complex64)

            stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
            stream_cmd.stream_now = True
            rx_streamer.issue_stream_cmd(stream_cmd)

            md = uhd.types.RXMetadata()

            self.root.after(0, lambda: self._set_status("Running", "#2E7D32"))

            while not self.stop_event.is_set():
                n_recv = rx_streamer.recv(recv_buf, md, timeout=1.0)
                if md.error_code == uhd.types.RXMetadataErrorCode.timeout:
                    continue
                if md.error_code != uhd.types.RXMetadataErrorCode.none:
                    continue
                if n_recv > 0:
                    self.sample_queue.append(recv_buf[:n_recv].copy())

            stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
            rx_streamer.issue_stream_cmd(stream_cmd)

        except Exception as e:
            msg = str(e)
            self.root.after(0, lambda: messagebox.showerror("RX Error", msg))

    # ── Live plot ───────────────────────────────────────────────

    def _schedule_plot_update(self):
        self._update_plot()
        if self.stop_event.is_set() and not self._is_running():
            self.plot_timer_id = None
            return
        self.plot_timer_id = self.root.after(PLOT_UPDATE_MS, self._schedule_plot_update)

    def _update_plot(self):
        if not self.sample_queue:
            return

        chunks = []
        while self.sample_queue:
            chunks.append(self.sample_queue.popleft())
        samples = np.concatenate(chunks)

        if len(samples) < NFFT:
            return

        window = np.hanning(NFFT)
        n_avg = len(samples) // NFFT
        psd = np.zeros(NFFT)
        for i in range(n_avg):
            seg = samples[i * NFFT:(i + 1) * NFFT]
            spectrum = np.fft.fftshift(np.fft.fft(seg * window))
            psd += np.abs(spectrum) ** 2
        psd /= max(n_avg, 1)
        psd_db = 10 * np.log10(psd + 1e-20)

        freqs_hz = np.fft.fftshift(np.fft.fftfreq(NFFT, 1 / self.sample_rate))
        freqs_abs = self.center_freq + freqs_hz
        freqs_mhz = freqs_abs / 1e6

        # Find the FFT bin closest to the expected tone frequency
        tone_bin = np.argmin(np.abs(freqs_hz - self.tone_offset))
        # Average a few bins around it for a more stable reading
        half_w = 3
        lo = max(0, tone_bin - half_w)
        hi = min(NFFT, tone_bin + half_w + 1)
        tone_power = 10 * np.log10(np.mean(psd[lo:hi]) + 1e-20)

        # Noise floor: median of spectrum, excluding DC region and tone region
        dc_bin = NFFT // 2
        dc_exclude = 10
        mask = np.ones(NFFT, dtype=bool)
        mask[max(0, dc_bin - dc_exclude):min(NFFT, dc_bin + dc_exclude + 1)] = False
        mask[lo:hi] = False
        if np.any(mask):
            noise_floor = np.median(psd_db[mask])
        else:
            noise_floor = np.median(psd_db)

        snr = tone_power - noise_floor
        expected_freq_mhz = (self.center_freq + self.tone_offset) / 1e6

        self.peak_var.set(f"Tone @ {expected_freq_mhz:.4f} MHz: {tone_power:.1f} dB")
        self.peak_power_var.set(f"Noise floor: {noise_floor:.1f} dB")
        self.snr_var.set(f"SNR: {snr:.1f} dB")

        detected = snr >= DETECTION_SNR_THRESHOLD_DB
        if detected:
            self.detect_var.set("\u2714 TONE DETECTED")
            self.detect_label.config(fg="#2E7D32")
        else:
            self.detect_var.set("\u2718 NO SIGNAL")
            self.detect_label.config(fg="#C62828")

        tone_freq_mhz = freqs_mhz[tone_bin]

        if self.line is None:
            self.line, = self.ax.plot(freqs_mhz, psd_db, color="#1565C0", linewidth=0.8)
            self.tone_marker, = self.ax.plot(tone_freq_mhz, tone_power, 'rv', markersize=10,
                                             label=f"Expected tone ({self.tone_offset/1e3:.0f} kHz)")
            self.noise_line = self.ax.axhline(y=noise_floor, color="#FF9800", linestyle='--',
                                              linewidth=0.8, label="Noise floor")
            self.ax.axvline(x=tone_freq_mhz, color="#E53935", linestyle=':', alpha=0.4)
            self.ax.legend(loc="upper right", fontsize=9)
            self.ax.set_xlim(freqs_mhz[0], freqs_mhz[-1])
        else:
            self.line.set_ydata(psd_db)
            self.tone_marker.set_data([tone_freq_mhz], [tone_power])
            self.noise_line.set_ydata([noise_floor, noise_floor])

        y_min = max(psd_db.min() - 5, -120)
        y_max = max(psd_db.max(), tone_power) + 10
        self.ax.set_ylim(y_min, y_max)

        self.canvas.draw_idle()

    # ── Helpers ──────────────────────────────────────────────────

    def _reset_plot(self):
        self.ax.clear()
        self.ax.set_facecolor("#F5F5F5")
        self.ax.set_xlabel("Frequency (MHz)")
        self.ax.set_ylabel("Power (dB)")
        self.ax.set_title("Live RX Spectrum")
        self.ax.grid(True, alpha=0.3)

    def _reset_readouts(self):
        self.tx_power_var.set("TX Power: --")
        self.peak_var.set("RX Peak: --")
        self.peak_power_var.set("RX Power: --")
        self.snr_var.set("SNR: --")
        self.detect_var.set("")

    def _is_running(self):
        return ((self.tx_thread and self.tx_thread.is_alive()) or
                (self.rx_thread and self.rx_thread.is_alive()))

    def _set_status(self, text, color):
        self.status_var.set(text)
        self.status_label.config(fg=color)

    def _set_entries_state(self, state):
        for entry in self.tx_entries.values():
            entry.config(state=state)
        for entry in self.rx_entries.values():
            entry.config(state=state)


if __name__ == "__main__":
    root = tk.Tk()
    ToneTestApp(root)
    root.mainloop()
