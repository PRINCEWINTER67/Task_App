"""
TASK STATUS TRACKER
====================
Desktop app: color-coded task list synced to a physical Arduino control
panel, with difficulty, exact due time, and a priority score.

HOW TO RUN:
1. pip install customtkinter pyserial   (only needed once)
2. Arduino plugged in with task_light/task_light.ino uploaded
3. python task_app.py

ARDUINO HARDWARE PANEL:
- 4 status LEDs (red/yellow/blue/green): red solid = a task is due within
  the hour (or overdue), red blink = due later today, blue = nearest task
  due tomorrow, yellow = nearest task due later than tomorrow, green =
  nothing pending.
- 16x2 I2C LCD, navigated with an analog joystick: short click toggles
  the screen on/off (doesn't affect the lights' own schedule at all),
  up/down moves between tasks (showing each one's name), left shows
  the total pending count, right shows the selected task's due date.
  Holding the click for 5 seconds is a full shutdown: the LCD shows
  "SHUT DOWN" for 5s then goes dark, and every LED force-off too -
  holding it again for 5s wakes everything back up to its current
  real status immediately.
See task_light/task_light.ino for the full serial protocol and wiring.
"""

import customtkinter as ctk
import tkinter as tk
import json
import os
import math
import time
from datetime import date, datetime, timedelta
from typing import Optional

# ============================================================
# FILES
# ============================================================
SETTINGS_FILE = "settings.json"
TASKS_FILE = "tasks.json"
ARDUINO_BAUD = 9600

DEFAULT_SETTINGS = {
    "arduino_port": "COM4",
    "resync_enabled": True,
    "resync_interval_seconds": 30,
    "time_format": "24h",   # "24h" or "12h" - change anytime in Settings
}

def load_json(path, default):
    """Load JSON from disk, falling back to `default` if the file is
    missing, empty, or corrupted - so a bad save file never crashes the app."""
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not read {path} ({e}). Using defaults.")
            return default.copy() if isinstance(default, dict) else default
        if isinstance(default, dict):
            merged = default.copy()
            merged.update(data)
            return merged
        return data
    return default.copy() if isinstance(default, dict) else default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
tasks = load_json(TASKS_FILE, [])

# ============================================================
# COLOR SCHEME - Midnight indigo
# ============================================================
COLOR_SIDEBAR = "#14141F"
COLOR_MAIN_BG = "#1E1E2E"
COLOR_CARD = "#26263A"
COLOR_TEXT_LIGHT = "#F4F4F8"
COLOR_TEXT_MUTED = "#9A9AB0"

COLOR_BTN_NEUTRAL = "#3A3A45"
COLOR_BTN_NEUTRAL_HOVER = "#55555F"
COLOR_ACCENT_HOVER = "#6373E8"
COLOR_DIFFICULTY_EASY = "#4FBFA8"
COLOR_DIVIDER = "#2A2A3D"

ACCENT_COLOR = "#7C6FF0"
APP_TITLE = "Task Tracker"
BANNER_H = 70  # banner width is dynamic (follows the window), see refresh_home_banner

