// ======================================================================
// \title  Doom.cpp
// \brief  Payload interface implementation (see Doom.hpp)
// ======================================================================

#include "DoomMission/Components/Doom/Doom.hpp"

#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>

#include "Fw/Com/ComPacket.hpp"

namespace DoomMission {

// ----------------------------------------------------------------------
// Big-endian field readers for the payload protocol
// ----------------------------------------------------------------------
namespace {
U16 rdU16(const U8*& p) { U16 v = static_cast<U16>((p[0] << 8) | p[1]); p += 2; return v; }
I16 rdI16(const U8*& p) { return static_cast<I16>(rdU16(p)); }
U32 rdU32(const U8*& p) { U32 v = (static_cast<U32>(p[0]) << 24) | (static_cast<U32>(p[1]) << 16) | (static_cast<U32>(p[2]) << 8) | p[3]; p += 4; return v; }
F32 rdF32(const U8*& p) { U32 u = rdU32(p); F32 f; std::memcpy(&f, &u, sizeof f); return f; }
U8 rdU8(const U8*& p) { return *p++; }
void wrF32(U8* p, F32 f) { U32 u; std::memcpy(&u, &f, sizeof u); p[0] = static_cast<U8>(u >> 24); p[1] = static_cast<U8>(u >> 16); p[2] = static_cast<U8>(u >> 8); p[3] = static_cast<U8>(u); }
constexpr U16 STATUS_LEN = 112;  // struct.calcsize of the payload STATUS_FMT
}  // namespace

Doom ::Doom(const char* const compName)
    : DoomComponentBase(compName), m_sock(-1), m_retryTicks(0), m_rx(new U8[RX_CAPACITY]), m_rxLen(0),
      m_framesSent(0), m_chunksSent(0), m_cmdsReceived(0), m_lastEpisode(0), m_wasDead(false), m_wasDone(false), m_lastLevel(0), m_lastKeys(0) {}

Doom ::~Doom() {
    this->dropPayload();
    delete[] this->m_rx;
}

// ----------------------------------------------------------------------
// Rate group tick
// ----------------------------------------------------------------------

void Doom ::run_handler(FwIndexType portNum, U32 context) {
    if (this->m_sock < 0) {
        if (this->m_retryTicks++ % 20 == 0) {  // once a second at 20 Hz
            this->connectPayload();
        }
    }
    if (this->m_sock >= 0) {
        this->drainSocket();
    }
    this->tlmWrite_PAYLOAD_LINK(this->m_sock >= 0);
    this->tlmWrite_FRAMES_SENT(this->m_framesSent);
    this->tlmWrite_CHUNKS_SENT(this->m_chunksSent);
    this->tlmWrite_CMDS_RECEIVED(this->m_cmdsReceived);
}

// ----------------------------------------------------------------------
// Commands: each becomes one small uplink record to the payload
// ----------------------------------------------------------------------

void Doom ::CONTROL_cmdHandler(FwOpcodeType opCode, U32 cmdSeq, I8 move, I8 strafe, F32 turn, bool fire, bool use,
                               const DoomMission::Weapon& weapon) {
    this->m_cmdsReceived++;
    U8 body[9];
    body[0] = static_cast<U8>(move);
    body[1] = static_cast<U8>(strafe);
    wrF32(&body[2], turn);
    body[6] = fire ? 1 : 0;
    body[7] = use ? 1 : 0;
    body[8] = static_cast<U8>(weapon.e);
    const bool ok = this->sendToPayload(0x10, body, sizeof body);
    this->cmdResponse_out(opCode, cmdSeq, ok ? Fw::CmdResponse::OK : Fw::CmdResponse::EXECUTION_ERROR);
}

void Doom ::SET_GOAL_cmdHandler(FwOpcodeType opCode, U32 cmdSeq, const DoomMission::Goal& goal) {
    this->m_cmdsReceived++;
    const U8 body = static_cast<U8>(goal.e);
    const bool ok = this->sendToPayload(0x11, &body, 1);
    if (ok) {
        this->log_ACTIVITY_LO_GoalSet(goal);
    }
    this->cmdResponse_out(opCode, cmdSeq, ok ? Fw::CmdResponse::OK : Fw::CmdResponse::EXECUTION_ERROR);
}

void Doom ::RESET_GAME_cmdHandler(FwOpcodeType opCode, U32 cmdSeq) {
    this->m_cmdsReceived++;
    const bool ok = this->sendToPayload(0x12, nullptr, 0);
    this->cmdResponse_out(opCode, cmdSeq, ok ? Fw::CmdResponse::OK : Fw::CmdResponse::EXECUTION_ERROR);
}

void Doom ::EXPLORE_HINT_cmdHandler(FwOpcodeType opCode, U32 cmdSeq, I16 bearing, U8 ttl) {
    this->m_cmdsReceived++;
    const U8 body[3] = {static_cast<U8>(static_cast<U16>(bearing) >> 8), static_cast<U8>(bearing), ttl};
    const bool ok = this->sendToPayload(0x14, body, sizeof body);
    if (ok) {
        this->log_ACTIVITY_LO_ExploreHint(bearing, ttl);
    }
    this->cmdResponse_out(opCode, cmdSeq, ok ? Fw::CmdResponse::OK : Fw::CmdResponse::EXECUTION_ERROR);
}

void Doom ::FRAME_RATE_cmdHandler(FwOpcodeType opCode, U32 cmdSeq, U8 hz, U8 quality) {
    this->m_cmdsReceived++;
    const U8 body[2] = {hz, quality};
    const bool ok = this->sendToPayload(0x13, body, sizeof body);
    this->cmdResponse_out(opCode, cmdSeq, ok ? Fw::CmdResponse::OK : Fw::CmdResponse::EXECUTION_ERROR);
}

// ----------------------------------------------------------------------
// Payload link
// ----------------------------------------------------------------------

void Doom ::connectPayload() {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        return;
    }
    sockaddr_in addr;
    std::memset(&addr, 0, sizeof addr);
    addr.sin_family = AF_INET;
    addr.sin_port = htons(PAYLOAD_PORT);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof addr) != 0) {
        ::close(fd);
        return;
    }
    int one = 1;
    (void)::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    (void)::fcntl(fd, F_SETFL, ::fcntl(fd, F_GETFL, 0) | O_NONBLOCK);
    this->m_sock = fd;
    this->m_rxLen = 0;
    this->log_ACTIVITY_HI_PayloadConnected();
}

