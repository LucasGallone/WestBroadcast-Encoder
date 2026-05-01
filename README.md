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
This broadcasting solution is entirely open source and is based on FFmpeg, as well as a Python script.
<br>
<br>
WestBroadcast Encoder runs as a portable installer. This means you can use it anywhere, even from an external hard drive or a USB drive.
- - -
<b>⚠️ At this time, the encoder only works on Windows. Optimizations are needed so that the project can run on Linux.</b>
<br>
<br>
This software has been tested on several computers running Windows 10 and 11, with success.
<br>
Any quality feedback regarding other operating systems is welcome!
## What this tool offers
• The ability to encode audio streams using the following codecs:
<br>
MP3, AAC (AAC-LC, HE-AAC V1, HE-AAC V2), OGG Opus, OGG Vorbis, FLAC, WAV, and MP2.
<br>
<br>
• Streaming to Icecast (V2) servers.
<br>
<br>
• Streaming on a built-in server, whose streams can be listened directly over a port, without additional installation.
<br>
<br>
• Streaming via RTP protocol, either in "pure" form (with an SDP file) or encapsulated in MPEG-TS.
<br>
<br>
• The ability to broadcast a same stream to multiple servers at once, using a single instance.
<br>
<br>
• Full control over the bitrate, sample rate, bit depth, audio gain, ...
<br>
<br>
• The ability to add latency before the audio encoding, in order to easily synchronize a stream with another.
<br>
<br>
• Sending "Currently Playing" metadata on your stream to display the title of the song being aired.
<br>
-> This can be done by retrieving the content of a text file, from a HTML page, or by using the POST function in your automation software.
<br>
<br>
• Sending email alerts via SMTP when one of your streams is silent, or the streaming server becomes unavailable.
## 1. Installation instructions for Windows
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
## 2. Configuration
Once installed, you must configure your stream(s) via the web interface.
<br>
The default port is 8090 and the default login password is **admin**.
<br>
(Changing the password at first use is STRONGLY recommended to prevent any unauthorized access!)
## 3. Starting the encoder after the initial setup
For the next startups, simply run `Launch.bat` as you did during the initial installation.
<br>
At each startup, the script checks that all required dependencies are present on your machine, then starts the audio engine and the webserver.
## 💡 Help / Documentation
Need help configuring the encoder or understanding a specific setting?
<br>
👉 [Click here to visit the Wiki section for detailed documentation.](https://github.com/LucasGallone/WestBroadcast-Encoder/wiki)
## Legal Notices and Licenses
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
