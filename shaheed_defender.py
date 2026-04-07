"""
shaheed_command.py  —  Missile Command clone
Incoming: Shaheed-136 delta-wing drones. Defend your cities.

pip install textual
python shaheed_command.py

Controls:
  Arrow keys — move targeting cursor
  Space      — fire interceptor missile
  R          — restart (game over screen)
  Q          — quit
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual import events
from textual.widget import Widget
from textual.widgets import Footer
from rich.text import Text

# ── board dimensions ──────────────────────────────────────────────────────────

W = 80    # board width  (chars)
H = 26    # board height (rows, excluding HUD)

BATTERY_X = W // 2
BATTERY_Y = H - 2

CITY_POSITIONS = [8, 18, 28, 52, 62, 72]

# ── backdrop skyline (generated once at import time) ──────────────────────────

def _make_skyline(
    seed: int, max_h: int
) -> tuple[list[tuple[int, int, int]], frozenset[tuple[int, int]]]:
    """Return (buildings, windows) where buildings = [(x, width, height), ...]
    and windows = frozenset of (col, rows_from_ground) interior cell coords."""
    rng = random.Random(seed)
    buildings: list[tuple[int, int, int]] = []
    windows: set[tuple[int, int]] = set()
    x = 0
    while x < W:
        bw = rng.randint(2, 7)
        bh = rng.randint(2, max_h)
        buildings.append((x, bw, bh))
        for rfg in range(1, bh - 1):
            for col in range(x + 1, min(x + bw - 1, W)):
                if rng.random() < 0.20:
                    windows.add((col, rfg))
        x += bw + rng.randint(0, 2)
    return buildings, frozenset(windows)

_SKY_FAR,  _          = _make_skyline(7331,  7)   # distant silhouette tier
_SKY_NEAR, _WIN_NEAR  = _make_skyline(1337, 14)   # taller tier with lit windows

# ── game objects ──────────────────────────────────────────────────────────────

@dataclass
class Drone:
    x: float
    y: float
    vx: float
    vy: float
    alive: bool = True

@dataclass
class Missile:
    x: float
    y: float
    tx: int
    ty: int
    dx: float = 0.0
    dy: float = 0.0
    alive: bool = True

    def __post_init__(self) -> None:
        dist = max(1.0, ((self.tx - self.x)**2 + (self.ty - self.y)**2) ** 0.5)
        spd = 1.4
        self.dx = (self.tx - self.x) / dist * spd
        self.dy = (self.ty - self.y) / dist * spd

@dataclass
class Explosion:
    x: int
    y: int
    r: int       = 0
    max_r: int   = 5
    shrinking: bool = False
    alive: bool  = True
    _t: int      = 0   # sub-tick counter
    rate: int    = 3   # ticks per radius step

    def advance(self) -> None:
        self._t += 1
        if self._t < self.rate:
            return
        self._t = 0
        if not self.shrinking:
            self.r += 1
            if self.r >= self.max_r:
                self.shrinking = True
        else:
            self.r -= 1
            if self.r < 0:
                self.alive = False

@dataclass
class City:
    x: int
    alive: bool = True

# ── game widget ───────────────────────────────────────────────────────────────

class GameBoard(Widget):

    can_focus = True

    def __init__(self) -> None:
        super().__init__()
        self.cx: int = W // 2
        self.cy: int = H // 2
        self._reset()
        self._text = Text()

    # ── state ─────────────────────────────────────────────────────────────────

    def _reset(self) -> None:
        self.drones:     list[Drone]     = []
        self.missiles:   list[Missile]   = []
        self.explosions: list[Explosion] = []
        self.cities:     list[City]      = [City(x) for x in CITY_POSITIONS]
        self.cx:  int = W // 2
        self.cy:  int = H // 2
        self.score:             int  = 0
        self.wave:              int  = 1
        self.ammo:              int  = 30
        self.game_over:         bool = False
        self._ticks:            int  = 0
        self._last_refill_wave: int  = 1

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def render(self) -> Text:
        return self._text

    def on_mount(self) -> None:
        self.set_interval(1 / 20, self._tick)  # 20 fps

    # ── game loop ─────────────────────────────────────────────────────────────

    def _spawn(self) -> None:
        alive = [c for c in self.cities if c.alive]
        if not alive:
            return
        target = random.choice(alive)
        sx = random.uniform(4, W - 4)
        spd = 0.18 + self.wave * 0.025 + random.uniform(-0.02, 0.04)
        dist = max(1.0, ((target.x - sx)**2 + (H - 2)**2) ** 0.5)
        vx = (target.x - sx) / dist * spd + random.uniform(-0.03, 0.03)
        vy = (H - 2) / dist * spd
        self.drones.append(Drone(x=sx, y=0.0, vx=vx, vy=vy))

    def _tick(self) -> None:
        if self.game_over:
            return
        self._ticks += 1

        # ── spawn ──
        interval = max(8, 45 - self.wave * 4)
        count = 1 + self.wave // 4
        if self._ticks % interval == 0:
            for _ in range(random.randint(1, count)):
                self._spawn()

        # ── move player missiles ──
        for m in self.missiles:
            if not m.alive:
                continue
            m.x += m.dx
            m.y += m.dy
            if ((m.x - m.tx)**2 + (m.y - m.ty)**2) ** 0.5 < 1.6:
                self.explosions.append(Explosion(x=m.tx, y=m.ty))
                m.alive = False

        # ── explosions ──
        for exp in self.explosions:
            if not exp.alive:
                continue
            exp.advance()
            for d in self.drones:
                if not d.alive:
                    continue
                if ((d.x - exp.x)**2 + (d.y - exp.y)**2) ** 0.5 <= exp.r + 0.5:
                    d.alive = False
                    self.score += 10

        # ── wave progression + one-time ammo refill per wave ──
        new_wave = 1 + self.score // 150
        if new_wave > self._last_refill_wave:
            self._last_refill_wave = new_wave
            self.ammo = min(30, self.ammo + 5)
        self.wave = new_wave

        # ── move drones ──
        for d in self.drones:
            if not d.alive:
                continue
            d.x += d.vx
            d.y += d.vy
            if d.y >= H - 2:
                for city in self.cities:
                    if city.alive and abs(d.x - city.x) < 3.5:
                        city.alive = False
                        self.explosions.append(
                            Explosion(x=int(d.x), y=H - 2, max_r=4)
                        )
                        break
                d.alive = False  # drone gone regardless

        # ── prune ──
        self.drones     = [o for o in self.drones     if o.alive]
        self.missiles   = [o for o in self.missiles   if o.alive]
        self.explosions = [o for o in self.explosions if o.alive]

        # ── game over ──
        if not any(c.alive for c in self.cities):
            self.game_over = True

        self._draw()

    # ── rendering ─────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        # char grid: (char, style_str)
        blank = (' ', '')
        grid: list[list[tuple[str, str]]] = [
            [blank] * W for _ in range(H)
        ]

        def put(px: float, py: float, glyph: str, color: str = '') -> None:
            ix, iy = int(px), int(py)
            if 0 <= ix < W and 0 <= iy < H:
                grid[iy][ix] = (glyph, color)

        # ── sky gradient / stars ──
        for y in range(H - 3):
            for x in range(0, W, 12 + y % 5):
                put(x + (y * 7) % 11, y, '·', 'bright_black')

        # ── backdrop: diffused city skyline ──
        # Far tier — very dark silhouettes, no windows (too distant)
        for bx, bw, bh in _SKY_FAR:
            top_y = H - 2 - bh
            for row in range(max(0, top_y), H - 2):
                for col in range(bx, min(bx + bw, W)):
                    put(col, row, '▀' if row == top_y else '█', '#0e1b28')

        # Near tier — taller buildings with lit windows and antenna spires
        for bx, bw, bh in _SKY_NEAR:
            top_y = H - 2 - bh
            for row in range(max(0, top_y), H - 2):
                rfg = H - 2 - row
                for col in range(bx, min(bx + bw, W)):
                    if (col, rfg) in _WIN_NEAR:
                        win_color = '#b87020' if (col + rfg) % 3 else '#3a7aaa'
                        put(col, row, '▪', win_color)
                    elif row == top_y:
                        put(col, row, '▀', '#253d55')
                    else:
                        put(col, row, '█', '#162535')
            if bh >= 9 and top_y > 0:
                put(bx + bw // 2, top_y - 1, '╵', '#2a4060')

        # ── ground line ──
        for x in range(W):
            put(x, H - 1, '▄', 'dim green')

        # ── cities ──
        for city in self.cities:
            if city.alive:
                put(city.x - 2, H - 2, '▐', 'bold cyan')
                put(city.x - 1, H - 2, '█', 'bold cyan')
                put(city.x,     H - 2, '█', 'bold cyan')
                put(city.x + 1, H - 2, '█', 'bold cyan')
                put(city.x + 2, H - 2, '▌', 'bold cyan')
                put(city.x,     H - 1, '╨', 'bold cyan')
            else:
                for dx in range(-2, 3):
                    put(city.x + dx, H - 2, '░', 'red')

        # ── battery ──
        put(BATTERY_X - 2, H - 2, '╔', 'yellow')
        put(BATTERY_X - 1, H - 2, '╤', 'yellow')
        put(BATTERY_X,     H - 2, '▲', 'bold bright_yellow')
        put(BATTERY_X + 1, H - 2, '╤', 'yellow')
        put(BATTERY_X + 2, H - 2, '╗', 'yellow')

        # ── explosions (draw before drones so drones appear on top) ──
        exp_chars = ['·', '∘', '○', '◎', '●']
        for exp in self.explosions:
            for dy in range(-exp.r, exp.r + 1):
                for dx in range(-exp.r, exp.r + 1):
                    if dx * dx + dy * dy <= exp.r * exp.r:
                        idx = min(exp.r, len(exp_chars) - 1)
                        style = 'bright_yellow' if not exp.shrinking else 'yellow'
                        put(exp.x + dx, exp.y + dy, exp_chars[idx], style)
            put(exp.x, exp.y, '◉', 'bold white')

        # ── drones: <▼> delta wing shape ──
        for d in self.drones:
            put(d.x - 1, d.y, '╲', 'bold red')
            put(d.x,     d.y, '▼', 'bold bright_red')
            put(d.x + 1, d.y, '╱', 'bold red')
            # exhaust plume
            put(d.x, d.y - 1, '⁘', 'dim yellow')

        # ── player missiles ──
        for m in self.missiles:
            put(m.x, m.y,     '│', 'bold bright_yellow')
            put(m.x, m.y - 1, '╵', 'yellow')

        # ── targeting cursor ──
        put(self.cx - 1, self.cy, '─', 'bright_cyan')
        put(self.cx + 1, self.cy, '─', 'bright_cyan')
        put(self.cx, self.cy - 1, '│', 'bright_cyan')
        put(self.cx, self.cy + 1, '│', 'bright_cyan')
        put(self.cx, self.cy,     '⊕', 'bold bright_cyan')

        # ── assemble Rich Text ──
        t = Text(no_wrap=True)
        for row in grid:
            for ch, st in row:
                t.append(ch, style=st) if st else t.append(ch)
            t.append('\n')

        # ── HUD ──
        if self.game_over:
            t.append('\n')
            t.append('  ╔══════════════════════════════╗\n', style='bold red')
            t.append('  ║        GAME  OVER            ║\n', style='bold red')
            t.append(f'  ║  Final Score: {self.score:<14}║\n', style='bold white')
            t.append(f'  ║  Waves survived: {self.wave - 1:<10}║\n', style='bold white')
            t.append('  ╚══════════════════════════════╝\n', style='bold red')
            t.append('        [R] Restart   [Q] Quit', style='dim')
        else:
            lives = sum(1 for c in self.cities if c.alive)
            ammo_bar = '█' * self.ammo + '░' * (30 - self.ammo)
            t.append(f'  Score: ', style='bold white')
            t.append(f'{self.score:<6}', style='bold green')
            t.append(f'  Wave: ', style='bold white')
            t.append(f'{self.wave:<3}', style='bold yellow')
            t.append(f'  Cities: ', style='bold white')
            t.append(f'{lives}/6  ', style='bold cyan')
            t.append(f'  Ammo[', style='bold white')
            t.append(ammo_bar[:15], style='bold green' if self.ammo > 10 else 'bold red')
            t.append(']  ', style='bold white')
            t.append('[Arrows/Mouse] Aim  [Space/Click] Fire  [Q] Quit', style='dim')

        self._text = t
        self.refresh()

    # ── input ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _grid_pos(ex: int, ey: int) -> tuple[int, int]:
        """Convert widget-relative mouse coords to clamped grid coords.
        Offsets: 1 col left-border + 1 col left-padding, 1 row top-border."""
        col = max(1, min(W - 2, ex - 2))
        row = max(1, min(H - 3, ey - 1))
        return col, row

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self.cx, self.cy = self._grid_pos(event.x, event.y)

    def on_click(self, event: events.Click) -> None:
        self.cx, self.cy = self._grid_pos(event.x, event.y)
        self.fire()

    def move(self, dx: int, dy: int) -> None:
        self.cx = max(1, min(W - 2, self.cx + dx))
        self.cy = max(1, min(H - 3, self.cy + dy))

    def fire(self) -> None:
        if self.game_over or self.ammo <= 0:
            return
        self.ammo -= 1
        self.missiles.append(Missile(
            x=float(BATTERY_X), y=float(BATTERY_Y),
            tx=self.cx, ty=self.cy,
        ))

    def restart(self) -> None:
        self._reset()
        self._draw()


# ── app ───────────────────────────────────────────────────────────────────────

class ShaheedCommand(App):

    CSS = """
    Screen {
        background: #000005;
    }
    GameBoard {
        height: 1fr;
        background: #000010;
        border: tall #001133;
        padding: 0 1;
    }
    Footer {
        background: #0a0a1a;
        color: #444466;
    }
    """

    TITLE = "SHAHEED COMMAND"
    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield GameBoard()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(GameBoard).focus()

    def on_key(self, event: events.Key) -> None:
        board = self.query_one(GameBoard)
        k = event.key
        if   k == "up":    board.move(0, -1)
        elif k == "down":  board.move(0,  1)
        elif k == "left":  board.move(-2, 0)
        elif k == "right": board.move( 2, 0)
        elif k == "space": board.fire()
        elif k == "r" and board.game_over: board.restart()


if __name__ == "__main__":
    ShaheedCommand().run()