# Urgency tier colors (used for the task list's colored dots)
TIER_COLORS = {
    "red": "#E85C5C",
    "yellow": "#E8B84B",
    "blue": "#4C8FE8",
    "purple": "#A374E0",
    "done": "#4FBF6B",
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ============================================================
# ARDUINO CONNECTION
# ============================================================
arduino = None

def connect_arduino() -> None:
    global arduino
    try:
        import serial
        arduino = serial.Serial(settings["arduino_port"], ARDUINO_BAUD, timeout=1)
        # Opening the port reboots an Uno/Nano (auto-reset via DTR), and the
        # bootloader eats anything sent in the first ~1-2s - so give it a
        # moment before we start pushing light/task data at it.
        time.sleep(2)
        print(f"Connected to Arduino on {settings['arduino_port']}")
    except Exception as e:
        arduino = None
        print(f"Could not connect to Arduino: {e}")

connect_arduino()

def send_to_arduino(letter: str) -> None:
    if arduino is not None:
        try:
            arduino.write(letter.encode())
        except Exception as e:
            print(f"Failed to send to Arduino: {e}")

# ============================================================
# TASK LOGIC
# ============================================================
def get_due_datetime(task: dict) -> datetime:
    # .get() with fallbacks so a tasks.json saved by an older version of the
    # app (before due_time existed) doesn't crash the whole thing on load
    due_date = task.get("due_date") or date.today().strftime("%Y-%m-%d")
    due_time = task.get("due_time") or "23:59"
    return datetime.strptime(f"{due_date} {due_time}", "%Y-%m-%d %H:%M")

def get_tier(task: dict) -> str:
    """Returns which urgency dot color this task should show."""
    if task.get("done"):
        return "done"
    days_left = (get_due_datetime(task).date() - date.today()).days
    if days_left <= 0:
        return "red"
    elif days_left <= 2:
        return "yellow"
    elif days_left <= 30:
        return "blue"
    else:
        return "purple"

def get_priority_score(task: dict) -> int:
    """1-10 score: mostly how soon it's due, difficulty as a secondary factor."""
    days_left = max(0, (get_due_datetime(task).date() - date.today()).days)
    time_score = max(1, min(10, round(10 - (days_left / 30) * 9)))
    difficulty = task.get("difficulty", 5)
    score = round(time_score * 0.7 + difficulty * 0.3)
    return max(1, min(10, score))

def format_time_for_display(hhmm: str) -> str:
    """Converts internal 24h HH:MM into whatever format Settings has chosen."""
    dt = datetime.strptime(hhmm, "%H:%M")
    if settings["time_format"] == "12h":
        return dt.strftime("%I:%M %p").lstrip("0")
    return dt.strftime("%H:%M")

def parse_time_input(text: str) -> Optional[str]:
    """Parses whatever the user typed, based on current time format setting.
    Returns 24h HH:MM string, or None if invalid."""
    text = text.strip()
    try:
        if settings["time_format"] == "12h":
            dt = datetime.strptime(text.upper(), "%I:%M %p")
        else:
            dt = datetime.strptime(text, "%H:%M")
        return dt.strftime("%H:%M")
    except ValueError:
        return None

def send_line_to_arduino(line: str) -> None:
    send_to_arduino(line + "\n")

# ============================================================
# ARDUINO HARDWARE PANEL (4 status LEDs + a joystick-navigated I2C LCD)
# Separate from the on-screen urgency tiers (get_tier/TIER_COLORS) above -
# the physical light escalates by literal time-to-due rather than the
# app's day-bucketed dots, so "due within the hour" can outrank "due
# today" even though both would show as the same red dot on screen.
# ============================================================
HW_MAX_LCD_TASKS = 6
HW_URGENT_WINDOW = timedelta(hours=1)
HW_LIGHT_PRIORITY = ["solid", "blink", "blue", "yellow"]  # first match wins
HW_LIGHT_CODE = {"solid": "0", "blink": "1", "blue": "2", "yellow": "3"}
HW_LIGHT_CODE_GREEN = "4"

def get_hardware_urgency(task: dict) -> str:
    """Physical-light bucket for one not-done task: 'solid' (due within the
    next hour, or overdue), 'blink' (due later today), 'blue' (due
    tomorrow), or 'yellow' (due later than tomorrow)."""
    due_dt = get_due_datetime(task)
    now = datetime.now()
    if due_dt - now <= HW_URGENT_WINDOW:
        return "solid"
    if due_dt.date() == now.date():
        return "blink"
    if due_dt.date() == now.date() + timedelta(days=1):
        return "blue"
    return "yellow"

def compute_hardware_light_code(pending: list) -> str:
    if not pending:
        return HW_LIGHT_CODE_GREEN
    urgencies = {get_hardware_urgency(t) for t in pending}
    for level in HW_LIGHT_PRIORITY:
        if level in urgencies:
            return HW_LIGHT_CODE[level]
    return HW_LIGHT_CODE_GREEN

def hw_due_label(task: dict) -> str:
    """Compact due label for the 16x2 LCD - always 24h time (independent of
    the Settings time-format toggle) so it reliably fits the fixed field
    the Arduino sketch reserves for it."""
    due_dt = get_due_datetime(task)
    today = date.today()
    if due_dt.date() == today:
        date_part = "Today"
    elif due_dt.date() == today + timedelta(days=1):
        date_part = "Tmrw"
    else:
        date_part = due_dt.strftime("%m-%d")
    return f"{date_part} {due_dt.strftime('%H:%M')}"

def sanitize_for_arduino(text: str, max_len: int) -> str:
    """Strips characters our line protocol can't carry (the '|' field
    separator and newlines), then trims to the Arduino sketch's fixed
    16-char field width."""
    cleaned = (text or "").replace("|", "/").replace("\n", " ").replace("\r", " ")
    return cleaned[:max_len]

def update_arduino_light() -> None:
    """Pushes light state and the LCD task list to the Arduino. Called
    after every task add/complete/delete and on resync."""
    pending = [t for t in tasks if not t.get("done")]

    send_line_to_arduino(f"L:{compute_hardware_light_code(pending)}")

    lcd_tasks = sorted(pending, key=get_due_datetime)[:HW_MAX_LCD_TASKS]
    send_line_to_arduino(f"N:{len(lcd_tasks)}")
    for t in lcd_tasks:
        name = sanitize_for_arduino(t.get("name", "Untitled"), 16)
        due = sanitize_for_arduino(hw_due_label(t), 16)
        send_line_to_arduino(f"I:{name}|{due}")

# ============================================================
# COLOR HELPERS (for the two built-in animations below)
# ============================================================
def hex_to_rgb01(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4))

