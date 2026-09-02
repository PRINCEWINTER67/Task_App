"""
TASK STATUS TRACKER
====================
Desktop app: color-coded task list synced to an Arduino LED, with
difficulty, exact due time, a priority score, an XP/Level/Tier progression
system (Wood -> Void), and a big Market/Customize cosmetics system.

HOW TO RUN:
1. pip install customtkinter pyserial   (only needed once)
2. Arduino plugged in with task_light.ino uploaded
3. python task_app.py

WHAT'S NEW IN THIS VERSION:
- Player Level system: XP -> Level -> Tier (Wood through Void), shown in the
  sidebar with a progress bar and an animated tier banner.
- 57-item Market across 4 categories (Backgrounds, Frames, Titles, Effects)
  and 6 rarities (Common -> Primordial). Common/Rare/Epic/Legendary cost
  coins (Legendary also needs a minimum tier); Mythic needs a 7-day
  completion streak; Primordial needs 150 lifetime completions. Neither of
  the last two can be bought with coins at all.
- Customize page (Titles sub-tab + Cosmetics sub-tab) to equip anything
  you've already unlocked.
- Anti-farm ledger: completing the exact same task (same name + due date)
  more than once only pays out coins/XP/streak/completions the first time,
  so delete-and-redo can't be used to inflate rewards.
- Old save files still work: coins/XP carry over automatically, and a
  one-time migration maps any previously-owned accent theme onto its
  closest new Background item.
"""

import customtkinter as ctk
import tkinter as tk
import json
import os
import math
import random
import colorsys
from datetime import date, datetime
from typing import Optional, Tuple

# ============================================================
# FILES
# ============================================================
SETTINGS_FILE = "settings.json"
TASKS_FILE = "tasks.json"
STATE_FILE = "user_state.json"
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

# ============================================================
# ITEM CATALOG - Market items across 4 categories x 6 rarities
# ============================================================
def _item(id_, name, category, rarity, is_default=False, **extra):
    d = {"id": id_, "name": name, "category": category, "rarity": rarity, "is_default": is_default}
    d.update(extra)
    return d

ITEM_CATALOG = [
    # ---------------- BACKGROUNDS (16) ----------------
    # effect: solid (Common) -> drift -> pulse -> cycle -> drift_cycle -> primordial_combo
    _item("bg_slate", "Slate", "background", "common", is_default=True, accent="#7C6FF0", effect="solid"),
    _item("bg_midnight", "Midnight", "background", "common", accent="#4C5FE8", effect="solid"),
    _item("bg_parchment", "Parchment", "background", "common", accent="#C9A876", effect="solid"),
    _item("bg_drifting_dust", "Drifting Dust", "background", "rare", accent="#4FBFA8", effect="drift"),
    _item("bg_ocean_current", "Ocean Current", "background", "rare", accent="#4C8FE8", effect="drift"),
    _item("bg_static_fuzz", "Static Fuzz", "background", "rare", accent="#9A9AB0", effect="drift"),
    _item("bg_ember_glow", "Ember Glow", "background", "epic", accent="#E8795C", effect="pulse"),
    _item("bg_frostbite", "Frostbite", "background", "epic", accent="#8FD9F0", effect="pulse"),
    _item("bg_neon_pulse", "Neon Pulse", "background", "epic", accent="#E85C9E", effect="pulse"),
    _item("bg_aurora_veil", "Aurora Veil", "background", "legendary", accent="#A374E0", effect="cycle"),
    _item("bg_molten_core", "Molten Core", "background", "legendary", accent="#E8B84B", effect="cycle"),
    _item("bg_starfall", "Starfall", "background", "legendary", accent="#C4C9D1", effect="cycle"),
    _item("bg_bloodmoon", "Bloodmoon", "background", "mythic", accent="#C0304A", effect="drift_cycle"),
    _item("bg_eclipse", "Eclipse", "background", "mythic", accent="#6B5CE0", effect="drift_cycle"),
    _item("bg_genesis", "Genesis", "background", "primordial", accent="#7C6FF0", effect="primordial_combo"),
    _item("bg_the_void_itself", "The Void Itself", "background", "primordial", accent="#2A1B3D", effect="primordial_combo"),

    # ---------------- FRAMES (10) ----------------
    # ring_style: thin (Common) -> thick -> glow -> animated
    _item("frame_plain_ring", "Plain Ring", "frame", "common", is_default=True, ring_color="#9A9AB0", ring_style="thin"),
    _item("frame_stitched_edge", "Stitched Edge", "frame", "common", ring_color="#C9A876", ring_style="thin"),
    _item("frame_copper_coil", "Copper Coil", "frame", "rare", ring_color="#B08D57", ring_style="thick"),
    _item("frame_sapphire_trim", "Sapphire Trim", "frame", "rare", ring_color="#4C8FE8", ring_style="thick"),
    _item("frame_runed_circle", "Runed Circle", "frame", "epic", ring_color="#A374E0", ring_style="glow"),
    _item("frame_emberline", "Emberline", "frame", "epic", ring_color="#E8795C", ring_style="glow"),
    _item("frame_golden_halo", "Golden Halo", "frame", "legendary", ring_color="#E8C34B", ring_style="glow"),
    _item("frame_frozen_crown", "Frozen Crown", "frame", "legendary", ring_color="#8FD9F0", ring_style="glow"),
    _item("frame_bloodforged_ring", "Bloodforged Ring", "frame", "mythic", ring_color="#C0304A", ring_style="animated"),
    _item("frame_voidframe", "Voidframe", "frame", "primordial", ring_color="#8A6FE0", ring_style="animated"),

    # ---------------- TITLES (22) ----------------
    _item("title_beginner", "Beginner", "title", "common", is_default=True),
    _item("title_list_maker", "List Maker", "title", "common"),
    _item("title_getting_started", "Getting Started", "title", "common"),
    _item("title_organized", "Organized", "title", "common"),
    _item("title_task_slayer", "Task Slayer", "title", "rare"),
    _item("title_deadline_dodger", "Deadline Dodger", "title", "rare"),
    _item("title_grinder", "Grinder", "title", "rare"),
    _item("title_on_track", "On Track", "title", "rare"),
    _item("title_overachiever", "Overachiever", "title", "epic"),
    _item("title_relentless", "Relentless", "title", "epic"),
    _item("title_streak_keeper", "Streak Keeper", "title", "epic"),
    _item("title_focus_master", "Focus Master", "title", "epic"),
    _item("title_unstoppable", "Unstoppable", "title", "legendary"),
    _item("title_time_bender", "Time Bender", "title", "legendary"),
    _item("title_elite_operative", "Elite Operative", "title", "legendary"),
    _item("title_deadline_ghost", "Deadline Ghost", "title", "legendary"),
    _item("title_mythforged", "Mythforged", "title", "mythic"),
    _item("title_chrono_breaker", "Chrono Breaker", "title", "mythic"),
    _item("title_the_undefeated", "The Undefeated", "title", "mythic"),
    _item("title_primordial_being", "Primordial Being", "title", "primordial"),
    _item("title_voidwalker", "Voidwalker", "title", "primordial"),
    _item("title_beyond_mortal", "Beyond Mortal", "title", "primordial"),

    # ---------------- COMPLETION EFFECTS (9) ----------------
    # style: flash -> burst / ripple -> confetti -> crack -> collapse
    _item("fx_simple_flash", "Simple Flash", "effect", "common", is_default=True, style="flash"),
    _item("fx_soft_fade", "Soft Fade", "effect", "common", style="flash"),
    _item("fx_spark_burst", "Spark Burst", "effect", "rare", style="burst"),
    _item("fx_ripple_pulse", "Ripple Pulse", "effect", "rare", style="ripple"),
    _item("fx_confetti_pop", "Confetti Pop", "effect", "epic", style="confetti"),
    _item("fx_ember_trail", "Ember Trail", "effect", "epic", style="burst"),
    _item("fx_lightning_crack", "Lightning Crack", "effect", "legendary", style="crack"),
    _item("fx_blood_moon_flare", "Blood Moon Flare", "effect", "mythic", style="ripple"),
    _item("fx_void_collapse", "Void Collapse", "effect", "primordial", style="collapse"),
]

