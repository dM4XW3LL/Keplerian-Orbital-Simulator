#!/usr/bin/env python3
"""
Kepler Orbit Simulator v1.0
────────────────────────────
A GUI application that lets you spawn custom Keplerian orbits around the Sun
in real time. The physics engine is your compiled C library (kepler.so / .dylib),
called via ctypes. The GUI is built with tkinter + matplotlib embedded.

Usage:
    make          # compile kepler.so first
    python3 orbit_sim.py
"""

import sys
import os
import platform
import ctypes
import math
import time
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Ellipse
from matplotlib.animation import FuncAnimation

# ─────────────────────────────────────────────────────────────────────────────
#  1. Load the C shared library
# ─────────────────────────────────────────────────────────────────────────────

def load_kepler_lib():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    system = platform.system()

    if system == "Windows":
        candidates = ["kepler.dll"]
    elif system == "Darwin":
        candidates = ["kepler.dylib", "kepler.so"]
    else:
        candidates = ["kepler.so", "kepler.dylib"]

    for name in candidates:
        path = os.path.join(script_dir, name)
        if os.path.exists(path):
            lib = ctypes.CDLL(path)
            _setup_lib_signatures(lib)
            return lib

    raise FileNotFoundError(
        f"Could not find the Kepler shared library next to orbit_sim.py.\n"
        f"Expected one of: {candidates}\n\n"
        f"On Linux/macOS:  run  'make'\n"
        f"On Windows:      run  'gcc -O2 -fPIC -shared -o kepler.dll kepler.c'\n"
        f"                 (requires MinGW — install from https://www.mingw-w64.org)"
    )


def _setup_lib_signatures(lib):
    """Tell ctypes the argument and return types for every C function we use."""
    dbl = ctypes.c_double
    pdbl = ctypes.POINTER(ctypes.c_double)
    pint = ctypes.POINTER(ctypes.c_int)

    lib.kepler_newton.argtypes   = [dbl, dbl, pint]
    lib.kepler_newton.restype    = dbl

    lib.eccentric_to_true.argtypes = [dbl, dbl]
    lib.eccentric_to_true.restype  = dbl

    lib.orbit_position.argtypes  = [dbl, dbl, dbl, pdbl, pdbl]
    lib.orbit_position.restype   = None

    lib.planet_position.argtypes = [dbl, dbl, dbl, dbl, dbl, pdbl, pdbl, pint]
    lib.planet_position.restype  = None

    lib.mean_anomaly_at_time.argtypes = [dbl, dbl, dbl]
    lib.mean_anomaly_at_time.restype  = dbl


# ─────────────────────────────────────────────────────────────────────────────
#  2. Pure-Python wrappers (thin, but ergonomic)
# ─────────────────────────────────────────────────────────────────────────────

class KeplerEngine:
    """Thin Python wrapper around the compiled C functions."""

    def __init__(self, lib):
        self._lib = lib
        self._iter = ctypes.c_int(0)

    def planet_position(self, t_years: float, a: float, e: float,
                        period: float, M0: float):
        """Return (x, y) in AU at time t_years."""
        x = ctypes.c_double(0.0)
        y = ctypes.c_double(0.0)
        iters = ctypes.c_int(0)
        self._lib.planet_position(
            ctypes.c_double(t_years),
            ctypes.c_double(a),
            ctypes.c_double(e),
            ctypes.c_double(period),
            ctypes.c_double(M0),
            ctypes.byref(x),
            ctypes.byref(y),
            ctypes.byref(iters),
        )
        return x.value, y.value

    def full_orbit_trace(self, a: float, e: float, n_points: int = 500):
        """Return (xs, ys) arrays tracing the full ellipse, in AU."""
        iters = ctypes.c_int(0)
        xs, ys = [], []
        for i in range(n_points + 1):
            M = 2.0 * math.pi * i / n_points
            E = self._lib.kepler_newton(
                ctypes.c_double(M),
                ctypes.c_double(e),
                ctypes.byref(iters),
            )
            f = self._lib.eccentric_to_true(
                ctypes.c_double(e),
                ctypes.c_double(E),
            )
            x = ctypes.c_double(0.0)
            y = ctypes.c_double(0.0)
            self._lib.orbit_position(
                ctypes.c_double(f),
                ctypes.c_double(a),
                ctypes.c_double(e),
                ctypes.byref(x),
                ctypes.byref(y),
            )
            xs.append(x.value)
            ys.append(y.value)
        return np.array(xs), np.array(ys)


