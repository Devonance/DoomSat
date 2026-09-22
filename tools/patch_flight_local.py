"""One-off patch: the F Prime Doom component's telemetry and status parsing for the local-sensing payload layout."""
import re

# ---- Doom.fpp: telemetry channels
p = "flight/Components/Doom/Doom.fpp"
s = open(p, encoding="utf-8").read()
start = s.index("        telemetry HEALTH: I16 id 0")
end = s.index("        telemetry HUNT_LEFT: U16 id 43")
end = s.index("\n", end) + 1
new_tlm = """        telemetry HEALTH: I16 id 0
        telemetry ARMOR: I16 id 1
        telemetry SHELLS: I16 id 2
        telemetry BULLETS: I16 id 3
        telemetry WEAPON: Weapon id 4
        telemetry OWN_SHOTGUN: bool id 5
        telemetry KILLS: U16 id 6
        telemetry POS_X: F32 id 7
        telemetry POS_Y: F32 id 8
        telemetry ANGLE: F32 id 9
        telemetry ENEMY_COUNT: U8 id 10
        telemetry ENEMY_BEARING: F32 id 11 @< degrees, positive left
        telemetry ENEMY_DIST: U16 id 12
        telemetry CLEAR_FWD: U16 id 13 @< map units of free space straight ahead (range camera)
        telemetry CLEAR_LEFT: U16 id 14 @< map units of open way to the left (map ray)
        telemetry CLEAR_RIGHT: U16 id 15
        telemetry CLEAR_BACK: U16 id 16
        telemetry CLEAR_FL: U16 id 17 @< range camera, ahead-left band
        telemetry CLEAR_FR: U16 id 18 @< range camera, ahead-right band
        telemetry CLEAR_MAP_FWD: U16 id 19 @< map ray straight ahead
        telemetry NEW_FWD: U8 id 20 @< percent of the ground that way not yet walked
        telemetry NEW_LEFT: U8 id 21
        telemetry NEW_RIGHT: U8 id 22
        telemetry NEW_BACK: U8 id 23
        telemetry AHEAD_KIND: AheadKind id 24 @< what is at arm's length ahead
        telemetry AHEAD_DIST: U16 id 25
        telemetry EXIT_BEARING: F32 id 26 @< degrees to the exit line seen, positive left
        telemetry EXIT_DIST: U16 id 27 @< 0 when no exit line has been seen
        telemetry KEY_BEARING: F32 id 28
        telemetry KEY_DIST: U16 id 29 @< 0 when no key is remembered
        telemetry HEALTH_ITEM_DIST: U16 id 30
        telemetry AMMO_ITEM_DIST: U16 id 31
        telemetry ARMOR_ITEM_DIST: U16 id 32
        telemetry HEALTH_BEARING: F32 id 33
        telemetry AMMO_BEARING: F32 id 34
        telemetry ARMOR_BEARING: F32 id 35
        telemetry STUCK: bool id 36
        telemetry DOOR_AHEAD: bool id 37 @< something usable at arm's length
        telemetry GOAL: Goal id 38
        telemetry TIC: U32 id 39
        telemetry EPISODE: U16 id 40
        telemetry DEAD: bool id 41
        telemetry LEVEL_DONE: bool id 42
        telemetry EXPLORED_CELLS: U16 id 43 @< cells of the self-built map the player has stood in
        telemetry LEVEL: U8 id 44 @< levels started so far (1 = the first map)
        telemetry KEYS: U8 id 45 @< keys held, bitmask red=1 blue=2 yellow=4
        telemetry HINT_ACTIVE: bool id 46 @< an exploration hint from the ground is in force
        telemetry HINT_REL: I16 id 47 @< the hint's bearing relative to the heading, degrees
        telemetry FRAMES_SENT: U32 id 48
        telemetry CHUNKS_SENT: U32 id 49
        telemetry FRAME_BYTES: U32 id 50 @< bytes of the last frame
        telemetry PAYLOAD_LINK: bool id 51
        telemetry CMDS_RECEIVED: U32 id 52
        telemetry FRAME_CHUNK: FrameChunk id 53
"""
s = s[:start] + new_tlm + s[end:]
s = re.sub(r"    @ What the navigator is currently routing toward\n    enum TargetKind : U8 \{.*?\n    \}\n\n", "", s, flags=re.S)
s = re.sub(r"    @ What the onboard navigator is doing\n    enum NavMode : U8 \{.*?\n    \}", """    @ What the range camera and the map say is at arm's length ahead
    enum AheadKind : U8 {
        NOTHING = 0
        WALL = 1
        DOOR = 2
        EXIT = 3           @< The exit line, seen on the automap
        LOCKED = 4         @< A locked door without its key
        BARRIER = 5        @< Something the map does not show (window bars, a fake door)
        THING = 6          @< A monster or a barrel
    }""", s, flags=re.S)
assert "TargetKind" not in s and "NavMode" not in s and "AheadKind" in s
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("fpp ok; channels:", s.count("        telemetry "))

