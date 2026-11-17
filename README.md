# WestBroadcast Encoder
WestBroadcast Encoder is a multi-output IP audio encoder, offering the ability for radio stations to stream audio to Icecast servers, as well as via RTP or through a built-in streaming server.
<br>
<br>
Multiple destinations can be configured, allowing audio to be sent from studios to several servers.
<br>
<br>
The encoders can be controlled remotely at any time via a secure web interface. An email alerts feature is also included to inform the user in the event of an incident (Silent streams or inability to connect to a streaming server).
<br>
<br>
This broadcasting solution, based on FFmpeg and a Python script, is entirely open source.
<br>
<br>
WestBroadcast Encoder runs as a portable installer. This means you can use it anywhere, even from an external hard drive or a USB drive.
- - -
<b>⚠️ For now, the encoder only works on Windows. Optimizations are needed so that the project can run on Linux.</b>
<br>
<br>
This software has been tested on several computers running Windows 10 and 11, with success.
<br>
Any feedback regarding other operating systems is welcome!


<img width="1910" height="1016" alt="wbencoder-main-preview" src="https://github.com/user-attachments/assets/e5df0d2c-9b55-4de9-92c3-ba240ef8d009" />

## ⚡ What this tool offers
• <b>Audio stream encoding using the following codecs:</b>
<br>
MP3, AAC* (AAC-LC, HE-AAC V1, HE-AAC V2), OGG Opus, OGG Vorbis, FLAC, WAV, and MP2.
<br>
<br>
• <b>Streaming to Icecast (V2) servers.</b>
<br>
<br>
• <b>Streaming on a built-in server</b>, whose streams can be listened directly over a port, without additional installation.
<br>
<br>
• <b>Streaming via RTP protocol</b>, either in "pure" form (with an SDP file) or encapsulated in MPEG-TS.
<br>
<br>
• <b>Broadcasting the same stream to multiple servers at once</b>, using a single instance.
<br>
<br>
• <b>Full control over the bitrate, sample rate, bit depth, audio gain, etc.</b>
<br>
<br>
• <b>Adjustable audio latency before encoding</b> to easily synchronize a stream with another.
<br>
<br>
• <b>Sending "Currently Playing" metadata</b> on your stream to display the title of the song being aired.
<br>
-> This can be done by retrieving the content of a text file, from a HTML page, or by using the POST function in your automation software.
<br>
<br>
• <b>Embedding RDS (UECP) data in MP2 and AAC streams</b>, received over TCP from an RDS encoder.
<br>
-> WestBroadcast Streamer (and other UECP-aware receivers) can extract it and forward it to an RDS encoder at the other end. See [RDS (UECP) embedding](#-rds-uecp-embedding) below.
<br>
<br>
• <b>Sending email alerts via SMTP</b> when one of your streams is silent, or the streaming server becomes unavailable.
> _* AAC encoding requires the Fraunhofer FDK library, which is not included for legal reasons.<br>It can be downloaded directly via the interface or installed manually. Please refer to the Wiki section for details and instructions._
## 💬 Available languages
WestBroadcast Encoder is available in English and French.
<br>
There are currently no plans to add other languages, in order to ensure the quality of the translation.
<br>
<br>
If you would like to contribute a translation for a language **you are a native speaker of**, please feel free to do so.
<br>
Any contribution is appreciated and welcome.
## ⚙️ 1. Installation instructions for Windows
-> [Download the entire content of the repository by clicking here.](https://github.com/LucasGallone/WestBroadcast-Encoder/archive/refs/heads/main.zip)
<br>
<br>
-> Extract the content of the .zip file and place the files wherever you like.
<br>
<br>
-> Install Python 3.10 or newer on your computer from the official website [by clicking here.](https://www.python.org/downloads/)
<br>
<b>IMPORTANT: When installing Python, make sure to check the "Add Python to PATH" box, otherwise the encoder will not work properly!</b>
<br>
<br>
-> Ideally, as is customary, restart your computer after installing Python.
<br>
<br>
-> Go back to the folder containing the encoder files, and run `Launcher.bat`.
<br>
When started for the first time, it will install the Python dependencies required for the encoder to work properly. This may take a few minutes.
<br>
Even if nothing appears to be happening on the terminal, please wait until the process is complete.
<br>
<br>
-> Once the installation is complete, the webserver will start up.
<br>
A Python window will open, displaying your machine's IP address, the port used by the webserver, and the default login password.
<br>
Be sure to keep this window open on the host machine, as well as the terminal, otherwise the software will close!
## ⚙️ 2. Configuration
Once installed, you must configure your stream(s) via the web interface.
<br>
The default port is 8090 and the default login password is **admin**.
<br>
(Changing the password at first use is STRONGLY recommended to prevent any unauthorized access!)
## 🚀 3. Starting the encoder after the initial setup
For the next startups, simply run `Launch.bat` as you did during the initial installation.
<br>
At each startup, the script checks that all required dependencies are present on your machine, then starts the audio engine and the webserver.
## 📡 RDS (UECP) embedding
MP2 and AAC streams can carry RDS data alongside the audio. Enable **Embed RDS (UECP) data in the audio frames** in the stream's Audio Settings and choose a TCP port (default 9000). The encoder then listens on that port for UECP frames (`0xFE … 0xFF`) from your RDS encoder or playout system, and embeds them in the stream a few bytes per audio frame. The frames aren't parsed or modified.
<br>
<br>
• <b>MP2:</b> up to 8 bytes per frame (about 330 bytes/s at 48 kHz), in the frame's ancillary data: `[UECP bytes, reversed][N][0xFD]` at the end of the frame. These streams are encoded by `mp2_uecp_x64.exe` (libtoolame-dab, psychoacoustic model 2, joint stereo) instead of FFmpeg's MP2 encoder; FFmpeg still prepares the audio and sends the result to every destination as usual.
<br>
• <b>AAC (AAC-LC, HE-AAC V1/V2):</b> up to 4 bytes per frame (about 190 bytes/s for AAC-LC at 48 kHz, half that for HE-AAC), in a data stream element (DSE), using the same libfdk-aac.dll. The FDK library only allows ancillary data above 8 kbps per channel, so at very low bitrates there is no room for it; the dashboard shows a warning when that happens.
<br>
<br>
One UECP client is served per port; a new connection replaces the current one. Streams set to the same port receive the same data. If UECP arrives faster than the audio frames can carry it, the oldest waiting frames are dropped (shown on the dashboard) so the delay can't keep growing. This is the same mechanism as UecpSource, and the format WestBroadcast Streamer's UECP forwarding extracts.
<br>
<br>
`mp2_uecp_x64.exe` is built from [`native/mp2_uecp`](native/mp2_uecp) with CMake and Visual Studio (see the comment at the top of its `CMakeLists.txt`).
## 💡 Help / Documentation
Need help configuring the encoder or understanding a specific setting?
<br>
👉 [Click here to visit the Wiki section for detailed documentation.](https://github.com/LucasGallone/WestBroadcast-Encoder/wiki)
<br>
<br>
If you discover any bugs, despite the rigorous pre-release testing, don't hesitate to report them in the [Issues](https://github.com/LucasGallone/WestBroadcast-Encoder/issues) section.
## ⚖️ Legal Notices and Licenses
### WestBroadcast Encoder
This project is licensed under the GNU General Public License (GPL) v3.0.
<br>
Please refer to the `LICENSE` file for more details.
- - -
### FFmpeg
This project uses the FFmpeg executable for encoding audio streams.
<br>
<br>
• <b>License:</b> FFmpeg is licensed under the GNU General Public License (GPL) v3.0.
<br>
• <b>Redistribution:</b> The binary provided in this repository is an unmodified static version compiled by [Gyan.dev.](https://www.gyan.dev/ffmpeg/builds/)
<br>
• <b>Source Code:</b> In accordance with the GPL license, the FFmpeg source code is available on [ffmpeg.org.](https://ffmpeg.org/)
<br>
• <b>Trademark:</b> FFmpeg is a registered trademark of Fabrice Bellard, creator of the FFmpeg project.
<br>
<br>
For more details, please refer to the `FFmpeg-LICENSE.txt` file included in this repository.
- - -
### libtoolame-dab (MP2 encoder for RDS/UECP embedding)
`mp2_uecp_x64.exe` is built from [`native/mp2_uecp`](native/mp2_uecp), which includes a modified copy of libtoolame-dab from [ODR-AudioEnc](https://github.com/Opendigitalradio/ODR-AudioEnc).
<br>
<br>
• <b>License:</b> GNU Lesser General Public License (LGPL) v2.1 or later. See `native/mp2_uecp/libtoolame-dab/LGPL.txt`.
<br>
• <b>Modifications:</b> listed in `native/mp2_uecp/libtoolame-dab/MODIFICATIONS.md`.
- - -
### Vue.js (JavaScript Framework)
The `vue3.js` file included in the `/static` folder is part of the Vue.js library.
<br>
<br>
• <b>License:</b> MIT License.
<br>
• <b>Copyright (c)</b> 2013-present, Yuxi (Evan) You.
- - -
### Socket.io (JavaScript Client)
The `socket.io.js` file included in the `/static` folder is part of the Socket.io library.
<br>
<br>
• <b>License:</b> MIT License.
<br>
• <b>Copyright (c)</b> 2014-2025 Automattic.
- - -
### Bootstrap (CSS Framework)
The `bootstrap.min.css` file included in the `/static` folder is part of the Bootstrap framework.
<br>
<br>
• <b>License:</b> MIT License.
<br>
• <b>Copyright (c)</b> 2011-2024 The Bootstrap Authors.
- - -
### Python Dependencies
This project uses the following libraries, automatically installed by the Launcher script:
<br>
<br>
• <b>Flask / Werkzeug:</b> BSD-3-Clause License.
<br>
• <b>Flask-SocketIO:</b> MIT License.
<br>
• <b>Sounddevice / PortAudio:</b> MIT License.
<br>
• <b>NumPy:</b> BSD-3-Clause License.
<br>
• <b>psutil:</b> BSD-3-Clause License.
<br>
• <b>Requests:</b> Apache License 2.0.