# ─────────────────────────────────────────────────────────────────────────────
#  3. Data model — one Body per spawned orbit
# ─────────────────────────────────────────────────────────────────────────────

_BODY_COUNTER = 0

class Body:
    """Holds orbital parameters + matplotlib artists for one orbiting body."""

    # Built-in solar system presets
    PRESETS = {
        "Mercury": dict(a=0.387, e=0.206, period=0.241, M0=0.0,  color="#b5b5b5"),
        "Venus":   dict(a=0.723, e=0.007, period=0.615, M0=0.0,  color="#e8cda0"),
        "Earth":   dict(a=1.000, e=0.017, period=1.000, M0=0.0,  color="#4fa3e0"),
        "Mars":    dict(a=1.524, e=0.093, period=1.881, M0=0.0,  color="#c1440e"),
        "Jupiter": dict(a=5.203, e=0.049, period=11.86, M0=0.0,  color="#c88b3a"),
        "Saturn":  dict(a=9.537, e=0.057, period=29.46, M0=0.0,  color="#e4d191"),
        "Uranus":  dict(a=19.19, e=0.047, period=84.01, M0=0.0,  color="#7de8e8"),
        "Neptune": dict(a=30.07, e=0.009, period=164.8, M0=0.0,  color="#5b7fde"),
    }

    def __init__(self, name, a, e, period, M0, color, marker_size=7):
        global _BODY_COUNTER
        _BODY_COUNTER += 1
        self.id          = _BODY_COUNTER
        self.name        = name
        self.a           = a        # semi-major axis (AU)
        self.e           = e        # eccentricity
        self.period      = period   # orbital period (years)
        self.M0          = M0       # initial mean anomaly (radians)
        self.color       = color
        self.marker_size = marker_size

        # matplotlib artists (set by the GUI)
        self.orbit_line  = None   # faint ellipse
        self.dot         = None   # planet dot
        self.trail_line  = None   # trailing path
        self.label_text  = None   # name label

        # Trail buffer: circular in time
        self.trail_x = []
        self.trail_y = []

    def __repr__(self):
        return (f"Body({self.name!r}, a={self.a}, e={self.e}, "
                f"P={self.period}yr, M0={math.degrees(self.M0):.1f}°)")


# ─────────────────────────────────────────────────────────────────────────────
#  4. Main application window
# ─────────────────────────────────────────────────────────────────────────────

# ── Visual theme ──────────────────────────────────────────────────────────────
BG_DARK    = "#0d1117"
BG_PANEL   = "#161b22"
BG_WIDGET  = "#21262d"
BORDER     = "#30363d"
TEXT_MAIN  = "#e6edf3"
TEXT_DIM   = "#8b949e"
ACCENT     = "#58a6ff"
ACCENT2    = "#f78166"
SUN_COLOR  = "#ffe066"
GREEN      = "#3fb950"
RED        = "#f85149"

FONT_TITLE = ("Courier New", 13, "bold")
FONT_LABEL = ("Courier New", 9)
FONT_SMALL = ("Courier New", 8)
FONT_MONO  = ("Courier New", 10)


