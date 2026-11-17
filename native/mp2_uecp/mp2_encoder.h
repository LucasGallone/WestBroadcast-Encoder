#pragma once

#include <cstdint>

namespace ucs {

// Thin wrapper around libtoolame-dab's global C API (toolame_init/set_*/
// encode_frame/finish), giving it the same open()/encodeFrame()/flush()
// shape as AacEncoder. libtoolame-dab has no per-instance handle -- it's
// process-global state -- so only one Mp2Encoder may usefully be open at a
// time, which matches how this app only ever runs one encoder at once.
//
// Ancillary data format (last N + 2 bytes of each frame):
//   [UECP chunk, N bytes, REVERSED]  [N]  [0xFD]
// A decoder reading backwards from the frame end recovers the UECP bytes in
// forward order. This reversal (unlike AAC's raw DSE payload) is needed
// because MP2's ancillary bytes are just raw appended bytes with no
// self-describing length field of their own -- the trailing [N][0xFD] is
// what supplies that.
//
// Only N + 2 bytes are reserved per frame (2 when no UECP is pending), so
// the audio gets every byte not needed for ancillary data that frame. The
// 2-byte [N][0xFD] trailer is always kept: without it, the last bytes of an
// all-audio frame would occasionally look like a valid trailer to a receiver.
// Receivers reading backwards via [N] see the same bytes as when the area
// was a fixed size with leading zero padding.
class Mp2Encoder
{
public:
    // sampleRate in Hz (44100/48000), channels 1 or 2, bitrateKbps in kbps.
    // jointStereo selects joint-stereo vs plain stereo coding when
    // channels == 2 (ignored -- forced mono -- when channels == 1).
    // psyModel selects libtoolame's psychoacoustic model (0..3, see
    // app_config.h's kDefaultMp2PsyModel).
    Mp2Encoder(int sampleRate, int channels, int bitrateKbps, bool jointStereo, int psyModel);

    // Opens and configures the encoder, allowing up to ancTotalBytes of
    // ancillary space per frame (see app_config.h's kMp2AncTotalBytes).
    // Throws std::runtime_error on failure.
    void open(int ancTotalBytes);

    // PCM samples per channel per encodeFrame() call -- fixed at 1152 for
    // MPEG-1/2 Layer II regardless of sample rate.
    static constexpr int frameSamples() { return 1152; }

    // Encode one frame. pcm is planar (pcm[channel][sample], frameSamples()
    // samples per channel -- channel 1 unused/ignored for mono). ancData/
    // ancLen (0..ancTotalBytes-2 bytes) are embedded via the ancillary
    // format described above; pass ancLen=0 for a frame with no pending
    // data. Returns bytes written to outBuf, or -1 on error.
    int encodeFrame(short pcm[][1152], const uint8_t* ancData, int ancLen,
                     uint8_t* outBuf, int outBufSize);

    // Drain the encoder's internal bit-reservoir at end of stream. Returns
    // bytes written (0 if nothing left).
    int flush(uint8_t* outBuf, int outBufSize);

private:
    int sample_rate_;
    int channels_;
    int bitrate_kbps_;
    bool joint_stereo_;
    int psy_model_;
    int anc_total_bytes_ = 0;
};

} // namespace ucs