ITEMS_BY_ID = {item["id"]: item for item in ITEM_CATALOG}
ITEMS_BY_CATEGORY = {}
for _it in ITEM_CATALOG:
    ITEMS_BY_CATEGORY.setdefault(_it["category"], []).append(_it)
DEFAULT_ITEM_ID = {item["category"]: item["id"] for item in ITEM_CATALOG if item.get("is_default")}

# ============================================================
# STATE (coins, XP, ownership, equipped items, anti-farm ledger)
# ============================================================
DEFAULT_STATE = {
    "coins": 0,
    "xp": 0,
    "owned_items": list(DEFAULT_ITEM_ID.values()),
    "equipped": dict(DEFAULT_ITEM_ID),
    "completion_ledger": [],       # "name|due_date" keys that already paid out once
    "current_streak": 0,
    "longest_streak": 0,
    "last_completion_date": None,  # ISO date string
    "total_completions": 0,        # only counts fresh (non-repeat) completions
}

state = load_json(STATE_FILE, DEFAULT_STATE)

# One-time migration: old THEMES-based unlocked_themes/active_theme -> new items.
# The hexes below match the old THEMES dict exactly, so this is lossless for
# anyone who bought/equipped one of the old 5 colors.
_OLD_THEME_TO_NEW_BG = {
    "indigo": "bg_slate",
    "teal": "bg_drifting_dust",
    "coral": "bg_ember_glow",
    "rose": "bg_neon_pulse",
    "amber": "bg_molten_core",
}

def migrate_legacy_theme_state():
    legacy_unlocked = state.get("unlocked_themes")
    legacy_active = state.get("active_theme")
    if not legacy_unlocked and not legacy_active:
        return
    for old_name in (legacy_unlocked or []):
        new_id = _OLD_THEME_TO_NEW_BG.get(old_name)
        if new_id and new_id not in state["owned_items"]:
            state["owned_items"].append(new_id)
    if legacy_active:
        new_active = _OLD_THEME_TO_NEW_BG.get(legacy_active)
        if new_active:
            state["equipped"]["background"] = new_active
    state.pop("unlocked_themes", None)
    state.pop("active_theme", None)
    save_json(STATE_FILE, state)

migrate_legacy_theme_state()

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
COLOR_CARD_ELEVATED = "#2C2C42"   # sidebar stat card - one step brighter than the sidebar itself
COLOR_DIVIDER = "#2A2A3D"         # hairline separators between sidebar zones
COLOR_TEXT_FAINT = "#6E6E85"      # tertiary/caption text, dimmer than COLOR_TEXT_MUTED

PROFILE_NAME = "Exodus"

# Urgency tier colors (unrelated to Market rarity - these are the task dots)
TIER_COLORS = {
    "red": "#E85C5C",
    "yellow": "#E8B84B",
    "blue": "#4C8FE8",
    "purple": "#A374E0",
    "done": "#4FBF6B",
}

RARITY_COLORS = {
    "common": "#9A9AB0",
    "rare": "#4C8FE8",
    "epic": "#A374E0",
    "legendary": "#E8C34B",
    "mythic": "#E85C5C",
    "primordial": "#E85C9E",
}

# Fixed-size UI element dimensions
AVATAR_SIZE = 72
TIER_PANEL_W, TIER_PANEL_H = 164, 50
SWATCH_W, SWATCH_H = 60, 34
BANNER_H = 70  # banner width is dynamic (follows the window), see refresh_home_banner

def get_equipped_item(category: str) -> dict:
    item_id = state.get("equipped", {}).get(category)
    item = ITEMS_BY_ID.get(item_id)
    if item is not None:
        return item
    return ITEMS_BY_ID[DEFAULT_ITEM_ID[category]]

def owns_item(item_id: str) -> bool:
    return item_id in state["owned_items"]

def get_accent() -> str:
    return get_equipped_item("background").get("accent", "#7C6FF0")

# ============================================================
# LEVEL / TIER SYSTEM
# ============================================================
LEVEL_XP_BASE = 50
LEVEL_XP_GROWTH = 1.06  # each level costs 6% more XP than the last

# (min_level, max_level, name, banner_hex, readable_text_hex)
LEVEL_TIERS = [
    (1, 5, "Wood", "#8B6F47", "#C9A876"),
    (6, 10, "Bronze", "#C08552", "#E0A875"),
    (11, 16, "Iron", "#8C9296", "#C7CCD1"),
    (17, 23, "Silver", "#C7CCD1", "#E8EAEE"),
    (24, 31, "Gold", "#E8C34B", "#F5D876"),
    (32, 40, "Platinum", "#7FE0D0", "#A8F0E5"),
    (41, 50, "Diamond", "#6FC9F0", "#9EDCF5"),
    (51, 65, "Ascended", "#B98CF0", "#D0B3F5"),
    (66, 80, "Primordial", "#F06BA8", "#F599C4"),
    (81, 10**9, "Void", "#1A1028", "#C9A8F0"),
]
TIER_ORDER = [t[2] for t in LEVEL_TIERS]

TIER_EFFECT_STYLE = {
    "Wood": "solid", "Bronze": "solid", "Iron": "solid", "Silver": "solid",
    "Gold": "pulse", "Platinum": "pulse",
    "Diamond": "cycle", "Ascended": "cycle",
    "Primordial": "primordial_combo", "Void": "primordial_combo",
}

def get_tier_for_level(level: int):
    for lo, hi, name, banner_hex, text_hex in LEVEL_TIERS:
        if lo <= level <= hi:
            return name, banner_hex, text_hex
    last = LEVEL_TIERS[-1]
    return last[2], last[3], last[4]

