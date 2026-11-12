#!/usr/bin/env python3
"""NFSHP2-3DS Packer's window. The work itself is hp2_packer.py's run(),
here on a worker thread that talks to the window through a queue.

    python tools/hp2_packer_gui.pyw      (pythonw on Windows: no console)

Standard library only (tkinter), Python 3.8 or newer.
"""
import json
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hp2_packer  # noqa: E402

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox, ttk  # noqa: E402

SETTINGS = Path.home() / ".nfshp2_packer.json"


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(d):
    try:
        SETTINGS.write_text(json.dumps(d, indent=1), encoding="utf-8")
    except OSError:
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.worker = None
        self.stop = threading.Event()
        s = load_settings()

        root.title(hp2_packer.APP_NAME)
        root.minsize(620, 520)
        icon = resource("icon.png")
        if icon:
            try:
                self.icon = tk.PhotoImage(file=str(icon))
                root.iconphoto(True, self.icon)
            except tk.TclError:
                pass

        f = ttk.Frame(root, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="NFSHP2-3DS Packer",
                  font=("Segoe UI", 15, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(f, wraplength=580, justify="left", text=(
            "Makes the NFSHP2 folder the 3DS port reads, from your own PS2 "
            "disc of Need for Speed: Hot Pursuit 2. Choose the disc (a .iso "
            "image, or the disc's drive), and your SD card.")).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(2, 12))

        self.disc = tk.StringVar(value=s.get("disc", ""))
        self.card = tk.StringVar(value=s.get("card", ""))
        self.work = tk.StringVar(value=s.get("work") or
                                 str(hp2_packer.default_work()))
        self.keep = tk.BooleanVar(value=s.get("keep_work", False))
        self.prune = tk.BooleanVar(value=s.get("prune", False))

        self.inputs = []
        self._row(f, 2, "PS2 disc:", self.disc,
                  [("Disc image...", self.pick_iso),
                   ("Drive or folder...", self.pick_disc_dir)],
                  "a .iso of the disc, the disc's drive, or a folder with "
                  "ZDIR.BIN and ZZDATA.BIN")
        self._row(f, 4, "SD card:", self.card,
                  [("Choose...", self.pick_card)],
                  "the card's root (like E:\\), or a folder to copy to the "
                  "card's root later; about 2.9 GB")
        self._row(f, 6, "Work folder:", self.work,
                  [("Choose...", self.pick_work)],
                  "where the disc is unpacked while this runs; about 3.3 GB")

        opts = ttk.Frame(f)
        opts.grid(row=8, column=0, columnspan=4, sticky="w", pady=(6, 0))
        c1 = ttk.Checkbutton(opts, variable=self.keep, text=(
            "Keep the unpacked disc files afterwards (3.3 GB)"))
        c1.pack(anchor="w")
        c2 = ttk.Checkbutton(opts, variable=self.prune, text=(
            "Delete old game files on the card that aren't from this disc "
            "(your saves are kept)"))
        c2.pack(anchor="w")
        self.inputs += [c1, c2]

        btns = ttk.Frame(f)
        btns.grid(row=9, column=0, columnspan=4, sticky="we", pady=(12, 6))
        self.go_btn = ttk.Button(btns, text="Make SD card files",
                                 command=self.start)
        self.go_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="Stop", command=self.cancel,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))

        self.step_lbl = ttk.Label(f, text="Ready.")
        self.step_lbl.grid(row=10, column=0, columnspan=4, sticky="w")
        self.bar = ttk.Progressbar(f, mode="determinate", maximum=1000)
        self.bar.grid(row=11, column=0, columnspan=4, sticky="we",
                      pady=(4, 8))

        logf = ttk.Frame(f)
        logf.grid(row=12, column=0, columnspan=4, sticky="nsew")
        f.rowconfigure(12, weight=1)
        self.log = tk.Text(logf, height=12, wrap="word", state="disabled",
                           font=("Consolas", 9))
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def _row(self, f, r, label, var, buttons, hint):
        ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8))
        e = ttk.Entry(f, textvariable=var)
        e.grid(row=r, column=1, sticky="we")
        self.inputs.append(e)
        for k, (text, cmd) in enumerate(buttons):
            b = ttk.Button(f, text=text, command=cmd)
            b.grid(row=r, column=2 + k, padx=(6, 0))
            self.inputs.append(b)
        ttk.Label(f, text=hint, foreground="#666").grid(
            row=r + 1, column=1, columnspan=3, sticky="w", pady=(0, 6))

    # ----------------------------------------------------------- choosing
    def pick_iso(self):
        p = filedialog.askopenfilename(
            title="The Hot Pursuit 2 disc image",
            filetypes=[("Disc images", "*.iso"), ("All files", "*.*")])
        if p:
            self.disc.set(os.path.normpath(p))

    def pick_disc_dir(self):
        p = filedialog.askdirectory(
            title="The disc's drive, or the folder with ZDIR.BIN and ZZDATA.BIN")
        if p:
            self.disc.set(os.path.normpath(p))

    def pick_card(self):
        p = filedialog.askdirectory(title="The SD card (its root)")
        if p:
            self.card.set(os.path.normpath(p))

    def pick_work(self):
        p = filedialog.askdirectory(title="Where to unpack the disc")
        if p:
            self.work.set(os.path.normpath(p))

    # ------------------------------------------------------------ the run
    def start(self):
        disc, card = self.disc.get().strip(), self.card.get().strip()
        work = self.work.get().strip() or str(hp2_packer.default_work())
        if not disc or not card:
            messagebox.showwarning(hp2_packer.APP_NAME,
                                   "Choose the PS2 disc and the SD card first.")
            return
        save_settings({"disc": disc, "card": card, "work": work,
                       "keep_work": self.keep.get(),
                       "prune": self.prune.get()})
        self.set_busy(True)
        self.stop.clear()
        self.clear_log()
        args = dict(disc=disc, card=card, work=work, prune=self.prune.get(),
                    keep_work=self.keep.get())
        self.worker = threading.Thread(target=self.work_thread, args=(args,),
                                       daemon=True)
        self.worker.start()

    def work_thread(self, args):
        q = self.q
        try:
            hp2_packer.run(
                log=lambda m: q.put(("log", m)),
                step=lambda i, t: q.put(("step", i, t)),
                progress=lambda d, n: q.put(("prog", d, n)),
                cancel=self.stop.is_set, **args)
            q.put(("done", None))
        except hp2_packer.Cancelled:
            q.put(("done", "Stopped. Run it again to finish; what was "
                           "already copied to the card isn't copied twice."))
        except SystemExit as e:
            q.put(("done", str(e.code) if e.code is not None else "stopped"))
        except OSError as e:
            q.put(("done", "Couldn't read or write a file: %s. Is the disc "
                           "or the SD card still there, and can this folder "
                           "be written to?" % e))
        except Exception:
            q.put(("log", traceback.format_exc()))
            q.put(("done", "Something went wrong; the log says what."))

    def cancel(self):
        self.stop.set()
        self.step_lbl.configure(text="Stopping...")

    def poll(self):
        last_prog = None
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "log":
                    self.write(m[1])
                elif m[0] == "step":
                    self.cur_step = m[1]
                    self.step_lbl.configure(text="Step %d of %d: %s" % (
                        m[1] + 1, len(hp2_packer.STEPS), m[2]))
                    self.bar.configure(value=0)
                elif m[0] == "prog":
                    last_prog = m
                elif m[0] == "done":
                    self.finish(m[1])
        except queue.Empty:
            pass
        if last_prog and last_prog[2]:
            self.bar.configure(value=1000 * last_prog[1] / last_prog[2])
        self.root.after(100, self.poll)

    def finish(self, error):
        self.set_busy(False)
        if error:
            self.step_lbl.configure(text="Not finished.")
            self.write(error)
            messagebox.showerror(hp2_packer.APP_NAME, error)
        else:
            self.bar.configure(value=1000)
            self.step_lbl.configure(text="Done. The SD card is ready.")
            messagebox.showinfo(hp2_packer.APP_NAME, (
                "Done. Put the SD card in the New 3DS, install "
                "NFSHP2-3DS.cia with FBI, and start the game."))

    def set_busy(self, busy):
        for w in self.inputs:
            w.configure(state="disabled" if busy else "normal")
        self.go_btn.configure(state="disabled" if busy else "normal")
        self.stop_btn.configure(state="normal" if busy else "disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        # The copy step logs a line a file: keep the box from growing
        # without end.
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 3000:
            self.log.delete("1.0", "%d.0" % (lines - 2500))
        self.log.see("end")
        self.log.configure(state="disabled")

    def close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                    hp2_packer.APP_NAME,
                    "It is still working. Stop and close?"):
                return
            self.stop.set()
        self.root.destroy()


def resource(name):
    for base in (getattr(sys, "_MEIPASS", None), HERE):
        if base and (Path(base) / name).is_file():
            return Path(base) / name
    return None


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if sys.platform == "win32" else "clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
