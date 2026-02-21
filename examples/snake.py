#!/usr/bin/env python3
"""
Multiplayer Snake — running inside Dragonfly.

All game logic (movement, collision, food) runs as a single Lua EVAL.
Multiple players connect from separate terminals. Dragonfly IS the game server.

Usage:
    pip install redis
    # Terminal 1:
    python3 examples/snake.py alice
    # Terminal 2:
    python3 examples/snake.py bob

Controls: Arrow keys / WASD to move, Q to quit, R to respawn when dead.
"""

import curses
import json
import os
import sys

import redis

# One game tick — ALL logic runs inside Dragonfly.
# Only 2 declared KEYS: game state + tick lock. Player data arrives via ARGV.
# KEYS: [1]=game state, [2]=tick lock
# ARGV: [1]=tick_ms, [2]=board_w, [3]=board_h, [4]=player_name, [5]=direction, [6]=respawn
TICK_SCRIPT = """
local game_key = KEYS[1]
local tick_lock = KEYS[2]

local tick_ms = tonumber(ARGV[1])
local W = tonumber(ARGV[2])
local H = tonumber(ARGV[3])
local pname = ARGV[4]
local pdir = ARGV[5]
local respawn = ARGV[6]

local raw = redis.call('GET', game_key)
local state
if raw then
    state = cjson.decode(raw)
else
    state = {w=W, h=H, food={x=math.random(1,W-2), y=math.random(1,H-2)}, players={}, tick=0}
end

-- Update this player's info (direction, last_seen, respawn)
local found = false
for _, p in ipairs(state.players) do
    if p.name == pname then
        found = true
        p.last_seen = state.tick
        if p.alive then
            local opp = {UP='DOWN', DOWN='UP', LEFT='RIGHT', RIGHT='LEFT'}
            if opp[pdir] ~= p.dir then p.dir = pdir end
        elseif respawn == '1' then
            local sx = math.random(3, W - 3)
            local sy = math.random(3, H - 3)
            p.body = {{x=sx,y=sy},{x=sx-1,y=sy},{x=sx-2,y=sy}}
            p.dir = 'RIGHT'
            p.alive = true
        end
        break
    end
end
if not found then
    local sx = math.random(3, W - 3)
    local sy = math.random(3, H - 3)
    table.insert(state.players, {
        name=pname,
        body={{x=sx,y=sy},{x=sx-1,y=sy},{x=sx-2,y=sy}},
        dir=pdir, score=0, alive=true, last_seen=state.tick
    })
end

-- Check tick lock — only advance simulation once per interval
local should_tick = redis.call('EXISTS', tick_lock) == 0
if should_tick then
    redis.call('SET', tick_lock, '1', 'PX', tick_ms)

    -- Prune disconnected players (not seen for 50+ ticks)
    local keep = {}
    for _, p in ipairs(state.players) do
        if state.tick - (p.last_seen or 0) < 50 then
            table.insert(keep, p)
        end
    end
    state.players = keep

    -- Move alive snakes
    for _, p in ipairs(state.players) do
        if p.alive then
            local hd = p.body[1]
            local nx, ny = hd.x, hd.y
            if p.dir == 'UP' then ny = ny - 1
            elseif p.dir == 'DOWN' then ny = ny + 1
            elseif p.dir == 'LEFT' then nx = nx - 1
            elseif p.dir == 'RIGHT' then nx = nx + 1 end

            if nx < 0 or nx >= W or ny < 0 or ny >= H then
                p.alive = false
            else
                for k = 1, #p.body - 1 do
                    if p.body[k].x == nx and p.body[k].y == ny then
                        p.alive = false
                        break
                    end
                end
            end

            if p.alive then
                table.insert(p.body, 1, {x=nx, y=ny})
                if nx == state.food.x and ny == state.food.y then
                    p.score = p.score + 1
                    state.food = {x=math.random(1,W-2), y=math.random(1,H-2)}
                else
                    table.remove(p.body)
                end
            end
        end
    end

    -- Cross-snake collision
    for i, p1 in ipairs(state.players) do
        if p1.alive then
            for j, p2 in ipairs(state.players) do
                if i ~= j then
                    local hd = p1.body[1]
                    for _, seg in ipairs(p2.body) do
                        if hd.x == seg.x and hd.y == seg.y then
                            p1.alive = false
                            if p2.alive then p2.score = p2.score + 1 end
                            break
                        end
                    end
                end
            end
        end
    end

    state.tick = state.tick + 1
end

local enc = cjson.encode(state)
redis.call('SET', game_key, enc)
return enc
"""

GAME_KEY = "snake:game"
TICK_KEY = "snake:tick"

