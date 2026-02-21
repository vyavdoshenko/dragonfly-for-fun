#!/usr/bin/env python3
"""
DOOM Fire Effect — running inside Dragonfly via Lua scripting.

The entire fire physics simulation runs as a Lua script inside Dragonfly.
This client just sends EVAL and renders the result. The database IS the game engine.

Usage:
    pip install redis
    # Start Dragonfly first, then:
    python3 examples/doom_fire.py
"""

import os
import sys
import time

import redis

# The fire palette from the original PSX Doom — 37 colors from black to white
PALETTE = [
    (0x07, 0x07, 0x07),
    (0x1F, 0x07, 0x07),
    (0x2F, 0x0F, 0x07),
    (0x47, 0x0F, 0x07),
    (0x57, 0x17, 0x07),
    (0x67, 0x1F, 0x07),
    (0x77, 0x1F, 0x07),
    (0x8F, 0x27, 0x07),
    (0x9F, 0x2F, 0x07),
    (0xAF, 0x3F, 0x07),
    (0xBF, 0x47, 0x07),
    (0xC7, 0x47, 0x07),
    (0xDF, 0x4F, 0x07),
    (0xDF, 0x57, 0x07),
    (0xDF, 0x57, 0x07),
    (0xD7, 0x5F, 0x07),
    (0xD7, 0x5F, 0x07),
    (0xD7, 0x67, 0x0F),
    (0xCF, 0x6F, 0x0F),
    (0xCF, 0x77, 0x0F),
    (0xCF, 0x7F, 0x0F),
    (0xCF, 0x87, 0x17),
    (0xC7, 0x87, 0x17),
    (0xC7, 0x8F, 0x17),
    (0xC7, 0x97, 0x1F),
    (0xBF, 0x9F, 0x1F),
    (0xBF, 0x9F, 0x1F),
    (0xBF, 0xA7, 0x27),
    (0xBF, 0xA7, 0x27),
    (0xBF, 0xAF, 0x2F),
    (0xB7, 0xAF, 0x2F),
    (0xB7, 0xB7, 0x2F),
    (0xB7, 0xB7, 0x37),
    (0xCF, 0xCF, 0x6F),
    (0xDF, 0xDF, 0x9F),
    (0xEF, 0xEF, 0xC7),
    (0xFF, 0xFF, 0xFF),
]

# All fire physics run inside Dragonfly as a Lua script.
# The grid is a binary string: each byte = pixel intensity (0..36).
# Bottom row = max fire. Each frame, fire propagates upward with random decay.
FIRE_SCRIPT = """
local key = KEYS[1]
local W = tonumber(ARGV[1])
local H = tonumber(ARGV[2])
local N = W * H

local raw = redis.call('GET', key)
local px = {}

if not raw or #raw ~= N then
    for i = 1, N do px[i] = 0 end
    for x = 1, W do px[(H - 1) * W + x] = 36 end
else
    for i = 1, N do px[i] = string.byte(raw, i) end
end

for x = 1, W do
    for y = 2, H do
        local src = (y - 1) * W + x
        local p = px[src]
        if p == 0 then
            px[src - W] = 0
        else
            local r = math.random(0, 3)
            local nx = math.max(1, math.min(W, x - r + 1))
            local dst = (y - 2) * W + nx
            local v = p - (r % 2)
            if v < 0 then v = 0 end
            px[dst] = v
        end
    end
end

local t = {}
for i = 1, N do t[i] = string.char(px[i]) end
local s = table.concat(t)
redis.call('SET', key, s)
return s
"""

KEY = "doom:fire"


def render(data, w, h):
    buf = []
    for y in range(h):
        for x in range(w):
            intensity = data[y * w + x]
            if intensity >= len(PALETTE):
                intensity = len(PALETTE) - 1
            r, g, b = PALETTE[intensity]
            buf.append(f"\033[48;2;{r};{g};{b}m ")
        buf.append("\033[0m\n")
    return "".join(buf)


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 6379

    r = redis.Redis(host=host, port=port)
    r.ping()

    try:
        cols, rows = os.get_terminal_size()
    except OSError:
        cols, rows = 80, 24

    w = min(cols, 120)
    h = min(rows - 3, 50)

    r.delete(KEY)
    print("\033[2J\033[H\033[?25l", end="")  # clear screen, hide cursor
    print(f" DOOM FIRE x DRAGONFLY  --  {w}x{h} pixels computed inside the database")

    try:
        while True:
            data = r.eval(FIRE_SCRIPT, 1, KEY, w, h)
            print(f"\033[2;1H{render(data, w, h)}", end="", flush=True)
            time.sleep(1 / 30)
    except KeyboardInterrupt:
        pass
    finally:
        r.delete(KEY)
        print("\033[?25h\033[0m\033[2J\033[H", end="")  # show cursor, reset, clear
        print("Fire extinguished.")


if __name__ == "__main__":
    main()