void Doom ::dropPayload() {
    if (this->m_sock >= 0) {
        ::close(this->m_sock);
        this->m_sock = -1;
        this->m_rxLen = 0;
        this->log_WARNING_HI_PayloadLost();
    }
}

bool Doom ::sendToPayload(U8 kind, const U8* body, U16 length) {
    if (this->m_sock < 0) {
        return false;
    }
    U8 msg[4 + 64];
    FW_ASSERT(length <= sizeof msg - 4, length);
    msg[0] = 'D';
    msg[1] = kind;
    msg[2] = static_cast<U8>(length >> 8);
    msg[3] = static_cast<U8>(length);
    if (length > 0) {
        std::memcpy(&msg[4], body, length);
    }
    const ssize_t n = ::send(this->m_sock, msg, 4 + length, MSG_NOSIGNAL);
    if (n != static_cast<ssize_t>(4 + length)) {
        this->dropPayload();
        return false;
    }
    return true;
}

void Doom ::drainSocket() {
    for (;;) {
        if (this->m_rxLen >= RX_CAPACITY) {
            this->m_rxLen = 0;  // hopeless backlog: resync
        }
        const ssize_t n = ::recv(this->m_sock, this->m_rx + this->m_rxLen, RX_CAPACITY - this->m_rxLen, 0);
        if (n == 0) {
            this->dropPayload();
            return;
        }
        if (n < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
                this->dropPayload();
            }
            break;
        }
        this->m_rxLen += static_cast<U32>(n);
    }
    // Parse complete records
    U32 pos = 0;
    while (this->m_rxLen - pos >= 4) {
        const U8* h = this->m_rx + pos;
        if (h[0] != 'D') {
            pos++;  // resync byte by byte
            continue;
        }
        const U8 kind = h[1];
        const U16 length = static_cast<U16>((h[2] << 8) | h[3]);
        if (this->m_rxLen - pos < 4u + length) {
            break;
        }
        this->handleMessage(kind, h + 4, length);
        pos += 4u + length;
    }
    if (pos > 0) {
        std::memmove(this->m_rx, this->m_rx + pos, this->m_rxLen - pos);
        this->m_rxLen -= pos;
    }
}