def rgb01_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)

def dim(hex_color, factor):
    r, g, b = hex_to_rgb01(hex_color)
    factor = max(0.0, factor)
    return rgb01_to_hex((r * factor, g * factor, b * factor))

def lighten(hex_color, factor):
    """Blends toward white. factor 0 = unchanged, 1 = pure white."""
    r, g, b = hex_to_rgb01(hex_color)
    factor = max(0.0, min(1.0, factor))
    return rgb01_to_hex((r + (1 - r) * factor, g + (1 - g) * factor, b + (1 - b) * factor))

def lerp_hex(hex_a, hex_b, t):
    a = hex_to_rgb01(hex_a)
    b = hex_to_rgb01(hex_b)
    t = max(0.0, min(1.0, t))
    return rgb01_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))

def _draw_gradient_base(canvas, w, h, top_hex, bottom_hex, bands=16):
    """Shared vertical gradient wash used as the base layer for both
    animations below, so the banner always looks intentional, not flat."""
    for i in range(bands):
        t = i / bands
        canvas.create_rectangle(0, h * t, w, h * (t + 1 / bands) + 1,
                                 fill=lerp_hex(top_hex, bottom_hex, t), outline="")

def _draw_glow_dot(canvas, x, y, r, core_hex, halo_hex):
    """A soft dot: dim halo behind a brighter core. Tkinter has no alpha, so
    the halo color is chosen close to the background it sits on instead of
    relying on transparency, which keeps the edge from looking hard-clipped."""
    canvas.create_oval(x - r * 2.4, y - r * 2.4, x + r * 2.4, y + r * 2.4, fill=halo_hex, outline="")
    canvas.create_oval(x - r, y - r, x + r, y + r, fill=core_hex, outline="")

def draw_ambient_banner(canvas, frame, w, h):
    """The home banner's idle animation - a slow, calm pulse in the app's
    accent color. Always running, not tied to any unlockable item."""
    w, h = max(1, int(w)), max(1, int(h))
    canvas.delete("all")
    _draw_gradient_base(canvas, w, h, dim(ACCENT_COLOR, 0.35), dim(ACCENT_COLOR, 0.12))
    cx, cy = w / 2, h / 2
    pulse = (math.sin(math.radians(frame * 3)) + 1) / 2
    max_r = min(w, h) / 1.8 + pulse * (max(w, h) * 0.13)
    layers = 6
    edge_color = dim(ACCENT_COLOR, 0.2)
    for i in range(layers, 0, -1):
        t = i / layers
        r = max_r * t
        shade = lerp_hex(edge_color, lighten(ACCENT_COLOR, 0.1 + 0.2 * pulse), 1 - t)
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=shade, outline="")