def get_level_progress(total_xp) -> dict:
    """Level 1 starts at 0 XP; each level needs more XP than the last."""
    total_xp = max(0, int(total_xp))
    level = 1
    cumulative = 0
    while True:
        cost = max(1, round(LEVEL_XP_BASE * (LEVEL_XP_GROWTH ** level)))
        if total_xp < cumulative + cost or level > 500:
            xp_into_level = max(0, total_xp - cumulative)
            tier_name, tier_hex, tier_text_hex = get_tier_for_level(level)
            return {
                "level": level,
                "xp_into_level": xp_into_level,
                "xp_needed": cost,
                "tier_name": tier_name,
                "tier_hex": tier_hex,
                "tier_text_hex": tier_text_hex,
            }
        cumulative += cost
        level += 1

def tier_at_least(current_tier_name: str, required_tier_name: str) -> bool:
    try:
        return TIER_ORDER.index(current_tier_name) >= TIER_ORDER.index(required_tier_name)
    except ValueError:
        return False

# ============================================================
# UNLOCK / PURCHASE RULES
# ============================================================
RARITY_COST = {"common": 40, "rare": 120, "epic": 300, "legendary": 650}
LEGENDARY_MIN_TIER = "Gold"
MYTHIC_STREAK_REQUIRED = 7
PRIMORDIAL_MILESTONE_REQUIRED = 150

def get_item_requirement_text(item: dict) -> str:
    """Short, action-first label used on the unlock button itself."""
    if item.get("is_default"):
        return "Starter"
    rarity = item["rarity"]
    if rarity in RARITY_COST:
        text = f"Unlock \u2014 {RARITY_COST[rarity]}c"
        if rarity == "legendary":
            text += f" + {LEGENDARY_MIN_TIER}"
        return text
    if rarity == "mythic":
        return f"Unlock \u2014 {MYTHIC_STREAK_REQUIRED}d streak"
    if rarity == "primordial":
        return f"Unlock \u2014 {PRIMORDIAL_MILESTONE_REQUIRED} done"
    return "Locked"

def can_unlock_item(item: dict) -> Tuple[bool, str]:
    rarity = item["rarity"]
    if rarity in RARITY_COST:
        cost = RARITY_COST[rarity]
        coins_ok = state["coins"] >= cost
        tier_ok = True
        tier_msg = ""
        if rarity == "legendary":
            current_tier = get_level_progress(state["xp"])["tier_name"]
            tier_ok = tier_at_least(current_tier, LEGENDARY_MIN_TIER)
            tier_msg = f"reach {LEGENDARY_MIN_TIER} tier"
        if coins_ok and tier_ok:
            return True, ""
        missing = []
        if not tier_ok:
            missing.append(tier_msg)
        if not coins_ok:
            missing.append(f"{cost - state['coins']} more coins")
        return False, "Need " + " and ".join(missing)
    if rarity == "mythic":
        have = state.get("current_streak", 0)
        if have >= MYTHIC_STREAK_REQUIRED:
            return True, ""
        return False, f"Need a {MYTHIC_STREAK_REQUIRED}-day streak (currently {have})"
    if rarity == "primordial":
        have = state.get("total_completions", 0)
        if have >= PRIMORDIAL_MILESTONE_REQUIRED:
            return True, ""
        return False, f"Need {PRIMORDIAL_MILESTONE_REQUIRED} total completions (currently {have})"
    return False, "Unknown rarity"

def unlock_item(item_id: str) -> Tuple[bool, str]:
    """Buys+equips an unowned item if requirements are met, or just equips
    an already-owned one. Returns (success, message)."""
    item = ITEMS_BY_ID.get(item_id)
    if item is None:
        return False, "Unknown item."
    if owns_item(item_id):
        state["equipped"][item["category"]] = item_id
        save_json(STATE_FILE, state)
        return True, f"Equipped {item['name']}."
    can, reason = can_unlock_item(item)
    if not can:
        return False, reason
    if item["rarity"] in RARITY_COST:
        state["coins"] -= RARITY_COST[item["rarity"]]
    state["owned_items"].append(item_id)
    state["equipped"][item["category"]] = item_id
    save_json(STATE_FILE, state)
    return True, f"Unlocked and equipped {item['name']}!"

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

def update_arduino_light() -> None:
    tiers = [get_tier(t) for t in tasks if not t.get("done")]
    if "red" in tiers:
        send_to_arduino("R")
    elif "yellow" in tiers:
        send_to_arduino("Y")
    elif len(tasks) > 0 and all(t.get("done") for t in tasks):
        send_to_arduino("G")
    # blue/purple-only tasks don't change the light

def make_ledger_key(task: dict) -> str:
    name = (task.get("name") or "").strip().lower()
    due_date = task.get("due_date") or ""
    return f"{name}|{due_date}"

def update_streak() -> None:
    """Call once per FRESH (non-repeat) completion. Advances the daily streak."""
    today_str = date.today().isoformat()
    last = state.get("last_completion_date")
    if last == today_str:
        pass  # already counted today
    elif last is not None:
        try:
            last_date = datetime.strptime(last, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            last_date = None
        if last_date is not None and (date.today() - last_date).days == 1:
            state["current_streak"] = state.get("current_streak", 0) + 1
        else:
            state["current_streak"] = 1
    else:
        state["current_streak"] = 1
    state["last_completion_date"] = today_str
    state["longest_streak"] = max(state.get("longest_streak", 0), state["current_streak"])

def award_for_completion(task: dict) -> Tuple[int, int, bool]:
    """Coins and XP scale with how hard AND how urgent the task was.
    Returns (xp_gain, coin_gain, already_claimed). Repeated completions of the
    exact same task (same name+due date - e.g. via delete-and-redo) are logged
    in a ledger and pay 0 the second time, so coins/XP/streaks/milestones
    can't be farmed by re-adding the same task over and over."""
    key = make_ledger_key(task)
    already_claimed = key in state["completion_ledger"]

    if already_claimed:
        xp_gain, coin_gain = 0, 0
    else:
        difficulty = task.get("difficulty", 5)
        priority = get_priority_score(task)
        xp_gain = difficulty * 2 + priority * 2
        coin_gain = xp_gain // 2
        state["xp"] += xp_gain
        state["coins"] += coin_gain
        state["completion_ledger"].append(key)
        state["total_completions"] = state.get("total_completions", 0) + 1
        update_streak()

    save_json(STATE_FILE, state)
    return xp_gain, coin_gain, already_claimed

# ============================================================
# COLOR HELPERS (for animated effects)
# ============================================================
def hex_to_rgb01(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4))

def rgb01_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)

def shift_hue(hex_color, degrees):
    r, g, b = hex_to_rgb01(hex_color)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    return rgb01_to_hex(colorsys.hsv_to_rgb(h, s, v))

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

# ============================================================
# BACKGROUND / TIER EFFECT DRAWING
# ============================================================
def _draw_gradient_base(canvas, w, h, top_hex, bottom_hex, bands=16):
    """Shared vertical gradient wash used as the base layer for every effect,
    so even 'quiet' tiers look intentional instead of a flat color fill."""
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

def draw_effect_solid(canvas, frame, base_hex, w, h):
    canvas.delete("all")
    _draw_gradient_base(canvas, w, h, lighten(base_hex, 0.06), dim(base_hex, 0.5))

