module DoomMission {

    @ What the onboard navigator steers toward. Chosen on the ground, executed onboard.
    enum Goal : U8 {
        EXPLORE = 0        @< Explore toward the nearest unexplored frontier (the exit is found, not known)
        KILL_ENEMY = 1     @< Face and close on the nearest visible enemy
        STOCK_AMMO = 2     @< Route to the nearest ammunition pickup
        RESTORE_HEALTH = 3 @< Route to the nearest health pickup
        ADD_ARMOR = 4      @< Route to the nearest armor pickup
        UPGRADE_WEAPON = 5 @< Route to the nearest weapon pickup
        SCOUT = 6          @< Explore toward the farthest frontier (a different part of the level)
        HOLD = 7           @< Stand still (safe mode)
    }

    @ What the range camera and the map say is at arm's length ahead
    enum AheadKind : U8 {
        NOTHING = 0
        WALL = 1
        DOOR = 2
        EXIT = 3           @< The exit line, seen on the automap
        LOCKED = 4         @< A locked door without its key
        BARRIER = 5        @< Something the map does not show (window bars, a fake door)
        THING = 6          @< A monster or a barrel
    }

    @ Weapon the player currently holds
    enum Weapon : U8 {
        FIST = 0
        PISTOL = 1
        SHOTGUN = 2
        OTHER = 3
    }

    @ !binary
    @ Raw bytes of one slice of a JPEG frame (opaque blob on the ground)
    array ChunkBytes = [960] U8

    @ One slice of a JPEG frame, downlinked as an image product. Reassemble on the ground by (seq, index).
    struct FrameChunk {
        seq: U32     @< Frame sequence number
        index: U16   @< Chunk index within the frame
        count: U16   @< Number of chunks in the frame
        length: U16  @< Valid bytes in data
        data: ChunkBytes
    }

    @ Payload interface component: bridges the Doom game process (payload) to F Prime commands and telemetry.
    active component Doom {

        # ----------------------------------------------------------------------
        # Ports
        # ----------------------------------------------------------------------

        @ Rate group input: polls the payload socket and downlinks what arrived
        async input port run: Svc.Sched

        @ Image product packets (FrameChunk telemetry records) sent straight to the com queue
        output port frameOut: Fw.Com

        # ----------------------------------------------------------------------
        # Commands (uplink)
        # ----------------------------------------------------------------------

        @ One set of held controls; applied every game tic until the next CONTROL arrives
        async command CONTROL(
            move: I8      @< -1 backward, 0 hold, 1 forward
            strafe: I8    @< -1 left, 0 hold, 1 right
            turn: F32     @< degrees to turn (heading setpoint executed onboard), positive left
            fire: bool    @< hold the trigger
            $use: bool    @< press use (doors, switches)
            weapon: Weapon @< weapon to select (FIST/OTHER = keep current)
        ) opcode 0x00

        @ Set the navigation goal the onboard navigator routes toward
        async command SET_GOAL(goal: Goal) opcode 0x01

        @ Restart the episode
        async command RESET_GAME opcode 0x02

        @ Bias exploration toward a direction for a while (what the ground saw in a frame)
        async command EXPLORE_HINT(
            bearing: I16  @< degrees relative to the current heading, positive left
            ttl: U8       @< seconds the hint stays in force
        ) opcode 0x04

        @ Set the frame downlink rate and JPEG quality
        async command FRAME_RATE(
            hz: U8        @< frames per second (0 disables frames)
            quality: U8   @< JPEG quality 10-95
        ) opcode 0x03

        # ----------------------------------------------------------------------
        # Telemetry (downlink)
        # ----------------------------------------------------------------------

        telemetry HEALTH: I16 id 0
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
        telemetry CLEAR_AL: U16 id 54 @< map ray ahead-left (45 deg)
        telemetry CLEAR_AR: U16 id 55 @< map ray ahead-right
        telemetry CLEAR_BL: U16 id 56 @< map ray behind-left (135 deg)
        telemetry CLEAR_BR: U16 id 57 @< map ray behind-right
        telemetry NEW_AL: U8 id 58 @< percent of the ground ahead-left not yet walked
        telemetry NEW_AR: U8 id 59
        telemetry NEW_BL: U8 id 60
        telemetry NEW_BR: U8 id 61

        # ----------------------------------------------------------------------
        # Events
        # ----------------------------------------------------------------------

        event PayloadConnected severity activity high id 0 format "Doom payload connected"
        event PayloadLost severity warning high id 1 format "Doom payload link lost"
        event EpisodeStarted(episode: U16) severity activity high id 2 format "Episode {} started"
        event PlayerDied(episode: U16, tic: U32) severity warning low id 3 format "Player died in episode {} at tic {}"
        event LevelFinished(episode: U16, tic: U32) severity activity high id 4 format "Level finished in episode {} at tic {}"
        event GoalSet(goal: Goal) severity activity low id 5 format "Navigation goal set to {}"
        event ExploreHint(bearing: I16, ttl: U8) severity activity low id 8 format "Exploration hint {} degrees for {} s"
        event FrameTooLarge(bytes: U32) severity warning low id 6 format "Frame of {} bytes exceeds the chunk budget; dropped"
        event BadPayloadMessage(kind: U8) severity warning low id 7 format "Unknown payload message kind {}"
        event LevelStarted(level: U8) severity activity high id 9 format "Now playing level {}"
        event KeyPickedUp(keys: U8) severity activity high id 10 format "Keys held (bitmask red=1 blue=2 yellow=4): {}"

        # ----------------------------------------------------------------------
        # Standard ports
        # ----------------------------------------------------------------------

        command recv port cmdIn
        command reg port cmdRegOut
        command resp port cmdResponseOut
        event port eventOut
        text event port textEventOut
        time get port timeCaller
        telemetry port tlmOut
    }
}