def draw_completion_burst(canvas, frame, w, h, max_frames):
    """Short particle burst played once when a task is marked done."""
    w, h = max(1, int(w)), max(1, int(h))
    canvas.delete("all")
    base_hex = TIER_COLORS["done"]
    _draw_gradient_base(canvas, w, h, dim(base_hex, 0.28), dim(base_hex, 0.1))
    cx, cy = w / 2, h / 2
    progress = frame / max(1, max_frames - 1)
    n = 14
    halo = dim(base_hex, 0.3)
    core = lighten(base_hex, 0.2)
    for i in range(n):
        angle = (360 / n) * i
        dist = progress * (w / 2.2)
        x = cx + dist * math.cos(math.radians(angle))
        y = cy + dist * math.sin(math.radians(angle)) * 0.6
        r = max(1, 3.5 * (1 - progress))
        _draw_glow_dot(canvas, x, y, r, core, halo)
    canvas.create_text(w / 2, h / 2, text="Task complete!", fill="white", font=("Segoe UI", 12, "bold"))

# ============================================================
# CENTRAL ANIMATION HEARTBEAT
# One shared timer redraws every registered canvas each tick. A canvas that
# no longer exists (e.g. its page was rebuilt) is silently dropped on the
# next tick - no manual cleanup needed anywhere else in the app.
# ============================================================
ANIMATION_TICK_MS = 100
animated_canvases = []
animation_heartbeat_job = None

def unregister_animated_canvas(canvas):
    global animated_canvases
    animated_canvases = [a for a in animated_canvases if a["canvas"] is not canvas]

def register_animated_canvas(canvas, draw_fn, max_frames=None, on_complete=None):
    unregister_animated_canvas(canvas)
    animated_canvases.append({"canvas": canvas, "draw_fn": draw_fn, "frame": 0,
                               "max_frames": max_frames, "on_complete": on_complete})

def animation_tick():
    global animation_heartbeat_job, animated_canvases
    still_alive = []
    pending_completions = []
    for entry in animated_canvases:
        canvas = entry["canvas"]
        if not canvas.winfo_exists():
            continue
        try:
            entry["draw_fn"](canvas, entry["frame"])
        except Exception as e:
            print(f"Animation draw error (dropping this canvas): {e}")
            continue
        entry["frame"] += 1
        if entry["max_frames"] is not None and entry["frame"] >= entry["max_frames"]:
            if entry.get("on_complete"):
                pending_completions.append(entry["on_complete"])
            continue
        still_alive.append(entry)

    # Commit survivors FIRST, then fire completion callbacks - otherwise a
    # callback that re-registers something (e.g. resuming the ambient
    # animation after a completion burst finishes) would get wiped out by
    # this function's own end-of-tick list assignment.
    animated_canvases = still_alive
    for cb in pending_completions:
        try:
            cb()
        except Exception as e:
            print(f"Animation on_complete error: {e}")

    animation_heartbeat_job = root.after(ANIMATION_TICK_MS, animation_tick)

# ============================================================
# MAIN WINDOW
# ============================================================
root = ctk.CTk()
root.title("Task Status Tracker")
root.geometry("980x650")
root.configure(fg_color=COLOR_MAIN_BG)

# ---------- SIDEBAR ----------
sidebar = ctk.CTkFrame(root, width=220, corner_radius=0, fg_color=COLOR_SIDEBAR)
sidebar.pack(side="left", fill="y")
sidebar.pack_propagate(False)

ctk.CTkLabel(sidebar, text=APP_TITLE, font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
             text_color=COLOR_TEXT_LIGHT).pack(pady=(28, 4), padx=20, anchor="w")
