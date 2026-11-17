#include "mp2_encoder.h"

#include <stdexcept>

extern "C" {
#include "toolame.h"
}

namespace ucs {

Mp2Encoder::Mp2Encoder(int sampleRate, int channels, int bitrateKbps, bool jointStereo, int psyModel) :
    sample_rate_(sampleRate), channels_(channels), bitrate_kbps_(bitrateKbps),
    joint_stereo_(jointStereo), psy_model_(psyModel) {}

void Mp2Encoder::open(int ancTotalBytes) {
    if (toolame_init() != 0)
        throw std::runtime_error("toolame_init failed");
    if (toolame_set_samplerate(sample_rate_) != 0)
        throw std::runtime_error("toolame_set_samplerate failed");

    char mode = (channels_ == 1) ? 'm' : (joint_stereo_ ? 'j' : 's');
    if (toolame_set_channel_mode(mode) != 0)
        throw std::runtime_error("toolame_set_channel_mode failed");

    // Must come after toolame_init(), which resets the model to the
    // library's built-in default (DFLT_PSY, model 1).
    if (toolame_set_psy_model(psy_model_) != 0)
        throw std::runtime_error("toolame_set_psy_model failed");

    if (toolame_set_bitrate(bitrate_kbps_) != 0)
        throw std::runtime_error("toolame_set_bitrate failed");
    if (toolame_set_pad(ancTotalBytes) != 0)
        throw std::runtime_error("toolame_set_pad failed");

    anc_total_bytes_ = ancTotalBytes;
}

int Mp2Encoder::encodeFrame(short pcm[][1152], const uint8_t* ancData, int ancLen,
                             uint8_t* outBuf, int outBufSize) {
    constexpr int kMaxAncTotal = 32; // generous; app_config.h's kMp2AncTotalBytes is 10
    uint8_t xpad[kMaxAncTotal] = {0};

    int total = anc_total_bytes_;
    if (total > kMaxAncTotal) total = kMaxAncTotal;
    int payload = total - 2; // reserve [N] and [0xFD]
    if (payload < 0) payload = 0;
    if (ancLen > payload) ancLen = payload;
    if (ancLen < 0) ancLen = 0;

    // Right-justify ancData in REVERSE order within [0 .. payload-1] (see
    // this class's header comment for the full wire format).
    for (int i = 0; i < ancLen; i++)
        xpad[payload - 1 - i] = ancData[i];
    xpad[payload] = static_cast<uint8_t>(ancLen);
    xpad[payload + 1] = 0xFD;

    // Only the last ancLen + 2 bytes of xpad are reserved and written:
    // toolame takes them from the end of the anc_total_bytes_-sized buffer,
    // and the bits that aren't reserved go to the audio instead.
    return toolame_encode_frame(pcm, xpad, static_cast<size_t>(ancLen + 2),
                                 outBuf, static_cast<size_t>(outBufSize));
}

int Mp2Encoder::flush(uint8_t* outBuf, int outBufSize) {
    return toolame_finish(outBuf, static_cast<size_t>(outBufSize));
}

} // namespace ucs
