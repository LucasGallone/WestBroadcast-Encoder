# Local modifications to libtoolame-dab

This directory is a modified copy of `libtoolame-dab` from
[ODR-AudioEnc](https://github.com/Opendigitalradio/ODR-AudioEnc). It was
compared against ODR-AudioEnc v3.6.0 (commit `20d3b59`, 2024-12-03). It is
licensed under the GNU LGPL 2.1 or later (see `LGPL.txt`). The original
copyright notices and credits are in `README.md`.

Upstream files not needed for the build (`HISTORY`, `html/`, `text/`) are
omitted. Each modified file also has a short notice at the top. The changes
are listed below.

## `toolame.c`: DAB mode disabled

2026-08-14. Upstream libtoolame-dab is set up to produce DAB (ETSI EN 300 401) frames.
This project streams plain MPEG-1 Layer II over Icecast, so:

- `toolame_init()` sets `header.error_protection = FALSE` (upstream: `TRUE`)
  and `header.dab_extension = 0` (upstream: `4`). Frames carry no CRC and
  no DAB extension bytes.
- `toolame_encode_frame()` no longer applies the DAB-only adjustment.
  Upstream does two things in DAB mode: it reserves the DAB extension plus a
  fixed F-PAD (`FPAD_LENGTH`) when no X-PAD is supplied, and it sets the
  bitstream buffer's minimum to one whole frame. Now only the X-PAD length the
  caller passes is reserved. UecpSource uses that X-PAD area for its MP2
  ancillary data.
- 2026-11-02: when the caller passes `xpad_len == 0`, `toolame_encode_frame()`
  no longer writes the 2 all-zero F-PAD bytes. F-PAD is DAB-only, and since
  the change above no longer reserves bits for it, writing it made such frames
  2 bytes too long.

## `tables.c`, `utils.c`: MSVC portability

2026-08-14. `#include <unistd.h>` is wrapped in `#if !defined(_WIN32)`.
Neither file uses anything from it, and MSVC doesn't provide the header.

## `pds_subband.c`: missing declarations

2026-08-14. Adds `#include <string.h>`, `"mem.h"` and
`"tables.h"`, plus a prototype for `read_ana_window()`. This file is an
alternative subband implementation and isn't compiled by this project's
`CMakeLists.txt`.

## `CMakeLists.txt`: added

Upstream builds libtoolame-dab as part of ODR-AudioEnc's autotools build.
This project compiles the sources directly into a static library, without
`pds_subband.c` and with `-DNEWENCODE`.