ctk.CTkLabel(sidebar, text="Synced to your Arduino panel", font=ctk.CTkFont(family="Segoe UI", size=11),
             text_color=COLOR_TEXT_MUTED).pack(pady=(0, 18), padx=20, anchor="w")

ctk.CTkFrame(sidebar, height=1, fg_color=COLOR_DIVIDER).pack(fill="x", padx=20, pady=(0, 16))

nav_buttons = {}
def make_nav_button(text, command):
    btn = ctk.CTkButton(
        sidebar, text=text, command=command,
        fg_color="transparent", hover_color="#2A2A3D",
        anchor="w", font=ctk.CTkFont(family="Segoe UI", size=13), height=38, corner_radius=8,
        text_color=COLOR_TEXT_LIGHT
    )
    btn.pack(fill="x", padx=16, pady=2)
    nav_buttons[text] = btn

def set_active_nav(name):
    for text, btn in nav_buttons.items():
        btn.configure(fg_color="#2E2E45" if text == name else "transparent")

# ---------- MAIN AREA ----------
main_area = ctk.CTkFrame(root, fg_color=COLOR_MAIN_BG, corner_radius=0)
main_area.pack(side="right", fill="both", expand=True)

page_title = ctk.CTkLabel(main_area, text="Home", font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"), text_color=COLOR_TEXT_LIGHT)
page_title.pack(anchor="w", padx=35, pady=(30, 15))

content_frame = ctk.CTkFrame(main_area, fg_color="transparent")
content_frame.pack(fill="both", expand=True, padx=35)

# ---------- HOME PAGE ----------
home_frame = ctk.CTkFrame(content_frame, fg_color="transparent")

home_banner_canvas = tk.Canvas(home_frame, height=BANNER_H, bg=COLOR_MAIN_BG, highlightthickness=0)
home_banner_canvas.pack(fill="x", pady=(0, 16))

def refresh_home_banner():
    if not home_banner_canvas.winfo_exists():
        return
    unregister_animated_canvas(home_banner_canvas)

    def draw_it(c, f):
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1 or h <= 1:
            w, h = 680, BANNER_H
        draw_ambient_banner(c, f, w, h)

    draw_it(home_banner_canvas, 0)
    register_animated_canvas(home_banner_canvas, draw_it)

refresh_home_banner()

def play_completion_effect():
    if not home_banner_canvas.winfo_exists():
        return
    max_frames = 15

    def draw_it(c, f):
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1 or h <= 1:
            w, h = 680, BANNER_H
        draw_completion_burst(c, f, w, h, max_frames)

    register_animated_canvas(home_banner_canvas, draw_it, max_frames=max_frames, on_complete=refresh_home_banner)

form_frame = ctk.CTkFrame(home_frame, fg_color=COLOR_CARD, corner_radius=12)
form_frame.pack(fill="x", pady=(0, 20))

inner_form = ctk.CTkFrame(form_frame, fg_color="transparent")
inner_form.pack(padx=15, pady=15, fill="x")

task_entry = ctk.CTkEntry(inner_form, placeholder_text="Task name", width=200)
task_entry.grid(row=0, column=0, padx=5, pady=5)

date_entry = ctk.CTkEntry(inner_form, placeholder_text="YYYY-MM-DD", width=110)
date_entry.grid(row=0, column=1, padx=5, pady=5)
date_entry.insert(0, date.today().strftime("%Y-%m-%d"))

time_entry = ctk.CTkEntry(inner_form, width=100)
time_entry.grid(row=0, column=2, padx=5, pady=5)

def update_time_placeholder():
    if settings["time_format"] == "12h":
        time_entry.configure(placeholder_text="02:30 PM")
    else:
        time_entry.configure(placeholder_text="14:30")

update_time_placeholder()

diff_row = ctk.CTkFrame(inner_form, fg_color="transparent")
diff_row.grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))