def draw_effect_drift(canvas, frame, base_hex, w, h):
    canvas.delete("all")
    _draw_gradient_base(canvas, w, h, dim(base_hex, 0.4), dim(base_hex, 0.15))
    halo = dim(base_hex, 0.3)
    core = lighten(base_hex, 0.25)
    n_dots = 11
    for i in range(n_dots):
        speed = 0.5 + (i % 5) * 0.12
        x = (frame * speed + i * (w / n_dots)) % (w + 20) - 10
        y = (i * 37 + int(frame * 0.25)) % h
        r = 1.6 + (i % 3) * 0.7
        _draw_glow_dot(canvas, x, y, r, core, halo)

def draw_effect_pulse(canvas, frame, base_hex, w, h):
    canvas.delete("all")
    _draw_gradient_base(canvas, w, h, dim(base_hex, 0.35), dim(base_hex, 0.12))
    cx, cy = w / 2, h / 2
    pulse = (math.sin(math.radians(frame * 3)) + 1) / 2
    max_r = min(w, h) / 1.8 + pulse * (max(w, h) * 0.13)
    layers = 6
    edge_color = dim(base_hex, 0.2)
    for i in range(layers, 0, -1):
        t = i / layers
        r = max_r * t
        shade = lerp_hex(edge_color, lighten(base_hex, 0.1 + 0.2 * pulse), 1 - t)
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=shade, outline="")

def draw_effect_cycle(canvas, frame, base_hex, w, h):
    canvas.delete("all")
    hue_shift = (frame * 1.2) % 360
    top_c = shift_hue(base_hex, hue_shift)
    bottom_c = shift_hue(base_hex, hue_shift + 45)
    _draw_gradient_base(canvas, w, h, dim(top_c, 0.5), dim(bottom_c, 0.28), bands=20)
    band_x = (frame * 1.4) % (w + 160) - 80
    band_base = dim(top_c, 0.45)
    layers = 4
    for i in range(layers, 0, -1):
        t = i / layers
        rx, ry = 65 * t, h * 0.7 * t
        shade = lerp_hex(band_base, lighten(top_c, 0.28), 1 - t)
        canvas.create_oval(band_x - rx, h / 2 - ry, band_x + rx, h / 2 + ry, fill=shade, outline="")

def draw_effect_drift_cycle(canvas, frame, base_hex, w, h):
    hue_shift = (frame * 1.0) % 360
    cycled = shift_hue(base_hex, hue_shift)
    draw_effect_drift(canvas, frame, cycled, w, h)

def draw_effect_primordial_combo(canvas, frame, base_hex, w, h):
    canvas.delete("all")
    hue_shift = (frame * 0.8) % 360
    base = shift_hue(base_hex, hue_shift)
    _draw_gradient_base(canvas, w, h, dim(base, 0.32), dim(base, 0.1))
    cx, cy = w / 2, h / 2
    pulse = (math.sin(math.radians(frame * 4)) + 1) / 2
    core_r = 6 + pulse * (min(w, h) / 4)
    _draw_glow_dot(canvas, cx, cy, core_r, lighten(base, 0.35), dim(base, 0.4))
    n_dots = 8
    for i in range(n_dots):
        speed = 0.45 + (i % 4) * 0.18
        x = (frame * speed + i * (w / n_dots)) % (w + 20) - 10
        y = (i * 29 + int(frame * 0.35)) % h
        rr = 1.3 + (i % 3) * 0.6
        particle_hex = shift_hue(base, i * 22)
        _draw_glow_dot(canvas, x, y, rr, lighten(particle_hex, 0.2), dim(particle_hex, 0.35))

EFFECT_DRAW_FUNCTIONS = {
    "solid": draw_effect_solid,
    "drift": draw_effect_drift,
    "pulse": draw_effect_pulse,
    "cycle": draw_effect_cycle,
    "drift_cycle": draw_effect_drift_cycle,
    "primordial_combo": draw_effect_primordial_combo,
}

def draw_background_effect(canvas, frame, item, w, h):
    w, h = max(1, int(w)), max(1, int(h))
    style = item.get("effect", "solid")
    fn = EFFECT_DRAW_FUNCTIONS.get(style, draw_effect_solid)
    fn(canvas, frame, item.get("accent", "#7C6FF0"), w, h)

def draw_tier_banner_content(canvas, frame, level, tier_name, tier_hex, tier_text_hex, w, h):
    w, h = max(1, int(w)), max(1, int(h))
    style = TIER_EFFECT_STYLE.get(tier_name, "solid")
    fn = EFFECT_DRAW_FUNCTIONS.get(style, draw_effect_solid)
    fn(canvas, frame, tier_hex, w, h)
    canvas.create_text(w / 2, h / 2, text=f"{tier_name.upper()} \u00b7 Lv.{level}",
                        fill=tier_text_hex, font=("Segoe UI", 11, "bold"))

# ============================================================
# COMPLETION EFFECT DRAWING (short bursts, played on task completion)
# ============================================================
def draw_fx_flash(canvas, frame, base_hex, w, h, max_frames):
    canvas.delete("all")
    progress = frame / max(1, max_frames - 1)
    alpha_like = 1 - progress
    color = dim(base_hex, 0.3 + 0.7 * alpha_like)
    canvas.create_rectangle(0, 0, w, h, fill=color, outline="")
    canvas.create_text(w / 2, h / 2, text="+ TASK COMPLETE +", fill="white", font=("Segoe UI", 12, "bold"))

def draw_fx_burst(canvas, frame, base_hex, w, h, max_frames):
    canvas.delete("all")
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

def draw_fx_ripple(canvas, frame, base_hex, w, h, max_frames):
    canvas.delete("all")
    canvas.create_rectangle(0, 0, w, h, fill=dim(base_hex, 0.15), outline="")
    cx, cy = w / 2, h / 2
    progress = frame / max(1, max_frames - 1)
    for i in range(3):
        p = min(1.0, progress + i * 0.15)
        r = p * (w / 2.2)
        shade = dim(base_hex, max(0.1, 1 - p))
        canvas.create_oval(cx - r, cy - r / 2, cx + r, cy + r / 2, outline=shade, width=2)

def draw_fx_confetti(canvas, frame, base_hex, w, h, max_frames):
    canvas.delete("all")
    canvas.create_rectangle(0, 0, w, h, fill=dim(base_hex, 0.15), outline="")
    progress = frame / max(1, max_frames - 1)
    n = 20
    for i in range(n):
        seed = i * 977
        start_x = seed % w
        fall = progress * h * 1.3
        x = start_x + math.sin(frame * 0.3 + i) * 10
        y = (fall + (seed % h)) % (h + 10) - 5
        color = shift_hue(base_hex, (i * 37) % 360)
        canvas.create_rectangle(x, y, x + 4, y + 4, fill=color, outline="")

