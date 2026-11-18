// mp2_uecp - MP2 encoder (libtoolame-dab) that embeds UECP (RDS) bytes in each frame's
// ancillary data. Used by stream_manager.py when "RDS (UECP) embedding" is enabled on an MP2
// stream; ffmpeg still converts the captured audio to PCM before it gets here and sends the
// MP2 it produces to the stream's destinations (-c:a copy).
//
// One process per stream: libtoolame-dab keeps all its state in globals, so two encoders
// can't share a process.
//
// Usage:
//   mp2_uecp_x64.exe <sample_rate> <channels 1|2> <bitrate_kbps> [joint_stereo 0|1] [psy_model 0-3]
//   Defaults: joint stereo on, psychoacoustic model 2.
//
// stdin, repeated once per MP2 frame:
//   [N: 1 byte, 0..8] [N UECP bytes, in wire order] [1152 * channels samples, s16le interleaved]
// stdout: the MP2 bitstream.
//
// Ancillary data layout (see mp2_encoder.h): [UECP bytes, reversed][N][0xFD] at the end of the
// frame, as read by WestBroadcast Streamer's Mp2UecpExtractor and UecpSource-compatible decoders.
//
// Exits 0 at the end of stdin, 1 on a bad argument or encoder error (message on stderr).

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <vector>

#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#define DUP _dup
#define DUP2 _dup2
#define FDOPEN _fdopen
#define FILENO _fileno
#else
#include <unistd.h>
#define DUP dup
#define DUP2 dup2
#define FDOPEN fdopen
#define FILENO fileno
#endif

#include "mp2_encoder.h"

namespace {

constexpr int kAncPayloadBytes = 8;               // UECP bytes per frame (as UecpSource)
constexpr int kAncTotalBytes = kAncPayloadBytes + 2; // + [N][0xFD]
constexpr int kFrameSamples = ucs::Mp2Encoder::frameSamples();

bool readFully(void* buf, size_t len) {
    return std::fread(buf, 1, len, stdin) == len;
}

int parseInt(const char* s, const char* what, int lo, int hi) {
    char* end = nullptr;
    long v = std::strtol(s, &end, 10);
    if (!end || *end || v < lo || v > hi) {
        std::fprintf(stderr, "mp2_uecp: invalid %s '%s' (expected %d..%d)\n", what, s, lo, hi);
        std::exit(1);
    }
    return static_cast<int>(v);
}

} // namespace

int main(int argc, char** argv) {
    if (argc < 4 || argc > 6) {
        std::fprintf(stderr,
            "usage: %s <sample_rate> <channels 1|2> <bitrate_kbps> [joint_stereo 0|1] [psy_model 0-3]\n",
            argc ? argv[0] : "mp2_uecp");
        return 1;
    }
    const int sample_rate = parseInt(argv[1], "sample rate", 8000, 48000);
    const int channels = parseInt(argv[2], "channel count", 1, 2);
    const int bitrate = parseInt(argv[3], "bitrate", 8, 384);
    const bool joint = argc > 4 ? parseInt(argv[4], "joint stereo flag", 0, 1) != 0 : true;
    const int psy = argc > 5 ? parseInt(argv[5], "psychoacoustic model", 0, 3) : 2;

#if defined(_WIN32)
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    // libtoolame-dab prints some diagnostics to stdout. Keep the real stdout for the bitstream
    // only and point fd 1 at stderr, so nothing else can end up in the MP2 stream.
    std::fflush(stdout);
    int out_fd = DUP(FILENO(stdout));
    if (out_fd < 0 || DUP2(FILENO(stderr), FILENO(stdout)) < 0) {
        std::fprintf(stderr, "mp2_uecp: could not redirect stdout\n");
        return 1;
    }
    FILE* out = FDOPEN(out_fd, "wb");
    if (!out) {
        std::fprintf(stderr, "mp2_uecp: could not open output stream\n");
        return 1;
    }
#if defined(_WIN32)
    _setmode(out_fd, _O_BINARY);
#endif

    ucs::Mp2Encoder encoder(sample_rate, channels, bitrate, joint, psy);
    try {
        encoder.open(kAncTotalBytes);
    } catch (const std::exception& e) {
        std::fprintf(stderr,
            "mp2_uecp: %s (MP2 does not support %d kbps %s at %d Hz)\n",
            e.what(), bitrate, channels == 1 ? "mono" : "stereo", sample_rate);
        return 1;
    }

    std::vector<int16_t> interleaved(static_cast<size_t>(kFrameSamples) * channels);
    static short planar[2][1152];
    std::vector<uint8_t> encoded(16384);
    uint8_t anc[kAncPayloadBytes];

    for (;;) {
        uint8_t n = 0;
        if (!readFully(&n, 1)) break; // end of input
        if (n > kAncPayloadBytes) {
            std::fprintf(stderr, "mp2_uecp: invalid ancillary length %u\n", n);
            return 1;
        }
        if (n && !readFully(anc, n)) break;
        if (!readFully(interleaved.data(), interleaved.size() * sizeof(int16_t))) break;

        if (channels == 2) {
            for (int i = 0; i < kFrameSamples; i++) {
                planar[0][i] = interleaved[2 * i];
                planar[1][i] = interleaved[2 * i + 1];
            }
        } else {
            std::memcpy(planar[0], interleaved.data(), kFrameSamples * sizeof(int16_t));
        }

        int bytes = encoder.encodeFrame(planar, anc, n, encoded.data(), static_cast<int>(encoded.size()));
        if (bytes < 0) {
            std::fprintf(stderr, "mp2_uecp: encoder error\n");
            return 1;
        }
        if (bytes > 0) {
            if (std::fwrite(encoded.data(), 1, static_cast<size_t>(bytes), out) != static_cast<size_t>(bytes))
                return 0; // reader went away
            std::fflush(out);
        }
    }

    int bytes = encoder.flush(encoded.data(), static_cast<int>(encoded.size()));
    if (bytes > 0) std::fwrite(encoded.data(), 1, static_cast<size_t>(bytes), out);
    std::fflush(out);
    return 0;
}
