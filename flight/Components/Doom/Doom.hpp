// ======================================================================
// \title  Doom.hpp
// \brief  Payload interface: the Doom game process seen as an instrument.
//
// Polled by a rate group. Reads STATUS and FRAME records from the payload socket, publishes
// the status as telemetry channels and every JPEG frame as a run of FrameChunk telemetry
// records sent straight to the com queue (so no chunk is lost to TlmChan sampling). Forwards
// CONTROL / SET_GOAL / RESET / FRAME_RATE commands to the payload.
// ======================================================================

#ifndef DoomMission_Doom_HPP
#define DoomMission_Doom_HPP

#include "DoomMission/Components/Doom/DoomComponentAc.hpp"

namespace DoomMission {

class Doom final : public DoomComponentBase {
  public:
    Doom(const char* const compName);
    ~Doom();

    static constexpr U16 PAYLOAD_PORT = 4242;
    static constexpr U32 CHUNK_DATA = 960;               //!< must match ChunkBytes size in Doom.fpp
    static constexpr U32 MAX_FRAME = CHUNK_DATA * 64;    //!< frames beyond this are dropped
    static constexpr U32 RX_CAPACITY = 256 * 1024;

  private:
    // Rate group tick: connect if needed, drain the socket, downlink what arrived
    void run_handler(FwIndexType portNum, U32 context) override;

    void CONTROL_cmdHandler(FwOpcodeType opCode, U32 cmdSeq, I8 move, I8 strafe, F32 turn, bool fire, bool use,
                            const DoomMission::Weapon& weapon) override;
    void SET_GOAL_cmdHandler(FwOpcodeType opCode, U32 cmdSeq, const DoomMission::Goal& goal) override;
    void RESET_GAME_cmdHandler(FwOpcodeType opCode, U32 cmdSeq) override;
    void EXPLORE_HINT_cmdHandler(FwOpcodeType opCode, U32 cmdSeq, I16 bearing, U8 ttl) override;
    void FRAME_RATE_cmdHandler(FwOpcodeType opCode, U32 cmdSeq, U8 hz, U8 quality) override;

    // Payload link
    void connectPayload();
    void dropPayload();
    bool sendToPayload(U8 kind, const U8* body, U16 length);
    void drainSocket();
    void handleMessage(U8 kind, const U8* body, U16 length);
    void handleStatus(const U8* body, U16 length);
    void handleFrame(const U8* body, U16 length);

    int m_sock;
    U32 m_retryTicks;
    U8* m_rx;            //!< receive accumulation buffer (heap, RX_CAPACITY)
    U32 m_rxLen;
    U32 m_framesSent;
    U32 m_chunksSent;
    U32 m_cmdsReceived;
    U16 m_lastEpisode;
    bool m_wasDead;
    bool m_wasDone;
};

}  // namespace DoomMission

#endif