def draw_fx_crack(canvas, frame, base_hex, w, h, max_frames):
    canvas.delete("all")
    progress = frame / max(1, max_frames - 1)
    flash = (frame % 2 == 0 and progress < 0.7)
    bg = dim(base_hex, 0.5 if flash else 0.15)
    canvas.create_rectangle(0, 0, w, h, fill=bg, outline="")
    if flash:
        rng = random.Random(frame)  # deterministic per-frame, no test flakiness
        x = w * 0.2
        y = 0.0
        pts = [x, y]
        while y < h:
            x += rng.uniform(-15, 15)
            y += rng.uniform(10, 20)
            pts.extend([x, y])
        if len(pts) >= 4:
            canvas.create_line(*pts, fill="white", width=2)

def draw_fx_collapse(canvas, frame, base_hex, w, h, max_frames):
    canvas.delete("all")
    progress = frame / max(1, max_frames - 1)
    _draw_gradient_base(canvas, w, h, dim(base_hex, 0.28), dim(base_hex, 0.1))
    cx, cy = w / 2, h / 2
    n = 12
    halo = dim(base_hex, 0.3)
    core = lighten(base_hex, 0.2)
    for i in range(n):
        angle = (360 / n) * i
        dist = (1 - progress) * (w / 2.2)
        x = cx + dist * math.cos(math.radians(angle))
        y = cy + dist * math.sin(math.radians(angle)) * 0.6
        r = max(1, 3.5 * progress)
        _draw_glow_dot(canvas, x, y, r, core, halo)
    if progress > 0.85:
        _draw_glow_dot(canvas, cx, cy, 9, lighten(base_hex, 0.6), lighten(base_hex, 0.2))

FX_DRAW_FUNCTIONS = {
    "flash": draw_fx_flash,
    "burst": draw_fx_burst,
    "ripple": draw_fx_ripple,
    "confetti": draw_fx_confetti,
    "crack": draw_fx_crack,
    "collapse": draw_fx_collapse,
}

def draw_completion_effect(canvas, frame, item, w, h, max_frames):
    w, h = max(1, int(w)), max(1, int(h))
    style = item.get("style", "flash")
    fn = FX_DRAW_FUNCTIONS.get(style, draw_fx_flash)
    base_hex = RARITY_COLORS.get(item.get("rarity", "common"), "#9A9AB0")
    fn(canvas, frame, base_hex, w, h, max_frames)

# ============================================================
# AVATAR DRAWING (frame ring + filled circle + initial)
# ============================================================
def draw_avatar(canvas, frame, w, h, accent_hex, initial, frame_item):
    w, h = max(1, int(w)), max(1, int(h))
    canvas.delete("all")
    cx, cy = w / 2, h / 2
    ring_color = frame_item.get("ring_color", "#9A9AB0")
    ring_style = frame_item.get("ring_style", "thin")
    outer_r = min(w, h) / 2 - 2
    inner_r = max(1, outer_r - 10)

    if ring_style == "thin":
        canvas.create_oval(cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r, outline=ring_color, width=2)
    elif ring_style == "thick":
        canvas.create_oval(cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r, outline=ring_color, width=4)
    elif ring_style == "glow":
        # exactly two elements: one soft wide halo, one crisp ring on top -
        # deliberately NOT three overlapping strokes, which read as muddy
        canvas.create_oval(cx - outer_r - 5, cy - outer_r - 5, cx + outer_r + 5, cy + outer_r + 5,
                            outline=dim(ring_color, 0.35), width=6)
        canvas.create_oval(cx - outer_r - 1, cy - outer_r - 1, cx + outer_r + 1, cy + outer_r + 1,
                            outline=ring_color, width=3)
    elif ring_style == "animated":
        start = (frame * 5) % 360
        for k in range(3):
            a0 = start + k * 120
            canvas.create_arc(cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r,
                               start=a0, extent=70, style="arc", outline=ring_color, width=3)
        glow_r = outer_r + 4
        canvas.create_oval(cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r, outline=dim(ring_color, 0.3), width=2)

    canvas.create_oval(cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r, fill=accent_hex, outline="")
    canvas.create_text(cx, cy, text=initial, fill="white", font=("Segoe UI", 20, "bold"))

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
    # callback that re-registers something (e.g. resuming the background
    # animation after a completion effect finishes) would get wiped out by
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

# ---- Zone 1: Identity (who) ----
profile_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
profile_frame.pack(pady=(24, 14))

avatar_canvas = tk.Canvas(profile_frame, width=AVATAR_SIZE, height=AVATAR_SIZE, bg=COLOR_SIDEBAR, highlightthickness=0)
avatar_canvas.pack()