# ---- Doom.cpp: status parsing (STATUS_FMT is 100 bytes, 48 fields)
p = "flight/Components/Doom/Doom.cpp"
s = open(p, encoding="utf-8").read()
s = s.replace("constexpr U16 STATUS_LEN = 76;", "constexpr U16 STATUS_LEN = 100;")
start = s.index("    this->tlmWrite_HEALTH(rdI16(p));")
end = s.index("    if (episode != this->m_lastEpisode) {")
new_parse = """    this->tlmWrite_HEALTH(rdI16(p));
    this->tlmWrite_ARMOR(rdI16(p));
    this->tlmWrite_SHELLS(rdI16(p));
    this->tlmWrite_BULLETS(rdI16(p));
    const U8 weapon = rdU8(p);
    this->tlmWrite_WEAPON(DoomMission::Weapon(static_cast<DoomMission::Weapon::T>(weapon > 3 ? 3 : weapon)));
    this->tlmWrite_OWN_SHOTGUN(rdU8(p) != 0);
    this->tlmWrite_KILLS(rdU16(p));
    this->tlmWrite_POS_X(rdF32(p));
    this->tlmWrite_POS_Y(rdF32(p));
    this->tlmWrite_ANGLE(rdF32(p));
    this->tlmWrite_ENEMY_COUNT(rdU8(p));
    this->tlmWrite_ENEMY_BEARING(rdF32(p));
    this->tlmWrite_ENEMY_DIST(rdU16(p));
    this->tlmWrite_CLEAR_FWD(rdU16(p));
    this->tlmWrite_CLEAR_FL(rdU16(p));
    this->tlmWrite_CLEAR_FR(rdU16(p));
    this->tlmWrite_CLEAR_LEFT(rdU16(p));
    this->tlmWrite_CLEAR_RIGHT(rdU16(p));
    this->tlmWrite_CLEAR_BACK(rdU16(p));
    this->tlmWrite_CLEAR_MAP_FWD(rdU16(p));
    this->tlmWrite_NEW_FWD(rdU8(p));
    this->tlmWrite_NEW_LEFT(rdU8(p));
    this->tlmWrite_NEW_RIGHT(rdU8(p));
    this->tlmWrite_NEW_BACK(rdU8(p));
    const U8 ahead = rdU8(p);
    this->tlmWrite_AHEAD_KIND(DoomMission::AheadKind(static_cast<DoomMission::AheadKind::T>(ahead > 6 ? 0 : ahead)));
    this->tlmWrite_AHEAD_DIST(rdU16(p));
    this->tlmWrite_EXIT_BEARING(rdF32(p));
    this->tlmWrite_EXIT_DIST(rdU16(p));
    this->tlmWrite_KEY_BEARING(rdF32(p));
    this->tlmWrite_KEY_DIST(rdU16(p));
    this->tlmWrite_HEALTH_ITEM_DIST(rdU16(p));
    this->tlmWrite_AMMO_ITEM_DIST(rdU16(p));
    this->tlmWrite_ARMOR_ITEM_DIST(rdU16(p));
    this->tlmWrite_HEALTH_BEARING(rdF32(p));
    this->tlmWrite_AMMO_BEARING(rdF32(p));
    this->tlmWrite_ARMOR_BEARING(rdF32(p));
    this->tlmWrite_STUCK(rdU8(p) != 0);
    this->tlmWrite_DOOR_AHEAD(rdU8(p) != 0);
    const U8 goal = rdU8(p);
    this->tlmWrite_GOAL(DoomMission::Goal(static_cast<DoomMission::Goal::T>(goal > 7 ? 7 : goal)));
    const U32 tic = rdU32(p);
    this->tlmWrite_TIC(tic);
    const U16 episode = rdU16(p);
    this->tlmWrite_EPISODE(episode);
    const bool dead = rdU8(p) != 0;
    const bool done = rdU8(p) != 0;
    this->tlmWrite_DEAD(dead);
    this->tlmWrite_LEVEL_DONE(done);
    this->tlmWrite_EXPLORED_CELLS(rdU16(p));
    const U8 level = rdU8(p);
    this->tlmWrite_LEVEL(level);
    const U8 keys = rdU8(p);
    this->tlmWrite_KEYS(keys);
    this->tlmWrite_HINT_ACTIVE(rdU8(p) != 0);
    this->tlmWrite_HINT_REL(rdI16(p));
    if (level != this->m_lastLevel) {
        this->m_lastLevel = level;
        this->log_ACTIVITY_HI_LevelStarted(level);
    }
    if (keys != this->m_lastKeys) {
        this->m_lastKeys = keys;
        this->log_ACTIVITY_HI_KeyPickedUp(keys);
    }
"""
s = s[:start] + new_parse + s[end:]
dup = """    if (level != this->m_lastLevel) {
        this->m_lastLevel = level;
        this->log_ACTIVITY_HI_LevelStarted(level);
    }
    if (keys != this->m_lastKeys) {
        this->m_lastKeys = keys;
        this->log_ACTIVITY_HI_KeyPickedUp(keys);
    }
"""
first = s.index(dup)
second = s.find(dup, first + len(dup))
if second != -1:
    s = s[:second] + s[second + len(dup):]
for bad in ("tlmWrite_ROUTE", "tlmWrite_NAV_MODE", "tlmWrite_FRONTIERS", "DOORS_KNOWN", "HUNT_LEFT", "TARGET_KIND"):
    assert bad not in s, bad
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("cpp ok")
