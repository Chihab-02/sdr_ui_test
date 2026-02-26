#!/usr/bin/env python3

import threading
import tkinter as tk
from tkinter import messagebox

from gsm_burst_uhd_b210 import Params, run


class GsmBurstApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GSM Burst B210")
        self.root.resizable(False, False)

        self.stop_event = threading.Event()
        self.tx_thread = None

        frame = tk.Frame(root, padx=40, pady=30)
        frame.pack()

        self.status_label = tk.Label(frame, text="Idle", font=("Helvetica", 14))
        self.status_label.pack(pady=(0, 20))

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

    def start_test(self):
        if self.tx_thread and self.tx_thread.is_alive():
            return

        self.stop_event.clear()
        self.test_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_label.config(text="Transmitting...", fg="green")

        self.tx_thread = threading.Thread(target=self._run_tx, daemon=True)
        self.tx_thread.start()

    def _run_tx(self):
        try:
            params = Params(enable_live_plot=False)
            run(params, total_s=12.0, tx_gain_db=50.0, stop_event=self.stop_event)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.root.after(0, self._on_tx_done)

    def _on_tx_done(self):
        self.test_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_label.config(text="Idle", fg="black")

    def stop_test(self):
        self.stop_event.set()
        self.status_label.config(text="Stopping...", fg="orange")


if __name__ == "__main__":
    root = tk.Tk()
    GsmBurstApp(root)
    root.mainloop()
