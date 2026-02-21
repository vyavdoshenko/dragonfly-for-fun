#!/usr/bin/env python3
"""
Conway's Game of Life — running inside Dragonfly via Lua scripting.

The entire simulation (birth, death, survival) runs as a Lua script inside Dragonfly.
This client just sends EVAL and renders the result. The database IS the universe.

Usage:
    pip install redis
    # Start Dragonfly first, then:
    python3 examples/game_of_life.py
"""

import os
import sys
import time

import redis

# All simulation logic runs inside Dragonfly as a Lua script.
# The grid is a binary string: each byte is 0 (dead) or 1 (alive).
# Rules: alive cell with 2-3 neighbors survives, dead cell with 3 neighbors is born.
LIFE_SCRIPT = """
local key = KEYS[1]
local W = tonumber(ARGV[1])
local H = tonumber(ARGV[2])
local N = W * H

local raw = redis.call('GET', key)
local cur = {}

if not raw or #raw ~= N then
    -- Seed with random ~25% density
    for i = 1, N do
        if math.random(1, 4) == 1 then
            cur[i] = 1
        else
            cur[i] = 0
        end
    end
else
    for i = 1, N do cur[i] = string.byte(raw, i) end
end

-- Compute next generation
local nxt = {}
for y = 0, H - 1 do
    for x = 0, W - 1 do
        local neighbors = 0
        for dy = -1, 1 do
            for dx = -1, 1 do
                if not (dx == 0 and dy == 0) then
                    local nx = (x + dx) % W
                    local ny = (y + dy) % H
                    neighbors = neighbors + cur[ny * W + nx + 1]
                end
            end
        end
        local idx = y * W + x + 1
        local alive = cur[idx]
        if alive == 1 and (neighbors == 2 or neighbors == 3) then
            nxt[idx] = 1
        elseif alive == 0 and neighbors == 3 then
            nxt[idx] = 1
        else
            nxt[idx] = 0
        end
    end
end

local t = {}
for i = 1, N do t[i] = string.char(nxt[i]) end
local s = table.concat(t)
redis.call('SET', key, s)

-- Count alive cells
local pop = 0
for i = 1, N do pop = pop + nxt[i] end

return {s, pop}
"""

KEY = "life:grid"

# Braille-based rendering: each 2x4 block of cells maps to one braille character.
# This gives much higher resolution than simple block characters.
BRAILLE_BASE = 0x2800
# Braille dot positions: (dx, dy) -> bit index
#  0  3
#  1  4
#  2  5
#  6  7
BRAILLE_MAP = {
    (0, 0): 0x01,
    (0, 1): 0x02,
    (0, 2): 0x04,
    (0, 3): 0x40,
    (1, 0): 0x08,
    (1, 1): 0x10,
    (1, 2): 0x20,
    (1, 3): 0x80,
}


def render_braille(data, w, h):
    """Render grid using braille characters — 2x4 cells per character."""
    lines = []
    for cy in range(0, h, 4):
        row = []
        for cx in range(0, w, 2):
            code = BRAILLE_BASE
            for dx in range(2):
                for dy in range(4):
                    x, y = cx + dx, cy + dy
                    if x < w and y < h and data[y * w + x]:
                        code |= BRAILLE_MAP[(dx, dy)]
            row.append(chr(code))
        lines.append("".join(row))
    return "\n".join(lines)


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 6379

    r = redis.Redis(host=host, port=port)
    r.ping()

    try:
        cols, rows = os.get_terminal_size()
    except OSError:
        cols, rows = 80, 24

    # Braille: each char = 2x4 cells, so multiply terminal size
    w = min((cols - 2) * 2, 200)
    h = min((rows - 3) * 4, 160)

    r.delete(KEY)
    print("\033[2J\033[H\033[?25l", end="")  # clear screen, hide cursor

    gen = 0
    try:
        while True:
            result = r.eval(LIFE_SCRIPT, 1, KEY, w, h)
            data, pop = result[0], int(result[1])
            gen += 1
            frame = render_braille(data, w, h)
            status = f" GAME OF LIFE x DRAGONFLY  |  gen {gen}  |  {pop} alive  |  {w}x{h} universe"
            print(f"\033[1;1H\033[K{status}\n{frame}", end="", flush=True)
            time.sleep(1 / 15)
    except KeyboardInterrupt:
        pass
    finally:
        r.delete(KEY)
        print("\033[?25h\033[0m\033[2J\033[H", end="")
        print(f"Universe collapsed after {gen} generations.")


if __name__ == "__main__":
    main()