void Doom ::handleMessage(U8 kind, const U8* body, U16 length) {
    switch (kind) {
        case 1:
            this->handleStatus(body, length);
            break;
        case 2:
            this->handleFrame(body, length);
            break;
        default:
            this->log_WARNING_LO_BadPayloadMessage(kind);
            break;
    }
}

void Doom ::handleStatus(const U8* body, U16 length) {
    if (length < STATUS_LEN) {
        this->log_WARNING_LO_BadPayloadMessage(1);
        return;
    }
    const U8* p = body;
    this->tlmWrite_HEALTH(rdI16(p));
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
    this->tlmWrite_CLEAR_AL(rdU16(p));
    this->tlmWrite_CLEAR_AR(rdU16(p));
    this->tlmWrite_CLEAR_BL(rdU16(p));
    this->tlmWrite_CLEAR_BR(rdU16(p));
    this->tlmWrite_NEW_AL(rdU8(p));
    this->tlmWrite_NEW_AR(rdU8(p));
    this->tlmWrite_NEW_BL(rdU8(p));
    this->tlmWrite_NEW_BR(rdU8(p));
    if (level != this->m_lastLevel) {
        this->m_lastLevel = level;
        this->log_ACTIVITY_HI_LevelStarted(level);
    }
    if (keys != this->m_lastKeys) {
        this->m_lastKeys = keys;
        this->log_ACTIVITY_HI_KeyPickedUp(keys);
    }
    if (episode != this->m_lastEpisode) {
        this->m_lastEpisode = episode;
        this->log_ACTIVITY_HI_EpisodeStarted(episode);
    }
    if (dead && !this->m_wasDead) {
        this->log_WARNING_LO_PlayerDied(episode, tic);
    }
    if (done && !this->m_wasDone) {
        this->log_ACTIVITY_HI_LevelFinished(episode, tic);
    }
    this->m_wasDead = dead;
    this->m_wasDone = done;
}

void Doom ::handleFrame(const U8* body, U16 length) {
    if (length < 4) {
        return;
    }
    const U8* p = body;
    const U32 seq = rdU32(p);
    const U32 jpegLen = static_cast<U32>(length) - 4;
    if (jpegLen > MAX_FRAME) {
        this->log_WARNING_LO_FrameTooLarge(jpegLen);
        return;
    }
    const U16 count = static_cast<U16>((jpegLen + CHUNK_DATA - 1) / CHUNK_DATA);
    const FwChanIdType chanId = static_cast<FwChanIdType>(this->getIdBase() + CHANNELID_FRAME_CHUNK);
    for (U16 index = 0; index < count; index++) {
        const U32 offset = static_cast<U32>(index) * CHUNK_DATA;
        const U32 n = (jpegLen - offset < CHUNK_DATA) ? (jpegLen - offset) : CHUNK_DATA;
        DoomMission::ChunkBytes bytes;
        for (U32 i = 0; i < CHUNK_DATA; i++) {
            bytes[i] = (i < n) ? p[offset + i] : 0;
        }
        DoomMission::FrameChunk chunk(seq, index, count, static_cast<U16>(n), bytes);
        // One telemetry record per chunk, exactly as Svc::TlmChan would frame a single channel update
        Fw::ComBuffer buf;
        Fw::SerializeStatus status = buf.serializeFrom(static_cast<FwPacketDescriptorType>(Fw::ComPacketType::FW_PACKET_TELEM));
        FW_ASSERT(status == Fw::FW_SERIALIZE_OK, static_cast<FwAssertArgType>(status));
        status = buf.serializeFrom(chanId);
        FW_ASSERT(status == Fw::FW_SERIALIZE_OK, static_cast<FwAssertArgType>(status));
        Fw::Time now = this->getTime();
        status = buf.serializeFrom(now);
        FW_ASSERT(status == Fw::FW_SERIALIZE_OK, static_cast<FwAssertArgType>(status));
        status = buf.serializeFrom(chunk);
        FW_ASSERT(status == Fw::FW_SERIALIZE_OK, static_cast<FwAssertArgType>(status));
        this->frameOut_out(0, buf, 0);
        this->m_chunksSent++;
    }
    this->m_framesSent++;
    this->tlmWrite_FRAME_BYTES(jpegLen);
}

}  // namespace DoomMission
