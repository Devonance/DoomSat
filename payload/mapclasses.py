"""What the automap's colours mean, and the grids the payload measures on.

Pulled out of doom_payload so that world_model.py can be imported, and therefore tested, on a machine with
no ViZDoom. Two copies of these numbers would be worse than none: the raster is written with one set and
read with the other, and a mismatch shows up as the pilot walking confidently into a wall.

The order is the merge priority: when two readings land on the same raster pixel, the higher one wins.
"""
NONE, STEP, DOOR, LOCK_RED, LOCK_BLUE, LOCK_YELLOW, LOCKED, EXIT, WALL, BARRIER = range(10)
LOCK_KEY = {LOCK_RED: "red", LOCK_BLUE: "blue", LOCK_YELLOW: "yellow"}
BLOCKING = (WALL, BARRIER, LOCKED)

GRID = 32          # the cell the walk and the planner are measured on (map units)
WPX = 4            # map units per pixel of the world raster the automap is stamped into

# The monster classes the labels buffer can name, in a fixed order so an index can travel in one byte of
# telemetry. The payload reports WHICH class it saw; how dangerous that is comes from
# knowledge/doom_rules.yaml on the ground. Keeping the fact and the judgement apart is the point: the
# payload is an instrument, and "a Baron is worse than a Zombieman" is knowledge a player brings.
ENEMY_CLASSES = ("Zombieman", "ShotgunGuy", "ChaingunGuy", "DoomImp", "Demon", "Spectre", "LostSoul",
                 "Cacodemon", "BaronOfHell", "HellKnight", "Revenant", "Arachnotron", "Fatso",
                 "PainElemental", "Archvile", "WolfensteinSS")
ENEMY_INDEX = {name: i for i, name in enumerate(ENEMY_CLASSES)}
NO_ENEMY = 255