DIR_KEYS = {
    curses.KEY_UP: "UP",
    curses.KEY_DOWN: "DOWN",
    curses.KEY_LEFT: "LEFT",
    curses.KEY_RIGHT: "RIGHT",
    ord("w"): "UP",
    ord("s"): "DOWN",
    ord("a"): "LEFT",
    ord("d"): "RIGHT",
}

PLAYER_COLORS = [
    curses.COLOR_GREEN,
    curses.COLOR_CYAN,
    curses.COLOR_MAGENTA,
    curses.COLOR_YELLOW,
    curses.COLOR_RED,
    curses.COLOR_BLUE,
]


def safe_addstr(win, y, x, s, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    try:
        win.addnstr(y, x, s, w - x, attr)
    except curses.error:
        pass


def safe_addch(win, y, x, ch, attr=0):
    h, w = win.getmaxyx()
    if 0 <= y < h and 0 <= x < w:
        try:
            win.addch(y, x, ch, attr)
        except curses.error:
            pass


def run(stdscr, name, host, port):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(50)
    curses.start_color()
    curses.use_default_colors()
    for i, c in enumerate(PLAYER_COLORS):
        curses.init_pair(i + 1, c, -1)
    curses.init_pair(len(PLAYER_COLORS) + 1, curses.COLOR_RED, curses.COLOR_RED)

    r = redis.Redis(host=host, port=port)
    r.ping()

    rows, cols = stdscr.getmaxyx()
    bw = min(cols - 2, 60)
    bh = min(rows - 5, 30)
    tick_ms = 100

    direction = "RIGHT"
    want_respawn = "0"

    try:
        while True:
            key = stdscr.getch()
            if key == ord("q"):
                break
            if key in DIR_KEYS:
                direction = DIR_KEYS[key]
            if key == ord("r"):
                want_respawn = "1"

            raw = r.eval(
                TICK_SCRIPT, 2, GAME_KEY, TICK_KEY, tick_ms, bw, bh, name, direction, want_respawn
            )
            want_respawn = "0"

            if not raw:
                continue

            state = json.loads(raw)
            stdscr.erase()

            # Title
            safe_addstr(
                stdscr,
                0,
                0,
                f" SNAKE x DRAGONFLY  |  You: {name}  |  tick {state['tick']}",
                curses.A_BOLD,
            )

            # Border
            for x in range(bw + 2):
                safe_addch(stdscr, 1, x, curses.ACS_HLINE)
                safe_addch(stdscr, bh + 2, x, curses.ACS_HLINE)
            for y in range(1, bh + 3):
                safe_addch(stdscr, y, 0, curses.ACS_VLINE)
                safe_addch(stdscr, y, bw + 1, curses.ACS_VLINE)

            # Food
            fx, fy = int(state["food"]["x"]), int(state["food"]["y"])
            safe_addch(
                stdscr,
                fy + 2,
                fx + 1,
                ord("*"),
                curses.color_pair(len(PLAYER_COLORS) + 1) | curses.A_BOLD,
            )

            # Snakes
            scores = []
            for i, p in enumerate(state["players"]):
                color = curses.color_pair((i % len(PLAYER_COLORS)) + 1)
                tag = " (YOU)" if p["name"] == name else ""
                dead = (
                    "" if p["alive"] else " [dead, R=respawn]" if p["name"] == name else " [dead]"
                )
                scores.append(f"{p['name']}: {p['score']}{tag}{dead}")

                for j, seg in enumerate(p.get("body", [])):
                    sx, sy = int(seg["x"]), int(seg["y"])
                    ch = "@" if j == 0 else "o"
                    attr = color | curses.A_BOLD
                    if not p["alive"]:
                        attr = curses.A_DIM
                        ch = "x" if j == 0 else "."
                    safe_addch(stdscr, sy + 2, sx + 1, ord(ch), attr)

            # Scoreboard
            safe_addstr(stdscr, bh + 3, 0, "  |  ".join(scores))
            safe_addstr(stdscr, bh + 4, 0, " Arrows/WASD=move  Q=quit  R=respawn", curses.A_DIM)

            stdscr.refresh()
    finally:
        # Mark player as gone by not sending updates; pruning will remove them.
        # If we're the only player, clean up immediately.
        raw = r.get(GAME_KEY)
        if raw:
            state = json.loads(raw)
            remaining = [p for p in state.get("players", []) if p["name"] != name]
            if not remaining:
                r.delete(GAME_KEY, TICK_KEY)


def main():
    name = f"p{os.getpid() % 1000}"
    host = "localhost"
    port = 6379

    for a in sys.argv[1:]:
        if a.isdigit():
            port = int(a)
        elif "." in a or a == "localhost":
            host = a
        else:
            name = a

    curses.wrapper(lambda stdscr: run(stdscr, name, host, port))


if __name__ == "__main__":
    main()