ctk.CTkLabel(diff_row, text="Difficulty", text_color=COLOR_TEXT_LIGHT, font=ctk.CTkFont(family="Segoe UI", size=12)).pack(side="left", padx=(0, 8))
difficulty_value_label = ctk.CTkLabel(diff_row, text="5", width=24, font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=TIER_COLORS["yellow"])
difficulty_value_label.pack(side="left", padx=(8, 0))

def difficulty_color(value) -> str:
    value = int(value)
    if value <= 3:
        return COLOR_DIFFICULTY_EASY
    elif value <= 6:
        return TIER_COLORS["yellow"]
    else:
        return TIER_COLORS["red"]

def on_difficulty_change(value):
    v = int(round(value))
    color = difficulty_color(v)
    difficulty_value_label.configure(text=str(v), text_color=color)
    difficulty_slider.configure(progress_color=color, button_color=color, button_hover_color=lighten(color, 0.25))

difficulty_slider = ctk.CTkSlider(diff_row, from_=1, to=10, number_of_steps=9, width=180, command=on_difficulty_change,
                                   fg_color=COLOR_BTN_NEUTRAL, progress_color=COLOR_DIFFICULTY_EASY,
                                   button_color=COLOR_DIFFICULTY_EASY, button_hover_color=lighten(COLOR_DIFFICULTY_EASY, 0.25))
difficulty_slider.set(5)
difficulty_slider.pack(side="left")
on_difficulty_change(5)  # .set() above doesn't fire the command callback - sync colors explicitly

error_label = ctk.CTkLabel(inner_form, text="", text_color=TIER_COLORS["red"])
error_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

list_scroll = ctk.CTkScrollableFrame(home_frame, fg_color="transparent")
list_scroll.pack(fill="both", expand=True)

def draw_urgency_dot(parent, tier):
    """White ring, colored center - the urgency indicator."""
    canvas = tk.Canvas(parent, width=22, height=22, bg=COLOR_CARD, highlightthickness=0)
    canvas.create_oval(1, 1, 21, 21, fill="white", outline="")
    canvas.create_oval(5, 5, 17, 17, fill=TIER_COLORS[tier], outline="")
    return canvas

def refresh_task_list():
    for widget in list_scroll.winfo_children():
        widget.destroy()

    if not tasks:
        ctk.CTkLabel(list_scroll, text="No tasks yet. Add one above.", text_color=COLOR_TEXT_MUTED).pack(pady=20)
        return

    order = sorted(range(len(tasks)), key=lambda i: (tasks[i].get("done", False), -get_priority_score(tasks[i])))

    for i in order:
        task = tasks[i]
        tier = get_tier(task)

        row = ctk.CTkFrame(list_scroll, fg_color=COLOR_CARD, corner_radius=10)
        row.pack(fill="x", pady=6, padx=2)

        dot = draw_urgency_dot(row, tier)
        dot.pack(side="left", padx=(12, 8), pady=10)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, pady=10)

        time_display = format_time_for_display(task.get("due_time") or "23:59")
        title = task.get("name", "Untitled task") + ("  ·  done" if task.get("done") else "")
        ctk.CTkLabel(info, text=title, text_color=COLOR_TEXT_LIGHT, font=ctk.CTkFont(family="Segoe UI", size=13), anchor="w").pack(anchor="w")
        subtitle = f"due {task.get('due_date', 'unknown date')} at {time_display}   ·   difficulty {task.get('difficulty', 5)}/10"
        if not task.get("done"):
            subtitle += f"   ·   priority {get_priority_score(task)}/10"
        ctk.CTkLabel(info, text=subtitle, text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family="Segoe UI", size=11), anchor="w").pack(anchor="w")

        if not task.get("done"):
            ctk.CTkButton(row, text="Mark done", width=90, height=28, fg_color=ACCENT_COLOR, hover_color=COLOR_ACCENT_HOVER,
                          command=lambda i=i: mark_done(i)).pack(side="right", padx=8, pady=8)
        ctk.CTkButton(row, text="Delete", width=70, height=28, fg_color=COLOR_BTN_NEUTRAL, hover_color=COLOR_BTN_NEUTRAL_HOVER,
                      command=lambda i=i: delete_task(i)).pack(side="right", padx=5, pady=8)