ctk.CTkLabel(profile_frame, text=PROFILE_NAME, font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"), text_color=COLOR_TEXT_LIGHT).pack(pady=(10, 0))

title_label = ctk.CTkLabel(profile_frame, text="", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED)
title_label.pack(pady=(1, 0))

ctk.CTkFrame(sidebar, height=1, fg_color=COLOR_DIVIDER).pack(fill="x", padx=20, pady=(4, 16))

# ---- Zone 2: Progress (one bordered card - level, XP, tier, coins) ----
stat_card = ctk.CTkFrame(sidebar, fg_color=COLOR_CARD_ELEVATED, corner_radius=14,
                          border_width=1, border_color=COLOR_DIVIDER)
stat_card.pack(fill="x", padx=16, pady=(0, 18))

level_label = ctk.CTkLabel(stat_card, text="", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"))
level_label.pack(pady=(14, 6))

xp_bar = ctk.CTkProgressBar(stat_card, width=156, height=7, fg_color=COLOR_SIDEBAR, progress_color="#7C6FF0")
xp_bar.pack(pady=(0, 4))
xp_bar.set(0)

xp_bar_label = ctk.CTkLabel(stat_card, text="", font=ctk.CTkFont(family="Segoe UI", size=10), text_color=COLOR_TEXT_MUTED)
xp_bar_label.pack(pady=(0, 12))

tier_banner_canvas = tk.Canvas(stat_card, width=TIER_PANEL_W, height=TIER_PANEL_H, bg=COLOR_CARD_ELEVATED, highlightthickness=0)
tier_banner_canvas.pack(pady=(0, 10))

ctk.CTkFrame(stat_card, height=1, fg_color=COLOR_DIVIDER).pack(fill="x", padx=14, pady=(0, 8))

coins_label = ctk.CTkLabel(stat_card, text="", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color="#E8C34B")
coins_label.pack(pady=(0, 12))

# ---- Zone 3: Navigation (where) ----
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

def refresh_profile_panel():
    """Redraws avatar, title, level/tier text, XP bar, tier banner, coins."""
    equipped_frame_item = get_equipped_item("frame")
    accent = get_accent()

    unregister_animated_canvas(avatar_canvas)
    draw_avatar(avatar_canvas, 0, AVATAR_SIZE, AVATAR_SIZE, accent, PROFILE_NAME[0], equipped_frame_item)
    if equipped_frame_item.get("ring_style") == "animated":
        register_animated_canvas(
            avatar_canvas,
            lambda c, f: draw_avatar(c, f, AVATAR_SIZE, AVATAR_SIZE, accent, PROFILE_NAME[0], equipped_frame_item)
        )

    title_item = get_equipped_item("title")
    title_label.configure(text=title_item["name"])

    progress = get_level_progress(state["xp"])
    level_label.configure(text=f"Lv. {progress['level']} \u2014 {progress['tier_name']}",
                           text_color=progress["tier_text_hex"])
    xp_bar.configure(progress_color=progress["tier_hex"] if progress["tier_name"] != "Void" else progress["tier_text_hex"])
    xp_bar.set(progress["xp_into_level"] / max(1, progress["xp_needed"]))
    xp_bar_label.configure(text=f"{progress['xp_into_level']} / {progress['xp_needed']} XP")

    coins_label.configure(text=f"{state['coins']} coins")

    unregister_animated_canvas(tier_banner_canvas)
    draw_tier_banner_content(tier_banner_canvas, 0, progress["level"], progress["tier_name"],
                              progress["tier_hex"], progress["tier_text_hex"], TIER_PANEL_W, TIER_PANEL_H)
    if TIER_EFFECT_STYLE.get(progress["tier_name"], "solid") != "solid":
        register_animated_canvas(
            tier_banner_canvas,
            lambda c, f: draw_tier_banner_content(c, f, progress["level"], progress["tier_name"],
                                                   progress["tier_hex"], progress["tier_text_hex"],
                                                   TIER_PANEL_W, TIER_PANEL_H)
        )

    # keep the two "always accent-colored" buttons in sync after an equip change
    try:
        add_task_button.configure(fg_color=accent)
    except NameError:
        pass
    try:
        save_settings_button.configure(fg_color=accent)
    except NameError:
        pass

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
    bg_item = get_equipped_item("background")

    def draw_it(c, f):
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1 or h <= 1:
            w, h = 680, BANNER_H
        draw_background_effect(c, f, bg_item, w, h)

    draw_it(home_banner_canvas, 0)
    if bg_item.get("effect", "solid") != "solid":
        register_animated_canvas(home_banner_canvas, draw_it)

refresh_home_banner()

def play_completion_effect():
    if not home_banner_canvas.winfo_exists():
        return
    effect_item = get_equipped_item("effect")
    max_frames = 15

    def draw_it(c, f):
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1 or h <= 1:
            w, h = 680, BANNER_H
        draw_completion_effect(c, f, effect_item, w, h, max_frames)

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
        title = task.get("name", "Untitled task") + ("  \u00b7  done" if task.get("done") else "")
        ctk.CTkLabel(info, text=title, text_color=COLOR_TEXT_LIGHT, font=ctk.CTkFont(family="Segoe UI", size=13), anchor="w").pack(anchor="w")
        subtitle = f"due {task.get('due_date', 'unknown date')} at {time_display}   \u00b7   difficulty {task.get('difficulty', 5)}/10"
        if not task.get("done"):
            subtitle += f"   \u00b7   priority {get_priority_score(task)}/10"
        ctk.CTkLabel(info, text=subtitle, text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family="Segoe UI", size=11), anchor="w").pack(anchor="w")

        if not task.get("done"):
            ctk.CTkButton(row, text="Mark done", width=90, height=28, fg_color=get_accent(), hover_color=COLOR_ACCENT_HOVER,
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
    xp_before = state["xp"]
    tasks[index]["done"] = True
    xp_gain, coin_gain, already_claimed = award_for_completion(tasks[index])
    save_json(TASKS_FILE, tasks)
    refresh_task_list()
    refresh_profile_panel()
    update_arduino_light()

    if already_claimed:
        error_label.configure(text="Marked done (already rewarded once before for this task).", text_color=COLOR_TEXT_MUTED)
    else:
        level_before = get_level_progress(xp_before)["level"]
        level_after = get_level_progress(state["xp"])["level"]
        msg = f"+{xp_gain} XP, +{coin_gain} coins"
        if level_after > level_before:
            msg += f"  \u2014 LEVEL UP! Now level {level_after}"
        error_label.configure(text=msg, text_color=TIER_COLORS["done"])
        play_completion_effect()

def delete_task(index):
    tasks.pop(index)
    save_json(TASKS_FILE, tasks)
    refresh_task_list()
    update_arduino_light()

add_task_button = ctk.CTkButton(inner_form, text="Add Task", command=add_task, fg_color=get_accent(),
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
        ctk.CTkLabel(row, text=f"{task.get('name', 'Untitled task')}   \u00b7   was due {task.get('due_date', 'unknown date')}",
                     text_color=COLOR_TEXT_LIGHT).pack(side="left", pady=10)

# ---------- MARKET PAGE ----------
market_frame = ctk.CTkFrame(content_frame, fg_color="transparent")

market_filter_row = ctk.CTkFrame(market_frame, fg_color="transparent")
market_filter_row.pack(fill="x", pady=(0, 10))

CATEGORY_LABELS = {"All": "All", "background": "Backgrounds", "frame": "Frames", "title": "Titles", "effect": "Effects"}
CATEGORY_LABEL_TO_KEY = {v: k for k, v in CATEGORY_LABELS.items()}

def make_filter_dropdown(parent, values, variable, on_change, width=150):
    """A CTkOptionMenu restyled to match the app's dark palette - the
    library default is a bright blue that clashes with every accent theme."""
    return ctk.CTkOptionMenu(
        parent, values=values, variable=variable, width=width,
        command=lambda _v: on_change(),
        fg_color=COLOR_CARD, button_color=COLOR_BTN_NEUTRAL, button_hover_color=COLOR_BTN_NEUTRAL_HOVER,
        dropdown_fg_color=COLOR_CARD, dropdown_hover_color=COLOR_BTN_NEUTRAL,
        text_color=COLOR_TEXT_LIGHT, dropdown_text_color=COLOR_TEXT_LIGHT,
        font=ctk.CTkFont(family="Segoe UI", size=12)
    )

ctk.CTkLabel(market_filter_row, text="Category", text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family="Segoe UI", size=12)).pack(side="left", padx=(0, 6))
market_category_var = tk.StringVar(value="All")
market_category_menu = make_filter_dropdown(market_filter_row, list(CATEGORY_LABELS.values()), market_category_var, lambda: refresh_market())
market_category_menu.pack(side="left", padx=(0, 20))

ctk.CTkLabel(market_filter_row, text="Rarity", text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family="Segoe UI", size=12)).pack(side="left", padx=(0, 6))
market_rarity_var = tk.StringVar(value="All")
RARITY_FILTER_LABELS = ["All", "Common", "Rare", "Epic", "Legendary", "Mythic", "Primordial"]
market_rarity_menu = make_filter_dropdown(market_filter_row, RARITY_FILTER_LABELS, market_rarity_var, lambda: refresh_market())
market_rarity_menu.pack(side="left")

market_status = ctk.CTkLabel(market_frame, text="", text_color=TIER_COLORS["red"])
market_status.pack(anchor="w", pady=(0, 6))

market_scroll = ctk.CTkScrollableFrame(market_frame, fg_color="transparent")
market_scroll.pack(fill="both", expand=True)

def attempt_unlock_from_market(item_id):
    success, message = unlock_item(item_id)
    market_status.configure(text=message, text_color=TIER_COLORS["done"] if success else TIER_COLORS["red"])
    if success:
        refresh_profile_panel()
        refresh_home_banner()
    refresh_market()

_RARITY_ORDER_MAP = {"common": 0, "rare": 1, "epic": 2, "legendary": 3, "mythic": 4, "primordial": 5}

def add_rarity_strip(row, rarity, height=48):
    """A thin colored bar on the left edge of a card - rarity is readable
    at a glance without reading the text, consistent across every list.
    Uses an explicit height (not fill='y') since fill='y' inside a
    CTkScrollableFrame stretches the whole row to the scroll cavity height."""
    strip = ctk.CTkFrame(row, width=4, height=height, fg_color=RARITY_COLORS.get(rarity, "#9A9AB0"), corner_radius=2)
    strip.pack(side="left", pady=8)
    strip.pack_propagate(False)

def refresh_market():
    for widget in market_scroll.winfo_children():
        widget.destroy()

    selected_category = CATEGORY_LABEL_TO_KEY.get(market_category_var.get(), "All")
    selected_rarity = market_rarity_var.get().lower()

    filtered = []
    for item in ITEM_CATALOG:
        if selected_category != "All" and item["category"] != selected_category:
            continue
        if selected_rarity != "all" and item["rarity"] != selected_rarity:
            continue
        filtered.append(item)

    if not filtered:
        ctk.CTkLabel(market_scroll, text="No items match that filter.", text_color=COLOR_TEXT_MUTED).pack(pady=20)
        return

    filtered.sort(key=lambda it: (_RARITY_ORDER_MAP.get(it["rarity"], 99), it["name"]))

    for item in filtered:
        row = ctk.CTkFrame(market_scroll, fg_color=COLOR_CARD, corner_radius=10)
        row.pack(fill="x", pady=5, padx=2)
        add_rarity_strip(row, item["rarity"])

        swatch_canvas = tk.Canvas(row, width=SWATCH_W, height=SWATCH_H, bg=COLOR_CARD, highlightthickness=0)
        swatch_canvas.pack(side="left", padx=(10, 10), pady=8)
        preview_frame_val = hash(item["id"]) % 97  # static "random-ish" frame so previews vary
        if item["category"] == "background":
            draw_background_effect(swatch_canvas, preview_frame_val, item, SWATCH_W, SWATCH_H)
        elif item["category"] == "frame":
            mini = min(SWATCH_W, SWATCH_H)
            draw_avatar(swatch_canvas, preview_frame_val, mini, mini, get_accent(), PROFILE_NAME[0], item)
        elif item["category"] == "effect":
            draw_completion_effect(swatch_canvas, 7, item, SWATCH_W, SWATCH_H, 15)  # mid-burst still frame
        else:
            rc = RARITY_COLORS.get(item["rarity"], "#9A9AB0")
            swatch_canvas.create_oval(SWATCH_W / 2 - 10, SWATCH_H / 2 - 10, SWATCH_W / 2 + 10, SWATCH_H / 2 + 10, fill=rc, outline="")

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, pady=8)
        ctk.CTkLabel(info, text=item["name"], text_color=COLOR_TEXT_LIGHT, font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), anchor="w").pack(anchor="w")
        rarity_color = RARITY_COLORS.get(item["rarity"], "#9A9AB0")
        cat_text = CATEGORY_LABELS.get(item["category"], item["category"]).rstrip("s")
        ctk.CTkLabel(info, text=f"{item['rarity'].capitalize()} {cat_text}", text_color=rarity_color, font=ctk.CTkFont(family="Segoe UI", size=11), anchor="w").pack(anchor="w")

        equipped_id = state["equipped"].get(item["category"])
        if owns_item(item["id"]) and equipped_id == item["id"]:
            ctk.CTkLabel(row, text="Equipped", text_color=TIER_COLORS["done"], font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")).pack(side="right", padx=14)
        elif owns_item(item["id"]):
            ctk.CTkButton(row, text="Equip", width=90, height=28, fg_color=get_accent(), hover_color=COLOR_ACCENT_HOVER,
                          command=lambda iid=item["id"]: attempt_unlock_from_market(iid)).pack(side="right", padx=10, pady=8)
        else:
            req_text = get_item_requirement_text(item)
            can, _reason = can_unlock_item(item)
            btn_color = get_accent() if can else COLOR_BTN_NEUTRAL
            btn_hover = COLOR_ACCENT_HOVER if can else COLOR_BTN_NEUTRAL_HOVER
            ctk.CTkButton(row, text=req_text, width=170, height=28, fg_color=btn_color, hover_color=btn_hover,
                          command=lambda iid=item["id"]: attempt_unlock_from_market(iid)).pack(side="right", padx=10, pady=8)

# ---------- CUSTOMIZE PAGE ----------
customize_frame = ctk.CTkFrame(content_frame, fg_color="transparent")

customize_subnav = ctk.CTkFrame(customize_frame, fg_color="transparent")
customize_subnav.pack(fill="x", pady=(0, 12))

customize_sub_buttons = {}
def make_customize_sub_button(text, command):
    btn = ctk.CTkButton(customize_subnav, text=text, command=command, width=110, height=32,
                         fg_color="transparent", hover_color="#2A2A3D", text_color=COLOR_TEXT_LIGHT, corner_radius=8)
    btn.pack(side="left", padx=(0, 8))
    customize_sub_buttons[text] = btn

def set_active_customize_sub(name):
    for text, btn in customize_sub_buttons.items():
        btn.configure(fg_color="#2E2E45" if text == name else "transparent")

customize_titles_subframe = ctk.CTkScrollableFrame(customize_frame, fg_color="transparent")
customize_cosmetics_subframe = ctk.CTkScrollableFrame(customize_frame, fg_color="transparent")

def equip_owned_item(item_id):
    unlock_item(item_id)  # already-owned path always just equips, never charges
    refresh_profile_panel()
    refresh_home_banner()
    if customize_titles_subframe.winfo_ismapped():
        refresh_customize_titles()
    if customize_cosmetics_subframe.winfo_ismapped():
        refresh_customize_cosmetics()

def refresh_customize_titles():
    for widget in customize_titles_subframe.winfo_children():
        widget.destroy()
    owned_titles = [it for it in ITEMS_BY_CATEGORY.get("title", []) if owns_item(it["id"])]
    if not owned_titles:
        ctk.CTkLabel(customize_titles_subframe, text="No titles unlocked yet \u2014 check the Market.", text_color=COLOR_TEXT_MUTED).pack(pady=20)
        return
    owned_titles.sort(key=lambda it: (_RARITY_ORDER_MAP.get(it["rarity"], 99), it["name"]))
    for item in owned_titles:
        row = ctk.CTkFrame(customize_titles_subframe, fg_color=COLOR_CARD, corner_radius=10)
        row.pack(fill="x", pady=5, padx=2)
        add_rarity_strip(row, item["rarity"])
        rarity_color = RARITY_COLORS.get(item["rarity"], "#9A9AB0")
        name_block = ctk.CTkFrame(row, fg_color="transparent")
        name_block.pack(side="left", padx=(12, 10), pady=10)
        ctk.CTkLabel(name_block, text=item["name"], text_color=COLOR_TEXT_LIGHT, font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), anchor="w").pack(anchor="w")
        ctk.CTkLabel(name_block, text=item["rarity"].capitalize(), text_color=rarity_color, font=ctk.CTkFont(family="Segoe UI", size=11), anchor="w").pack(anchor="w")
        if state["equipped"].get("title") == item["id"]:
            ctk.CTkLabel(row, text="Equipped", text_color=TIER_COLORS["done"], font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")).pack(side="right", padx=14)
        else:
            ctk.CTkButton(row, text="Equip", width=80, height=28, fg_color=get_accent(), hover_color=COLOR_ACCENT_HOVER,
                          command=lambda iid=item["id"]: equip_owned_item(iid)).pack(side="right", padx=10, pady=8)

def refresh_customize_cosmetics():
    for widget in customize_cosmetics_subframe.winfo_children():
        widget.destroy()

    for section_i, category in enumerate(("background", "frame", "effect")):
        header_row = ctk.CTkFrame(customize_cosmetics_subframe, fg_color="transparent")
        header_row.pack(fill="x", pady=(18 if section_i else 4, 8))
        ctk.CTkLabel(header_row, text=CATEGORY_LABELS.get(category, category),
                     text_color=COLOR_TEXT_LIGHT, font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold")).pack(side="left")
        ctk.CTkFrame(customize_cosmetics_subframe, height=1, fg_color=COLOR_DIVIDER).pack(fill="x", pady=(0, 8))

        owned = [it for it in ITEMS_BY_CATEGORY.get(category, []) if owns_item(it["id"])]
        owned.sort(key=lambda it: (_RARITY_ORDER_MAP.get(it["rarity"], 99), it["name"]))

        if not owned:
            ctk.CTkLabel(customize_cosmetics_subframe, text="Nothing unlocked yet.", text_color=COLOR_TEXT_FAINT).pack(anchor="w", padx=4, pady=(0, 6))
            continue

        for item in owned:
            row = ctk.CTkFrame(customize_cosmetics_subframe, fg_color=COLOR_CARD, corner_radius=10)
            row.pack(fill="x", pady=4, padx=2)
            add_rarity_strip(row, item["rarity"])

            swatch_canvas = tk.Canvas(row, width=SWATCH_W, height=SWATCH_H, bg=COLOR_CARD, highlightthickness=0)
            swatch_canvas.pack(side="left", padx=(10, 10), pady=8)
            preview_frame_val = hash(item["id"]) % 97
            if category == "background":
                draw_background_effect(swatch_canvas, preview_frame_val, item, SWATCH_W, SWATCH_H)
            elif category == "frame":
                mini = min(SWATCH_W, SWATCH_H)
                draw_avatar(swatch_canvas, preview_frame_val, mini, mini, get_accent(), PROFILE_NAME[0], item)
            elif category == "effect":
                draw_completion_effect(swatch_canvas, 7, item, SWATCH_W, SWATCH_H, 15)
            else:
                rc = RARITY_COLORS.get(item["rarity"], "#9A9AB0")
                swatch_canvas.create_oval(SWATCH_W / 2 - 10, SWATCH_H / 2 - 10, SWATCH_W / 2 + 10, SWATCH_H / 2 + 10, fill=rc, outline="")

            ctk.CTkLabel(row, text=item["name"], text_color=COLOR_TEXT_LIGHT, font=ctk.CTkFont(family="Segoe UI", size=13)).pack(side="left", padx=8)

            if state["equipped"].get(category) == item["id"]:
                ctk.CTkLabel(row, text="Equipped", text_color=TIER_COLORS["done"], font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")).pack(side="right", padx=14)
            else:
                ctk.CTkButton(row, text="Equip", width=80, height=28, fg_color=get_accent(), hover_color=COLOR_ACCENT_HOVER,
                              command=lambda iid=item["id"]: equip_owned_item(iid)).pack(side="right", padx=10, pady=8)

def show_customize_titles():
    customize_cosmetics_subframe.pack_forget()
    customize_titles_subframe.pack(fill="both", expand=True)
    set_active_customize_sub("Titles")
    refresh_customize_titles()

def show_customize_cosmetics():
    customize_titles_subframe.pack_forget()
    customize_cosmetics_subframe.pack(fill="both", expand=True)
    set_active_customize_sub("Cosmetics")
    refresh_customize_cosmetics()

make_customize_sub_button("Titles", show_customize_titles)
make_customize_sub_button("Cosmetics", show_customize_cosmetics)

# ---------- SETTINGS PAGE ----------
settings_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
settings_card = ctk.CTkFrame(settings_frame, fg_color=COLOR_CARD, corner_radius=12)
settings_card.pack(fill="x", pady=10)
inner_settings = ctk.CTkFrame(settings_card, fg_color="transparent")
inner_settings.pack(padx=20, pady=20, fill="x")

def label(text, row):
    ctk.CTkLabel(inner_settings, text=text, text_color=COLOR_TEXT_LIGHT, font=ctk.CTkFont(family="Segoe UI", weight="bold")).grid(row=row, column=0, sticky="w", pady=8)

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
              progress_color=get_accent(), button_color="#D8D8E0").grid(row=2, column=1, sticky="w", padx=10)

label("Time format", 3)
time_format_var = tk.StringVar(value=settings["time_format"])
time_format_menu = make_filter_dropdown(inner_settings, ["24h", "12h"], time_format_var, lambda: None, width=120)
time_format_menu.grid(row=3, column=1, sticky="w", padx=10)

settings_status = ctk.CTkLabel(inner_settings, text="", text_color=get_accent())
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
                                      fg_color=get_accent(), hover_color=COLOR_ACCENT_HOVER)
save_settings_button.grid(row=5, column=0, pady=(15, 0), sticky="w")

# ---------- NAV LOGIC ----------
def hide_all():
    home_frame.pack_forget()
    history_frame.pack_forget()
    market_frame.pack_forget()
    customize_frame.pack_forget()
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

def show_market():
    hide_all()
    market_frame.pack(fill="both", expand=True)
    page_title.configure(text="Market")
    set_active_nav("Market")
    refresh_market()

def show_customize():
    hide_all()
    customize_frame.pack(fill="both", expand=True)
    page_title.configure(text="Customize")
    set_active_nav("Customize")
    show_customize_titles()

def show_settings():
    hide_all()
    settings_frame.pack(fill="both", expand=True)
    page_title.configure(text="Settings")
    set_active_nav("Settings")

make_nav_button("Home", show_home)
make_nav_button("History", show_history)
make_nav_button("Market", show_market)
make_nav_button("Customize", show_customize)
make_nav_button("Settings", show_settings)

refresh_profile_panel()

if settings["resync_enabled"]:
    schedule_resync()

animation_tick()
show_home()
root.mainloop()
