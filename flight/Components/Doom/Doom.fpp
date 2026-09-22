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

    @ What the navigator is currently routing toward
    enum TargetKind : U8 {
        FRONTIER = 0
        ENEMY = 1
        HEALTH = 2
        AMMO = 3
        ARMOR = 4
        WEAPON = 5
        FAR_FRONTIER = 6
        NONE = 7
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
        telemetry CLEAR_FWD: U16 id 13 @< map units of free space ahead
        telemetry CLEAR_LEFT: U16 id 14
        telemetry CLEAR_RIGHT: U16 id 15
        telemetry CLEAR_BACK: U16 id 16
        telemetry ROUTE_BEARING: F32 id 17 @< degrees to the next waypoint, positive left
        telemetry ROUTE_DIST: U16 id 18 @< path length to the target
        telemetry TARGET_DIST: U16 id 19
        telemetry TARGET_KIND: TargetKind id 20
        telemetry STUCK: bool id 21
        telemetry DOOR_AHEAD: bool id 22
        telemetry GOAL: Goal id 23
        telemetry HEALTH_ITEM_DIST: U16 id 24
        telemetry AMMO_ITEM_DIST: U16 id 25
        telemetry ARMOR_ITEM_DIST: U16 id 26
        telemetry TIC: U32 id 27
        telemetry EPISODE: U16 id 28
        telemetry DEAD: bool id 29
        telemetry LEVEL_DONE: bool id 30
        telemetry FRAMES_SENT: U32 id 31
        telemetry CHUNKS_SENT: U32 id 32
        telemetry FRAME_BYTES: U32 id 33 @< bytes of the last frame
        telemetry PAYLOAD_LINK: bool id 34
        telemetry CMDS_RECEIVED: U32 id 35
        telemetry FRAME_CHUNK: FrameChunk id 36
        telemetry EXPLORED_CELLS: U16 id 37 @< cells of the self-built map the player has stood in
        telemetry FRONTIERS: U16 id 38 @< known-free cells bordering the unexplored

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