def add_task():
    name = task_entry.get().strip()
    due = date_entry.get().strip()
    time_raw = time_entry.get().strip()
    difficulty = int(round(difficulty_slider.get()))
    error_label.configure(text="")

    if not name or not due or not time_raw:
        error_label.configure(text="Fill in the task name, date, and time.")
        return
    try:
        datetime.strptime(due, "%Y-%m-%d")
    except ValueError:
        error_label.configure(text="Date must be in YYYY-MM-DD format.")
        return

    parsed_time = parse_time_input(time_raw)
    if parsed_time is None:
        expected = "02:30 PM" if settings["time_format"] == "12h" else "14:30"
        error_label.configure(text=f"Time must look like {expected}.")
        return

    tasks.append({"name": name, "due_date": due, "due_time": parsed_time, "difficulty": difficulty, "done": False})
    save_json(TASKS_FILE, tasks)
    task_entry.delete(0, "end")
    time_entry.delete(0, "end")
    difficulty_slider.set(5)
    on_difficulty_change(5)
    refresh_task_list()
    update_arduino_light()

def mark_done(index):
    tasks[index]["done"] = True
    save_json(TASKS_FILE, tasks)
    refresh_task_list()
    update_arduino_light()
    error_label.configure(text="Nice work - task complete!", text_color=TIER_COLORS["done"])
    play_completion_effect()

def delete_task(index):
    tasks.pop(index)
    save_json(TASKS_FILE, tasks)
    refresh_task_list()
    update_arduino_light()

add_task_button = ctk.CTkButton(inner_form, text="Add Task", command=add_task, fg_color=ACCENT_COLOR,
                                 hover_color=COLOR_ACCENT_HOVER, width=100)
add_task_button.grid(row=0, column=3, padx=5)

# ---------- HISTORY PAGE ----------
history_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
history_scroll = ctk.CTkScrollableFrame(history_frame, fg_color="transparent")
history_scroll.pack(fill="both", expand=True)

def refresh_history():
    for widget in history_scroll.winfo_children():
        widget.destroy()
    done_tasks = [t for t in tasks if t.get("done")]
    if not done_tasks:
        ctk.CTkLabel(history_scroll, text="No completed tasks yet.", text_color=COLOR_TEXT_MUTED).pack(pady=20)
        return
    for task in done_tasks:
        row = ctk.CTkFrame(history_scroll, fg_color=COLOR_CARD, corner_radius=10)
        row.pack(fill="x", pady=6, padx=2)
        dot = draw_urgency_dot(row, "done")
        dot.pack(side="left", padx=(12, 8), pady=10)
        ctk.CTkLabel(row, text=f"{task.get('name', 'Untitled task')}   ·   was due {task.get('due_date', 'unknown date')}",
                     text_color=COLOR_TEXT_LIGHT).pack(side="left", pady=10)

# ---------- SETTINGS PAGE ----------
settings_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
settings_card = ctk.CTkFrame(settings_frame, fg_color=COLOR_CARD, corner_radius=12)
settings_card.pack(fill="x", pady=10)
inner_settings = ctk.CTkFrame(settings_card, fg_color="transparent")
inner_settings.pack(padx=20, pady=20, fill="x")

def label(text, row):
    ctk.CTkLabel(inner_settings, text=text, text_color=COLOR_TEXT_LIGHT, font=ctk.CTkFont(family="Segoe UI", weight="bold")).grid(row=row, column=0, sticky="w", pady=8)

def make_filter_dropdown(parent, values, variable, on_change, width=150):
    """A CTkOptionMenu restyled to match the app's dark palette - the
    library default is a bright blue that clashes with the accent color."""
    return ctk.CTkOptionMenu(
        parent, values=values, variable=variable, width=width,
        command=lambda _v: on_change(),
        fg_color=COLOR_CARD, button_color=COLOR_BTN_NEUTRAL, button_hover_color=COLOR_BTN_NEUTRAL_HOVER,
        dropdown_fg_color=COLOR_CARD, dropdown_hover_color=COLOR_BTN_NEUTRAL,
        text_color=COLOR_TEXT_LIGHT, dropdown_text_color=COLOR_TEXT_LIGHT,
        font=ctk.CTkFont(family="Segoe UI", size=12)
    )