class OrbitSimApp(tk.Tk):

    # How many days of simulation each animation tick advances
    DAYS_PER_TICK   = 5
    # How many days of trail to keep
    TRAIL_DAYS      = 365 * 2
    # Animation timer interval (ms)
    ANIM_INTERVAL   = 30

    def __init__(self, lib):
        super().__init__()
        self.engine = KeplerEngine(lib)

        self.title("Kepler Orbit Simulator  v1.0")
        self.configure(bg=BG_DARK)
        self.resizable(True, True)

        # Simulation state
        self.bodies: list[Body] = []
        self.t_years  = 0.0            # current simulation time
        self.running  = False          # animation on/off
        self._anim_id = None           # after() id

        # Selected color for next body
        self._next_color = ACCENT

        self._build_ui()
        self._style_ttk()

        # Draw Sun immediately
        self._draw_sun()

        self.after(100, self._resize_check)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        """Construct all widgets."""
        # Root grid: left panel | canvas
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._build_left_panel()
        self._build_canvas()

    def _build_left_panel(self):
        panel = tk.Frame(self, bg=BG_PANEL, width=300)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_propagate(False)
        panel.columnconfigure(0, weight=1)

        row = 0

        # ── Title ──────────────────────────────────────────────────────────
        tk.Label(
            panel, text="⊙  KEPLER  SIM", font=("Courier New", 14, "bold"),
            fg=ACCENT, bg=BG_PANEL, pady=10
        ).grid(row=row, column=0, sticky="ew"); row += 1

        tk.Frame(panel, bg=BORDER, height=1).grid(row=row, column=0, sticky="ew"); row += 1

        # ── Preset selector ───────────────────────────────────────────────
        sec = self._section(panel, "PRESETS", row); row += 1
        self._preset_var = tk.StringVar(value="Earth")
        preset_names = ["── Custom ──"] + list(Body.PRESETS.keys())
        self._preset_combo = ttk.Combobox(
            sec, textvariable=self._preset_var,
            values=preset_names, state="readonly", font=FONT_MONO
        )
        self._preset_combo.pack(fill="x", padx=8, pady=(0, 6))
        self._preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        # ── Orbital parameters ────────────────────────────────────────────
        sec2 = self._section(panel, "ORBITAL PARAMETERS", row); row += 1

        self._params = {}
        param_defs = [
            ("Name",          "name",    "str",   "MyBody"),
            ("Semi-Major Axis (AU)", "a", "float", "1.0"),
            ("Eccentricity",  "e",       "float",  "0.0"),
            ("Period (years)","period",  "float",  "1.0"),
            ("M₀ — Init. Mean Anomaly (°)", "M0", "float", "0.0"),
        ]
        for label, key, kind, default in param_defs:
            self._add_param_row(sec2, label, key, kind, default)

        # ── Name + Color ───────────────────────────────────────────────────
        color_row = tk.Frame(sec2, bg=BG_PANEL)
        color_row.pack(fill="x", padx=8, pady=2)
        tk.Label(color_row, text="Color", fg=TEXT_DIM, bg=BG_PANEL,
                 font=FONT_LABEL, width=18, anchor="w").pack(side="left")
        self._color_btn = tk.Button(
            color_row, bg=self._next_color, width=4,
            relief="flat", cursor="hand2",
            command=self._pick_color
        )
        self._color_btn.pack(side="left", padx=4)

        # ── Quick-fill from K3 ─────────────────────────────────────────────
        tk.Label(sec2,
            text=" ↑  period auto-fills via Kepler's 3rd law  (P = a^1.5)",
            fg=TEXT_DIM, bg=BG_PANEL, font=FONT_SMALL, wraplength=260,
            justify="left"
        ).pack(anchor="w", padx=8, pady=(2,6))

        # Trace 'a' to auto-update period
        self._params["a"].trace_add("write", self._autofill_period)

        # ── Spawn button ───────────────────────────────────────────────────
        tk.Button(
            panel, text="  ＋  SPAWN BODY",
            font=("Courier New", 10, "bold"),
            bg=GREEN, fg=BG_DARK, activebackground="#2ea043",
            relief="flat", cursor="hand2", pady=6,
            command=self._spawn_body
        ).grid(row=row, column=0, sticky="ew", padx=10, pady=(8, 4)); row += 1

        # ── Simulation controls ────────────────────────────────────────────
        sec3 = self._section(panel, "SIMULATION", row); row += 1

        ctrl = tk.Frame(sec3, bg=BG_PANEL)
        ctrl.pack(fill="x", padx=8, pady=4)

        self._play_btn = tk.Button(
            ctrl, text="▶  PLAY", font=FONT_MONO,
            bg=ACCENT, fg=BG_DARK, activebackground="#79c0ff",
            relief="flat", cursor="hand2", width=10,
            command=self._toggle_animation
        )
        self._play_btn.pack(side="left", padx=(0, 4))

        tk.Button(
            ctrl, text="⟳  RESET", font=FONT_MONO,
            bg=BG_WIDGET, fg=TEXT_MAIN, activebackground=BORDER,
            relief="flat", cursor="hand2", width=10,
            command=self._reset_time
        ).pack(side="left")

        # Speed slider
        spd_row = tk.Frame(sec3, bg=BG_PANEL)
        spd_row.pack(fill="x", padx=8, pady=(4,2))
        tk.Label(spd_row, text="Speed (days/tick)", fg=TEXT_DIM,
                 bg=BG_PANEL, font=FONT_LABEL).pack(side="left")
        self._speed_var = tk.IntVar(value=self.DAYS_PER_TICK)
        tk.Scale(
            spd_row, from_=1, to=100, orient="horizontal",
            variable=self._speed_var,
            bg=BG_PANEL, fg=TEXT_MAIN, troughcolor=BG_WIDGET,
            highlightthickness=0, bd=0, font=FONT_SMALL,
            showvalue=True, length=130
        ).pack(side="left", padx=6)

        # Trail length slider
        trail_row = tk.Frame(sec3, bg=BG_PANEL)
        trail_row.pack(fill="x", padx=8, pady=(0,6))
        tk.Label(trail_row, text="Trail length (days)", fg=TEXT_DIM,
                 bg=BG_PANEL, font=FONT_LABEL).pack(side="left")
        self._trail_var = tk.IntVar(value=self.TRAIL_DAYS)
        tk.Scale(
            trail_row, from_=0, to=365*10, orient="horizontal",
            variable=self._trail_var,
            bg=BG_PANEL, fg=TEXT_MAIN, troughcolor=BG_WIDGET,
            highlightthickness=0, bd=0, font=FONT_SMALL,
            showvalue=True, length=110
        ).pack(side="left", padx=6)

        # Time display
        self._time_label = tk.Label(
            sec3, text="t = 0.0000 yr",
            fg=ACCENT, bg=BG_PANEL, font=("Courier New", 11, "bold")
        )
        self._time_label.pack(pady=(0, 6))

        # ── Body list ──────────────────────────────────────────────────────
        sec4 = self._section(panel, "ACTIVE BODIES", row); row += 1

        list_frame = tk.Frame(sec4, bg=BG_PANEL)
        list_frame.pack(fill="both", expand=True, padx=8, pady=(0,6))

        scrollbar = tk.Scrollbar(list_frame, bg=BG_WIDGET)
        scrollbar.pack(side="right", fill="y")

        self._body_listbox = tk.Listbox(
            list_frame, font=FONT_SMALL,
            bg=BG_WIDGET, fg=TEXT_MAIN,
            selectbackground=ACCENT, selectforeground=BG_DARK,
            relief="flat", bd=0, highlightthickness=0,
            yscrollcommand=scrollbar.set,
            height=8,
        )
        self._body_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._body_listbox.yview)

        tk.Button(
            sec4, text="✕  REMOVE SELECTED",
            font=FONT_SMALL,
            bg=BG_WIDGET, fg=ACCENT2, activebackground=BORDER,
            relief="flat", cursor="hand2",
            command=self._remove_selected_body
        ).pack(fill="x", padx=8, pady=(0,8))

        # ── Footer ────────────────────────────────────────────────────────
        tk.Frame(panel, bg=BORDER, height=1).grid(row=row, column=0, sticky="ew"); row += 1
        tk.Label(
            panel, text="Engine: C (Newton-Raphson)  |  GUI: Python/Tk",
            fg=TEXT_DIM, bg=BG_PANEL, font=("Courier New", 7)
        ).grid(row=row, column=0, pady=6)

    def _build_canvas(self):
        """Embed a matplotlib figure into the right side of the window."""
        canvas_frame = tk.Frame(self, bg=BG_DARK)
        canvas_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.fig, self.ax = plt.subplots(figsize=(7, 7), facecolor=BG_DARK)
        self.ax.set_facecolor(BG_DARK)
        self._setup_axes()

        self.canvas = FigureCanvasTkAgg(self.fig, master=canvas_frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.canvas.draw()

    def _setup_axes(self):
        ax = self.ax
        ax.set_facecolor(BG_DARK)
        ax.tick_params(colors=TEXT_DIM, labelsize=7)
        for spine in ax.spines.values():
            spine.set_edgecolor(BORDER)
        ax.set_xlabel("x  (AU)", color=TEXT_DIM, fontsize=8, fontfamily="monospace")
        ax.set_ylabel("y  (AU)", color=TEXT_DIM, fontsize=8, fontfamily="monospace")
        ax.set_title("Kepler Orbit Simulator", color=TEXT_MAIN,
                     fontsize=10, fontfamily="monospace", pad=8)
        ax.set_aspect("equal")
        ax.grid(True, color=BORDER, linestyle="--", alpha=0.35, linewidth=0.5)
        ax.set_xlim(-12, 12)
        ax.set_ylim(-12, 12)

    def _draw_sun(self):
        self.ax.plot(0, 0, "o", color=SUN_COLOR, markersize=12,
                     zorder=10, label="Sun", markeredgewidth=0)
        # Soft glow
        for r, a in [(18, 0.06), (12, 0.10), (7, 0.18)]:
            self.ax.plot(0, 0, "o", color=SUN_COLOR, markersize=r,
                         alpha=a, zorder=9, markeredgewidth=0)
        self.canvas.draw_idle()

    # ── Helper widget builders ─────────────────────────────────────────────

    def _section(self, parent, title, grid_row):
        """Return a labelled section frame, already grid-placed."""
        wrapper = tk.Frame(parent, bg=BG_PANEL)
        wrapper.grid(row=grid_row, column=0, sticky="ew", padx=0, pady=0)
        wrapper.columnconfigure(0, weight=1)

        hdr = tk.Frame(wrapper, bg=BG_WIDGET)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"  {title}", font=("Courier New", 8, "bold"),
                 fg=TEXT_DIM, bg=BG_WIDGET, anchor="w", pady=3
                 ).pack(fill="x")
        return wrapper

    def _add_param_row(self, parent, label, key, kind, default):
        row = tk.Frame(parent, bg=BG_PANEL)
        row.pack(fill="x", padx=8, pady=2)
        tk.Label(row, text=label, fg=TEXT_DIM, bg=BG_PANEL,
                 font=FONT_LABEL, width=22, anchor="w").pack(side="left")
        var = tk.StringVar(value=default)
        self._params[key] = var
        entry = tk.Entry(
            row, textvariable=var, font=FONT_MONO,
            bg=BG_WIDGET, fg=TEXT_MAIN, insertbackground=ACCENT,
            relief="flat", bd=4, width=10
        )
        entry.pack(side="left", fill="x", expand=True)

    def _style_ttk(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox",
            fieldbackground=BG_WIDGET, background=BG_WIDGET,
            foreground=TEXT_MAIN, selectbackground=ACCENT,
            selectforeground=BG_DARK, font=FONT_MONO,
            bordercolor=BORDER, arrowcolor=TEXT_DIM,
        )

    # ── Parameter helpers ─────────────────────────────────────────────────

    def _autofill_period(self, *_):
        """Auto-fill period via Kepler's 3rd law: P = a^1.5 (in solar units)."""
        # Only auto-fill when in "Custom" preset mode
        if self._preset_var.get() not in ("── Custom ──", ""):
            return
        try:
            a = float(self._params["a"].get())
            if a > 0:
                self._params["period"].set(f"{a**1.5:.4f}")
        except ValueError:
            pass

    def _on_preset_selected(self, _event=None):
        name = self._preset_var.get()
        if name == "── Custom ──":
            return
        preset = Body.PRESETS.get(name)
        if not preset:
            return
        self._params["name"].set(name)
        self._params["a"].set(str(preset["a"]))
        self._params["e"].set(str(preset["e"]))
        self._params["period"].set(str(preset["period"]))
        self._params["M0"].set("0.0")
        self._next_color = preset["color"]
        self._color_btn.configure(bg=self._next_color)

    def _pick_color(self):
        color = colorchooser.askcolor(
            color=self._next_color, title="Choose body color"
        )
        if color and color[1]:
            self._next_color = color[1]
            self._color_btn.configure(bg=self._next_color)

    # ── Body management ───────────────────────────────────────────────────

    def _parse_params(self):
        """Parse and validate current UI parameter values. Returns dict or raises."""
        errors = []
        out = {}

        out["name"] = self._params["name"].get().strip() or "Body"

        for key, label in [("a","Semi-major axis"), ("e","Eccentricity"),
                            ("period","Period"), ("M0","Initial mean anomaly")]:
            try:
                out[key] = float(self._params[key].get())
            except ValueError:
                errors.append(f"{label}: not a valid number")

        if "a" in out and out["a"] <= 0:
            errors.append("Semi-major axis must be > 0")
        if "e" in out and not (0.0 <= out["e"] < 1.0):
            errors.append("Eccentricity must be in [0, 1)")
        if "period" in out and out["period"] <= 0:
            errors.append("Period must be > 0")

        if errors:
            raise ValueError("\n".join(errors))

        # Convert M0 from degrees to radians
        out["M0"] = math.radians(out["M0"])
        return out

    def _spawn_body(self):
        try:
            p = self._parse_params()
        except ValueError as exc:
            messagebox.showerror("Invalid Parameters", str(exc))
            return

        body = Body(
            name=p["name"], a=p["a"], e=p["e"],
            period=p["period"], M0=p["M0"],
            color=self._next_color,
        )
        self._add_body_to_plot(body)
        self.bodies.append(body)
        self._refresh_body_list()
        self._update_axes_limits()
        self.canvas.draw_idle()

    def _add_body_to_plot(self, body: Body):
        """Create matplotlib artists for a new body."""
        xs, ys = self.engine.full_orbit_trace(body.a, body.e)

        body.orbit_line, = self.ax.plot(
            xs, ys, color=body.color, lw=0.6, alpha=0.25, zorder=2
        )
        body.trail_line, = self.ax.plot(
            [], [], color=body.color, lw=1.2, alpha=0.55, zorder=3
        )
        body.dot, = self.ax.plot(
            [], [], "o", color=body.color,
            markersize=body.marker_size, zorder=6,
            markeredgewidth=0,
        )
        # Initial position
        x0, y0 = self.engine.planet_position(
            self.t_years, body.a, body.e, body.period, body.M0
        )
        body.dot.set_data([x0], [y0])
        body.trail_x = [x0]
        body.trail_y = [y0]

        body.label_text = self.ax.text(
            x0, y0 + 0.15, body.name,
            color=body.color, fontsize=6.5,
            fontfamily="monospace", zorder=7, alpha=0.85
        )

    def _remove_selected_body(self):
        sel = self._body_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        body = self.bodies[idx]
        # Remove artists
        for artist in (body.orbit_line, body.trail_line,
                       body.dot, body.label_text):
            if artist is not None:
                artist.remove()
        self.bodies.pop(idx)
        self._refresh_body_list()
        self._update_axes_limits()
        self.canvas.draw_idle()

    def _refresh_body_list(self):
        self._body_listbox.delete(0, tk.END)
        for b in self.bodies:
            self._body_listbox.insert(
                tk.END,
                f"  {b.name:<12}  a={b.a:.3f}AU  e={b.e:.3f}  P={b.period:.3f}yr"
            )

    def _update_axes_limits(self):
        if not self.bodies:
            self.ax.set_xlim(-12, 12)
            self.ax.set_ylim(-12, 12)
            return
        max_reach = max(b.a * (1 + b.e) for b in self.bodies)
        lim = max(max_reach * 1.15, 1.5)
        self.ax.set_xlim(-lim, lim)
        self.ax.set_ylim(-lim, lim)

    # ── Animation ─────────────────────────────────────────────────────────

    def _toggle_animation(self):
        if self.running:
            self._stop_animation()
        else:
            self._start_animation()

    def _start_animation(self):
        self.running = True
        self._play_btn.configure(text="⏸  PAUSE", bg=ACCENT2)
        self._tick()

    def _stop_animation(self):
        self.running = False
        self._play_btn.configure(text="▶  PLAY", bg=ACCENT)
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None

    def _tick(self):
        if not self.running:
            return

        days_per_tick = self._speed_var.get()
        trail_days    = self._trail_var.get()
        dt_years      = days_per_tick / 365.25
        self.t_years += dt_years

        trail_years = trail_days / 365.25

        for body in self.bodies:
            x, y = self.engine.planet_position(
                self.t_years, body.a, body.e, body.period, body.M0
            )
            body.trail_x.append(x)
            body.trail_y.append(y)
            body.dot.set_data([x], [y])

            # Trim trail to max length
            while (len(body.trail_x) > 2 and
                   (len(body.trail_x) * dt_years) > trail_years):
                body.trail_x.pop(0)
                body.trail_y.pop(0)

            body.trail_line.set_data(body.trail_x, body.trail_y)

            # Move label near dot
            if body.label_text is not None:
                body.label_text.set_position((x, y + 0.08))

        self._time_label.configure(text=f"t = {self.t_years:.4f} yr")
        self.canvas.draw_idle()

        self._anim_id = self.after(self.ANIM_INTERVAL, self._tick)

    def _reset_time(self):
        was_running = self.running
        self._stop_animation()
        self.t_years = 0.0
        self._time_label.configure(text="t = 0.0000 yr")
        for body in self.bodies:
            x0, y0 = self.engine.planet_position(
                0.0, body.a, body.e, body.period, body.M0
            )
            body.dot.set_data([x0], [y0])
            body.trail_x = [x0]
            body.trail_y = [y0]
            body.trail_line.set_data([x0], [y0])
            if body.label_text:
                body.label_text.set_position((x0, y0 + 0.08))
        self.canvas.draw_idle()
        if was_running:
            self._start_animation()

    # ── Misc ──────────────────────────────────────────────────────────────

    def _resize_check(self):
        """Keep figure background consistent on resize."""
        self.fig.set_facecolor(BG_DARK)
        self.after(2000, self._resize_check)

    def _on_close(self):
        self._stop_animation()
        self.destroy()
        sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
#  5. Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    try:
        lib = load_kepler_lib()
    except FileNotFoundError as exc:
        # Show a simple error dialog even if Tk isn't running yet
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Library Not Found", str(exc))
        root.destroy()
        sys.exit(1)

    app = OrbitSimApp(lib)

    # Make the window a reasonable starting size
    app.geometry("1180x760")
    app.minsize(900, 600)

    app.mainloop()


if __name__ == "__main__":
    main()


