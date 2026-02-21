# dragonfly-for-fun

Games & Demos powered by [Dragonfly](https://www.dragonflydb.io/) Lua scripting.

All game logic runs as Lua scripts inside [Dragonfly](https://github.com/dragonflydb/dragonfly) — a modern, Redis-compatible in-memory data store. The Python clients just send `EVAL` and render the result. The database IS the game engine.

## Prerequisites

- Docker
- Python 3.8+

## Start Dragonfly

```bash
docker run -d --name dragonfly -p 6379:6379 docker.dragonflydb.io/dragonflydb/dragonfly
```

## Install dependencies

```bash
pip install -r requirements.txt
```

## Examples

### 1. Snake (Multiplayer)

A multiplayer snake game. Each player connects from a separate terminal. Dragonfly handles all game logic — movement, collisions, food spawning — in a single atomic Lua script.

```bash
# Terminal 1:
python3 examples/snake.py alice

# Terminal 2 (optional — join the same game):
python3 examples/snake.py bob
```

**Controls:** Arrow keys / WASD to move, Q to quit, R to respawn when dead.

### 2. Game of Life

Conway's Game of Life. The entire simulation (birth, death, survival) runs inside Dragonfly. The client renders the universe using braille characters for high-resolution output.

```bash
python3 examples/game_of_life.py
```

Press `Ctrl+C` to stop.

### 3. Doom Fire

The classic DOOM PSX fire effect. Fire physics are computed inside Dragonfly and rendered with true-color ANSI output.

```bash
python3 examples/doom_fire.py
```

Press `Ctrl+C` to stop.

## Connecting to a remote Dragonfly instance

All examples accept optional host and port arguments:

```bash
python3 examples/snake.py alice 192.168.1.10 6380
python3 examples/game_of_life.py 192.168.1.10 6380
python3 examples/doom_fire.py 192.168.1.10 6380
```

## License

See [LICENSE](LICENSE).