label("Arduino port", 0)
port_entry = ctk.CTkEntry(inner_settings, width=120)
port_entry.grid(row=0, column=1, sticky="w", padx=10)
port_entry.insert(0, settings["arduino_port"])

label("Re-sync light every (seconds)", 1)
interval_entry = ctk.CTkEntry(inner_settings, width=120)
interval_entry.grid(row=1, column=1, sticky="w", padx=10)
interval_entry.insert(0, str(settings["resync_interval_seconds"]))

resync_switch_var = tk.BooleanVar(value=settings["resync_enabled"])
label("Enable auto re-sync", 2)
ctk.CTkSwitch(inner_settings, text="", variable=resync_switch_var,
              progress_color=ACCENT_COLOR, button_color="#D8D8E0").grid(row=2, column=1, sticky="w", padx=10)

label("Time format", 3)
time_format_var = tk.StringVar(value=settings["time_format"])
time_format_menu = make_filter_dropdown(inner_settings, ["24h", "12h"], time_format_var, lambda: None, width=120)
time_format_menu.grid(row=3, column=1, sticky="w", padx=10)

settings_status = ctk.CTkLabel(inner_settings, text="", text_color=ACCENT_COLOR)
settings_status.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))

resync_job_id = None

def schedule_resync():
    global resync_job_id
    update_arduino_light()
    resync_job_id = root.after(settings["resync_interval_seconds"] * 1000, schedule_resync)

def apply_settings():
    global resync_job_id, arduino
    try:
        interval = int(interval_entry.get().strip())
        if interval < 5:
            settings_status.configure(text="Interval must be at least 5 seconds.")
            return
    except ValueError:
        settings_status.configure(text="Interval must be a number.")
        return

    new_port = port_entry.get().strip()
    port_changed = new_port != settings["arduino_port"]

    settings["arduino_port"] = new_port
    settings["resync_interval_seconds"] = interval
    settings["resync_enabled"] = resync_switch_var.get()
    settings["time_format"] = time_format_var.get()
    save_json(SETTINGS_FILE, settings)
    update_time_placeholder()

    status_msg = "Settings saved."
    if port_changed:
        if arduino is not None:
            try:
                arduino.close()
            except Exception:
                pass
        connect_arduino()
        status_msg += "  Arduino connected." if arduino is not None else "  Couldn't connect on that port - check it and try again."

    if resync_job_id is not None:
        root.after_cancel(resync_job_id)
        resync_job_id = None
    if settings["resync_enabled"]:
        schedule_resync()

    settings_status.configure(text=status_msg)
    refresh_task_list()

save_settings_button = ctk.CTkButton(inner_settings, text="Save settings", command=apply_settings,
                                      fg_color=ACCENT_COLOR, hover_color=COLOR_ACCENT_HOVER)
save_settings_button.grid(row=5, column=0, pady=(15, 0), sticky="w")

# ---------- NAV LOGIC ----------
def hide_all():
    home_frame.pack_forget()
    history_frame.pack_forget()
    settings_frame.pack_forget()

def show_home():
    hide_all()
    home_frame.pack(fill="both", expand=True)
    page_title.configure(text="Home")
    set_active_nav("Home")
    refresh_task_list()

def show_history():
    hide_all()
    history_frame.pack(fill="both", expand=True)
    page_title.configure(text="History")
    set_active_nav("History")
    refresh_history()

def show_settings():
    hide_all()
    settings_frame.pack(fill="both", expand=True)
    page_title.configure(text="Settings")
    set_active_nav("Settings")

make_nav_button("Home", show_home)
make_nav_button("History", show_history)
make_nav_button("Settings", show_settings)

if settings["resync_enabled"]:
    schedule_resync()

animation_tick()
show_home()
root.mainloop()
