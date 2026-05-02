import subprocess
import threading
import time
import os
import requests
import smtplib
import platform
import struct
import math
import ssl
import ctypes
import glob
import socket
import asyncio
import numpy as np
import sounddevice as sd
from email.message import EmailMessage
from email.utils import formatdate

# --- Global server state cache ---
GLOBAL_SERVER_STATE = {}

class InternalHTTPServer:
    def __init__(self, port, content_type, station_name="WebStreamer", genre="Various", description="", initial_title="", use_udp=True):
        self.port = int(port)
        self.content_type = content_type
        self.station_name = station_name
        self.genre = genre
        self.description = description
        self.current_title = initial_title
        self.running = True
        self.use_udp = use_udp
        self.udp_port = 0
        self.meta_int = 16384
        
        self.clients = []
        self.client_queues = []
        
        self.header_cache = b""
        self.header_caching_done = False
    
        self.ready_event = threading.Event()
        
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._start_loop, daemon=True)
        self.thread.start()
        
        # The main code must wait (up to 3 seconds) for the asynchronous loop to have set the UDP port
        self.ready_event.wait(timeout=3.0)

    def set_metadata(self, title):
        self.current_title = title

    def _start_loop(self):
        asyncio.set_event_loop(self.loop)
        self._data_queue = asyncio.Queue()
        
        def exception_handler(loop, context):
            msg = context.get("message", "")
            if "Task was destroyed but it is pending" in msg:
                return
            exc = context.get('exception')
            if isinstance(exc, OSError) and getattr(exc, 'winerror', None) == 995: return
            loop.default_exception_handler(context)
            
        self.loop.set_exception_handler(exception_handler)
        
        try:
            self.loop.run_until_complete(self._run_server())
        except (RuntimeError, OSError, asyncio.CancelledError):
            pass
            
    async def _run_server(self):
        self.server = await asyncio.start_server(self._handle_client, '0.0.0.0', self.port)
        
        if self.use_udp:
            class UDPProtocol(asyncio.DatagramProtocol):
                def __init__(self, parent): self.parent = parent
                def datagram_received(self, data, addr):
                    try: self.parent._data_queue.put_nowait(data)
                    except: pass
                    
            transport, protocol = await self.loop.create_datagram_endpoint(
                lambda: UDPProtocol(self), local_addr=('127.0.0.1', 0)
            )
            self.udp_port = transport.get_extra_info('sockname')[1]
            self.udp_transport = transport
            
        self.loop.create_task(self._broadcast_worker())
        
        # The UDP port is known, FFmpeg can now be started safely
        self.ready_event.set()
        
        async with self.server:
            while self.running:
                await asyncio.sleep(0.5)

    async def _handle_client(self, reader, writer):
        client_info = {"writer": writer}
        client_queue = asyncio.Queue(maxsize=300)
        
        try:
            req = await asyncio.wait_for(reader.read(1024), timeout=3.0)
            if b"GET" in req:
                req_lower = req.lower()
                wants_icy = b"icy-metadata: 1" in req_lower
                
                if self.content_type in ["application/ogg", "audio/flac", "audio/wav"]:
                    wants_icy = False
                
                header = (f"HTTP/1.0 200 OK\r\n"
                          f"Content-Type: {self.content_type}\r\n"
                          f"Access-Control-Allow-Origin: *\r\n"
                          f"icy-name: {self.station_name}\r\n"
                          f"icy-genre: {self.genre}\r\n"
                          f"icy-description: {self.description}\r\n"
                          f"Connection: close\r\n"
                          f"Cache-Control: no-cache\r\n")
                if wants_icy: header += f"icy-metaint: {self.meta_int}\r\n"
                header += "\r\n"
                
                writer.write(header.encode())
                
                if self.content_type in ["application/ogg", "audio/flac", "audio/wav"] and self.header_cache:
                    writer.write(self.header_cache)
                    
                await writer.drain()
                
                self.clients.append(client_info)
                self.client_queues.append(client_queue)
                
                counter = self.meta_int
                
                while self.running:
                    try:
                        # If no data is received, the program enters a loop instead of crashing and closing the stream
                        data = await asyncio.wait_for(client_queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue 
                        
                    if not wants_icy:
                        writer.write(data)
                    else:
                        remaining = data
                        while remaining:
                            if counter > 0:
                                chunk = remaining[:counter]
                                writer.write(chunk)
                                counter -= len(chunk)
                                remaining = remaining[len(chunk):]
                            
                            if counter == 0:
                                meta_str = f"StreamTitle='{self.current_title}';".encode('utf-8')
                                blocks = (len(meta_str) + 15) // 16
                                meta_block = bytes([blocks]) + meta_str + b'\x00' * (blocks * 16 - len(meta_str))
                                writer.write(meta_block)
                                counter = self.meta_int
                    
                    await writer.drain()
            else:
                writer.close()
                await writer.wait_closed()
        except:
            pass
        finally:
            if client_queue in self.client_queues:
                self.client_queues.remove(client_queue)
            if client_info in self.clients:
                self.clients.remove(client_info)
            try:
                writer.close()
                await writer.wait_closed()
            except: pass

    async def _broadcast_worker(self):
        while self.running:
            try:
                data = await asyncio.wait_for(self._data_queue.get(), timeout=1.0)
                
                if not self.header_caching_done:
                    if self.content_type == "application/ogg":
                        self.header_cache += data
                        if len(self.header_cache) >= 16384: 
                            self.header_caching_done = True
                    elif self.content_type == "audio/flac":
                        self.header_cache += data
                        if len(self.header_cache) >= 8192:
                            self.header_caching_done = True
                    elif self.content_type == "audio/wav":
                        self.header_cache += data
                        if len(self.header_cache) >= 4096:
                            self.header_caching_done = True
                        
                for q in list(self.client_queues):
                    try: q.put_nowait(data)
                    except asyncio.QueueFull: pass
            except asyncio.TimeoutError: pass
            except Exception: pass

    def broadcast(self, data):
        if not self.use_udp and hasattr(self, '_data_queue'):
            try: self.loop.call_soon_threadsafe(self._data_queue.put_nowait, data)
            except: pass

    def stop(self):
        self.running = False
        self.ready_event.set()
        if hasattr(self, 'loop') and self.loop.is_running():
            def _cleanup():
                for c in list(self.clients):
                    try: c["writer"].close()
                    except: pass
                if hasattr(self, 'udp_transport'):
                    try: self.udp_transport.close()
                    except: pass
            try: self.loop.call_soon_threadsafe(_cleanup)
            except: pass

def get_ffmpeg_path():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ext = ".exe" if platform.system() == "Windows" else ""
    local_ffmpeg = os.path.join(base_dir, f"ffmpeg{ext}")
    return local_ffmpeg if os.path.exists(local_ffmpeg) else "ffmpeg"

# --- MEMORY STRUCTURES FOR THE LIBFDK-AAC DLL ---
class AACENC_InArgs(ctypes.Structure): 
    _fields_ = [("numInSamples", ctypes.c_int), ("numAncBytes", ctypes.c_int)]

class AACENC_OutArgs(ctypes.Structure): 
    _fields_ = [("numOutBytes", ctypes.c_int), ("numInSamples", ctypes.c_int), ("numAncBytes", ctypes.c_int)]

class AACENC_BufDesc(ctypes.Structure): 
    _fields_ = [
        ("numBufs", ctypes.c_int), 
        ("bufs", ctypes.c_void_p), 
        ("bufferIdentifiers", ctypes.c_void_p), 
        ("bufSizes", ctypes.c_void_p), 
        ("bufElSizes", ctypes.c_void_p)
    ]

class StreamManager:
    def __init__(self, stream_config, servers_config, app_settings, log_callback=None):
        self.config = stream_config
        self.servers = servers_config
        self.settings = app_settings
        self.log_callback = log_callback
        
        self.process = None
        self.process_out = None # Used for the DLL pipeline
        self.running = False
        self.start_time = None
        self.last_title = ""
        self.pending_title = ""
        self.pending_title_time = 0
        self.post_title = ""
        self.thread = None
        self.ffmpeg_path = get_ffmpeg_path()
        self.vu_l = -60.0
        self.vu_r = -60.0
        self.peak_l = -60.0
        self.peak_r = -60.0
        self.listeners = -1
        
        # Start-up errors management
        self.last_ffmpeg_error = ""
        self.startup_failed = False
        self.startup_error_msg = ""
        self.is_connecting = False
        
        # SMTP and Alerts variables
        self.silence_start_time = 0
        self.recovery_start_time = 0
        self.is_silent_state = False
        self.unreachable_start_time = 0
        self.is_unreachable_state = False
        self.last_email_sent_time = 0
        self.internal_servers = []
        self.sdp_content = ""
        self.vu_updated = False

    def start(self):
        if self.running: return
        self.running = True
        self.startup_failed = False
        self.startup_error_msg = ""
        self.is_connecting = True
        self.start_time = time.time()
        self.is_silent_state = False
        self.is_unreachable_state = False
        self.silence_start_time = 0
        self.unreachable_start_time = 0
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        
        # Explicit start-up of the Silence Watchdog
        threading.Thread(target=self._monitor_audio_silence_only, daemon=True).start()

    def stop(self):
        self.running = False
        for srv in getattr(self, 'internal_servers', []):
            srv.stop()
        self.internal_servers = []
        for sock, _, _ in getattr(self, 'rtp_sockets', []):
            try: sock.close()
            except: pass
        self.rtp_sockets = []
        
        # Safely and selectively stop the FFmpeg processes associated with this stream
        for proc in [self.process, self.process_out]:
            if proc:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                    proc.wait(timeout=2.0)
                except: pass
                
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=1.0)
                except: pass

                # If the process refuses to stop, we force it to terminate using its exact PID
                try:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait(timeout=1.0)
                except: pass
                
        self.process = None
        self.process_out = None
        self.start_time = None
        self.vu_l = -60.0
        self.vu_r = -60.0
        self.peak_l = -60.0
        self.peak_r = -60.0
        self.listeners = -1
        self.sdp_content = ""
        self.last_title = ""
        self.pending_title = ""

    def _check_unreachable_alert(self):
        if self.unreachable_start_time == 0:
            self.unreachable_start_time = time.time()
        
        if self.config.get("alert_unreachable") and not getattr(self, 'is_unreachable_state', False):
            unreach_timeout = float(self.config.get("unreachable_timeout_sec", 15.0))
            if (time.time() - self.unreachable_start_time) >= unreach_timeout:
                self.is_unreachable_state = True
                
                # --- OVERALL LOGIC FOR UNREACHABLE SERVER ---
                for target_id in self.config.get('targets', []):
                    srv = next((s for s in self.servers if s['id'] == target_id), None)
                    if srv and srv['type'] != 'internal':
                        is_reachable = False
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s.settimeout(2.0)
                            s.connect((srv.get('ip', '127.0.0.1'), int(srv.get('port', 8000))))
                            s.close()
                            is_reachable = True
                        except: pass

                        if not is_reachable:
                            if target_id not in GLOBAL_SERVER_STATE:
                                GLOBAL_SERVER_STATE[target_id] = {'is_down': True, 'email_sent': False, 'log_sent': False}
                                
                            # Logging warning event for unreachable server
                            if not GLOBAL_SERVER_STATE[target_id]['log_sent']:
                                if getattr(self, 'log_callback', None):
                                    self.log_callback("WARNING", f"Streaming server \"{srv.get('name', 'Unknown')}\" is unreachable. Attempting to reconnect.")
                                GLOBAL_SERVER_STATE[target_id]['log_sent'] = True

                            if not GLOBAL_SERVER_STATE[target_id]['email_sent']:
                                GLOBAL_SERVER_STATE[target_id]['email_sent'] = True
                                self._send_email_alert("SERVER_DOWN", srv.get('name', 'Unknown'))

    def _run_loop(self):
        reconnect_delay = int(self.settings.get("reconnect_delay", 5))
        first_attempt = True
        
        # --- HARDWARE INITIALIZATION (ONCE FOR THE ENTIRE LIFETIME OF THE STREAM) ---
        audio_device = self.config.get("audio_device", "")
        import re
        import sounddevice as sd
        target_api = ""
        match = re.match(r'^\[(.*?)\]\s*(.*)$', audio_device)
        if match:
            target_api = match.group(1)
            clean_name = match.group(2).strip()
        else:
            clean_name = audio_device.replace("[WASAPI] ", "").replace("[DirectShow] ", "").strip()
            
        sd_idx = None
        native_rate = 44100
        try:
            hostapis = sd.query_hostapis()
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0 and clean_name in dev['name']:
                    api_name = hostapis[dev['hostapi']]['name'].replace("Windows ", "")
                    if api_name == target_api:
                        sd_idx = i
                        break
            if sd_idx is None:
                for i, dev in enumerate(devices):
                    if dev['max_input_channels'] > 0 and clean_name in dev['name']:
                        sd_idx = i
                        break
            if sd_idx is not None:
                native_rate = int(devices[sd_idx]['default_samplerate'])
        except: pass

        self.capture_sd_idx = sd_idx
        self.capture_native_rate = native_rate

        import queue
        delay_sec = float(str(self.config.get("audio_delay", "0")).replace(',', '.'))
        self.pcm_queue = queue.Queue(maxsize=int((delay_sec + 2) * 25)) 
        threading.Thread(target=self._pcm_writer, daemon=True).start()
        threading.Thread(target=self._monitor_audio, daemon=True).start()

        while self.running:
            self.is_connecting = True
            success = self._start_ffmpeg(is_startup=first_attempt)
            
            if not success:
                if first_attempt:
                    self.is_connecting = False
                    break
                else:
                    self.is_connecting = True 
                    self._check_unreachable_alert() 
                    time.sleep(reconnect_delay)
                    continue
                    
            self.last_title = ""
            self.pending_title = ""
            process_start_time = time.time()
            self.unreachable_start_time = 0 
            self.is_connecting = False

            # --- MONITORING PHASE OF THE CURRENTLY-ACTIVE STREAM ---
            while self.running:
                p_alive = self.process and self.process.poll() is None
                p_out_alive = self.process_out and self.process_out.poll() is None if getattr(self, 'process_out', None) else True
                
                if not p_alive or not p_out_alive:
                    break 
                
                self.is_connecting = False 
                if first_attempt and (time.time() - process_start_time > 6.0):
                    first_attempt = False
                self.unreachable_start_time = 0
                
                # Wait 5 seconds for Icecast to fully register the stream before sending metadata
                if (time.time() - process_start_time) > 5.0:
                    self._update_metadata()
                    
                time.sleep(1)

            # --- EXIT PHASE (DEAD PROCESS) ---
            if self.running:
                self.is_connecting = True 
                if first_attempt:
                    self.startup_failed = True
                    err = getattr(self, 'last_ffmpeg_error', '').strip()
                    if not err: err = "Process crashed within the first 6 seconds (Check Icecast Password/URL)."
                    self.startup_error_msg = f"Failed to connect to Icecast.\n\n[LOGS]:\n{err}"
                    self.running = False
                    if self.log_callback: self.log_callback("ERROR", f"Stream \"{self.config.get('name', 'Unknown')}\" crashed at startup.")
                    break
                else:
                    # Classical disconnection
                    self._check_unreachable_alert()
                    time.sleep(reconnect_delay)
                    
    def _start_ffmpeg(self, is_startup=False):
        targets = [s for s in self.servers if s["id"] in self.config.get("targets", [])]
        if not targets:
            if is_startup:
                self.startup_failed = True
                self.startup_error_msg = "No destination server selected. Please select at least one target."
                self.running = False
            return False

        for srv in targets:
            if srv["type"] in ["internal", "rtp_mpegts", "rtp_pure"]: continue
            try:
                port = int(srv.get('port', 8000))
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(5.0)
                s.connect((srv.get('ip', ''), port))
                s.close()
            except Exception as e:
                if is_startup:
                    self.startup_failed = True
                    self.startup_error_msg = f"Server '{srv.get('name', 'Unknown')}' is offline or unreachable (5s Timeout).\nTarget: {srv.get('ip', '')}:{port}\nSocket Error: {str(e)}"
                    self.running = False
                return False

        format_audio = self.config.get("format", "mp3")
        bitrate = self.config.get("bitrate", "128k")
        gain = self.config.get("gain", "0")
        channels = str(self.config.get("channels", "2"))
        sample_rate = str(self.config.get("sample_rate", "48000"))
        bit_depth = str(self.config.get("bit_depth", "0" if format_audio not in ["wav", "flac"] else "16"))
        s_rate = int(sample_rate)

        # --- AAC-LC & HE-AAC MANAGEMENT (DLL) ---
        if format_audio in ["aac", "aac_lc", "he_aac", "he_aac_v2"]:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            dll_path = os.path.join(base_dir, "libfdk-aac.dll")
            
            if not os.path.exists(dll_path):
                if is_startup:
                    self.startup_failed = True
                    self.startup_error_msg = "DLL MISSING: libfdk-aac.dll not found.\nPlease download the DLL and place it in the application folder to use AAC-LC and HE-AAC V1/V2."
                    self.running = False
                return False
                
            success = self._start_fdk_pipeline(dll_path, format_audio, bitrate, "", gain, channels, sample_rate)
            return success

        # --- OTHER CODECS MANAGEMENT ---
        af_parts = []
        
        if format_audio not in ["wav", "flac"] and bit_depth == "16":
            af_parts.append("aformat=sample_fmts=s16")
            
        audio_filter = ",".join(af_parts) if af_parts else None

        cmd = [
            self.ffmpeg_path, "-y", "-hide_banner", "-nostats",
            "-f", "f32le", "-ar", str(self.capture_native_rate), "-ac", "2", "-i", "pipe:0"
        ]
        if audio_filter:
            cmd.extend(["-af", audio_filter])
        
        if targets:
            cmd.extend(["-map", "0:a"])
            if format_audio == "mp3": cmd.extend(["-c:a", "libmp3lame", "-b:a", bitrate, "-ac", channels, "-ar", str(s_rate)])
            elif format_audio == "mp2": cmd.extend(["-c:a", "mp2", "-b:a", bitrate, "-ac", channels, "-ar", str(s_rate)])
            elif format_audio == "opus": cmd.extend(["-c:a", "libopus", "-application", "audio", "-b:a", bitrate, "-ac", channels, "-ar", str(s_rate)])
            elif format_audio == "ogg": cmd.extend(["-c:a", "libvorbis", "-b:a", bitrate, "-ac", channels, "-ar", sample_rate])
            elif format_audio == "flac": 
                cmd.extend(["-c:a", "flac", "-ac", channels, "-ar", sample_rate])
                if bit_depth == "24": 
                    cmd.extend(["-sample_fmt", "s32"]) # 24-bit
                else: 
                    cmd.extend(["-sample_fmt", "s16"]) # 16-bit
            elif format_audio == "wav": 
                acodec = "pcm_s16le"
                if bit_depth == "24": acodec = "pcm_s24le"
                elif bit_depth == "32": acodec = "pcm_s32le"
                cmd.extend(["-c:a", acodec, "-ac", channels, "-ar", sample_rate])

            br_val = bitrate.replace('k', '') if format_audio not in ["wav", "flac"] else "Lossless"
            ice_genre_str = f"{self.config.get('genre', 'Various')}\r\nice-audio-info: bitrate={br_val}\r\nice-bitrate: {br_val}"
            
            cmd.extend(["-ice_name", self.config.get("radio_name", "WestBroadcast Encoder"), "-ice_description", self.config.get("description", "Live Stream"), "-ice_genre", ice_genre_str])

            muxer_map = {"mp3": "mp3", "mp2": "mp2", "aac": "adts", "aac_lc": "adts", "opus": "ogg", "ogg": "ogg", "flac": "flac", "wav": "wav"}
            ct_map = {"mp3": "audio/mpeg", "mp2": "audio/mpeg", "aac": "audio/aac", "aac_lc": "audio/aac", "opus": "application/ogg", "ogg": "application/ogg", "flac": "audio/flac", "wav": "audio/wav"}
            muxer = muxer_map.get(format_audio, "mp3")
            content_type = ct_map.get(format_audio, "audio/mpeg")
            stream_pass = self.config.get("password", "")
            stream_mount = self.config.get("mount", "/live")

            outputs = []
            self.internal_servers = []
            stream_user = self.config.get('user', 'source')

            for srv in targets:
                if srv["type"] == "icecast2":
                    ice_url = f"icecast://{stream_user}:{stream_pass}@{srv['ip']}:{srv['port']}{stream_mount}"
                    ice_url_escaped = ice_url.replace(":", "\\:")
                    
                    ice_muxer = muxer
                    ice_ct = content_type
                    if format_audio in ["flac", "wav"]:
                        ice_muxer = "matroska"
                        ice_ct = "audio/x-matroska"
                        
                    outputs.append(f"[f={ice_muxer}:content_type={ice_ct}]{ice_url_escaped}")
                elif srv["type"] == "rtp_mpegts":
                    outputs.append(f"[f=mpegts]udp://{srv['ip']}:{srv['port']}?pkt_size=1316")
                elif srv["type"] == "rtp_pure":
                    outputs.append(f"[f=rtp]rtp://{srv['ip']}:{srv['port']}")
                elif srv["type"] == "internal":
                    try:
                        int_srv = InternalHTTPServer(srv['port'], content_type, station_name=self.config.get('radio_name', 'WestBroadcast Encoder'), genre=self.config.get('genre', 'Various'), description=self.config.get('description', 'Live Stream'), initial_title=getattr(self, 'last_title', ''), use_udp=True)
                        self.internal_servers.append(int_srv)
                        outputs.append(f"[f={muxer}]udp://127.0.0.1:{int_srv.udp_port}")
                    except Exception as e:
                        if is_startup:
                            self.startup_failed = True
                            self.startup_error_msg = f"Failed to start Internal Server on port {srv['port']}. Port might be in use.\nError: {str(e)}"
                            self.running = False
                        return False
            
            if len(outputs) > 1: cmd.extend(["-f", "tee", "|".join(outputs)])
            elif len(outputs) == 1:
                srv = targets[0]
                if srv["type"] == "icecast2":
                    ice_url = f"icecast://{stream_user}:{stream_pass}@{srv['ip']}:{srv['port']}{stream_mount}"
                    
                    ice_muxer = muxer
                    ice_ct = content_type
                    if format_audio in ["flac", "wav"]:
                        ice_muxer = "matroska"
                        ice_ct = "audio/x-matroska"
                        
                    cmd.extend(["-content_type", ice_ct, "-f", ice_muxer, ice_url])
                elif srv["type"] == "rtp_mpegts":
                    cmd.extend(["-f", "mpegts", f"udp://{srv['ip']}:{srv['port']}?pkt_size=1316"])
                elif srv["type"] == "rtp_pure":
                    pt = "14" if format_audio in ["mp3", "mp2"] else "96"
                    cmd.extend(["-f", "rtp", "-payload_type", str(pt), "-rtcp_port", "0", f"rtp://{srv['ip']}:{srv['port']}"])
                elif srv["type"] == "internal":
                    cmd.extend(["-f", muxer, f"udp://127.0.0.1:{self.internal_servers[0].udp_port}"])

        kwargs = {'creationflags': 0x08000000} if platform.system() == "Windows" else {}
        try:
            self.last_ffmpeg_error = ""
            self.sdp_content = ""
            self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, bufsize=0, **kwargs)
            
            def read_stderr():
                err_lines = []
                if self.process and self.process.stderr:
                    for line in iter(self.process.stderr.readline, b''):
                        decoded = line.decode('utf-8', errors='ignore').strip()
                        if decoded:
                            err_lines.append(decoded)
                            if len(err_lines) > 15: err_lines.pop(0)
                            self.last_ffmpeg_error = "\n".join(err_lines)
                            
            threading.Thread(target=read_stderr, daemon=True).start()
            return True
        except Exception as e:
            self.last_ffmpeg_error = str(e)
            if is_startup:
                self.startup_failed = True
                self.startup_error_msg = f"Failed to launch FFmpeg: {str(e)}"
                self.running = False
            return False

    def _start_fdk_pipeline(self, dll_path, format_audio, bitrate, audio_device, gain, channels, sample_rate):
        import queue
        import socket
        import base64
        
        # 1. Strict True Frequency Configuration
        s_rate = int(sample_rate)
        b_rate = int(bitrate.replace('k', ''))
        
        if format_audio in ["he_aac", "he_aac_v2"]:
            self.frame_len = 2048
        else:
            self.frame_len = 1024
        
        if format_audio == "he_aac_v2":
            target_ch = 2
        else:
            target_ch = int(self.config.get("channels", "2"))

        # 2. PCM capture
        cmd_in = [
            self.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "f32le", "-ar", str(self.capture_native_rate), "-ac", "2", "-i", "pipe:0",
            "-f", "s16le", "-ac", str(target_ch), "-ar", str(s_rate), "pipe:1"
        ]

        # 3. Direct Icecast transport
        targets = [s for s in self.servers if s["id"] in self.config.get("targets", [])]
        if not targets: return False
        
        self.active_sockets = []
        stream_pass = self.config.get("password", "")
        mnt = self.config.get("mount", "/live")
        mnt = mnt if mnt.startswith('/') else '/' + mnt

        for srv in targets:
            if srv["type"] in ["internal", "rtp_mpegts", "rtp_pure"]: continue
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((srv['ip'], int(srv['port'])))
                user = self.config.get('user', 'source')
                auth = base64.b64encode(f"{user}:{stream_pass}".encode()).decode()
                header = (f"SOURCE {mnt} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n"
                          f"Content-Type: audio/aac\r\n"
                          f"ice-name: {self.config.get('radio_name', 'WestBroadcast Encoder')}\r\n"
                          f"ice-description: {self.config.get('description', 'Live Stream')}\r\n"
                          f"ice-genre: {self.config.get('genre', 'Various')}\r\n"
                          f"ice-audio-info: bitrate={b_rate}\r\n"
                          f"ice-bitrate: {b_rate}\r\n\r\n")
                sock.sendall(header.encode())
                sock.settimeout(2.0)
                if b"200" in sock.recv(1024):
                    sock.settimeout(None)
                    self.active_sockets.append(sock)
                else: sock.close()
            except: pass

        has_internal = any(s["type"] == "internal" for s in targets)
        has_rtp = any(s["type"] in ["rtp_mpegts", "rtp_pure"] for s in targets)
        
        if not self.active_sockets and not has_internal and not has_rtp:
            self.last_ffmpeg_error = "Connection failed to target servers."
            return False

        self.internal_servers = getattr(self, 'internal_servers', [])
        self.rtp_sockets = []
        for srv in targets:
            if srv["type"] in ["rtp_mpegts", "rtp_pure"]:
                usock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.rtp_sockets.append((usock, srv['ip'], int(srv['port'])))
            elif srv["type"] == "internal":
                try:
                    int_srv = InternalHTTPServer(srv['port'], "audio/aac", station_name=self.config.get('radio_name', 'WestBroadcast Encoder'), genre=self.config.get('genre', 'Various'), description=self.config.get('description', 'Live Stream'), initial_title=getattr(self, 'last_title', ''), use_udp=False)
                    self.internal_servers.append(int_srv)
                except Exception as e:
                    self.last_ffmpeg_error = f"Internal Server error on port {srv['port']}: {e}"
                    return False

        # 4. Initializing the FDK-AAC DLL
        try:
            fdk = ctypes.CDLL(dll_path)
            fdk.aacEncOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.c_uint]
            fdk.aacEncoder_SetParam.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
            fdk.aacEncEncode.argtypes = [ctypes.c_void_p, ctypes.POINTER(AACENC_BufDesc), ctypes.POINTER(AACENC_BufDesc), ctypes.POINTER(AACENC_InArgs), ctypes.POINTER(AACENC_OutArgs)]
            
            self.h_fdk = ctypes.c_void_p(None)
            fdk.aacEncOpen(ctypes.byref(self.h_fdk), 0, target_ch)
            
            # Paramétrage AOT natif : 29 = HE-AAC v2, 5 = HE-AAC v1, 2 = AAC-LC
            if format_audio == "he_aac_v2":
                fdk.aacEncoder_SetParam(self.h_fdk, 0x0100, 29)
            elif format_audio == "he_aac":
                fdk.aacEncoder_SetParam(self.h_fdk, 0x0100, 5)
            else:
                fdk.aacEncoder_SetParam(self.h_fdk, 0x0100, 2)
                
            fdk.aacEncoder_SetParam(self.h_fdk, 0x0103, s_rate)
            fdk.aacEncoder_SetParam(self.h_fdk, 0x0106, target_ch)
            fdk.aacEncoder_SetParam(self.h_fdk, 0x0101, b_rate * 1000)
            
            fdk.aacEncoder_SetParam(self.h_fdk, 0x0302, 0) 
            fdk.aacEncoder_SetParam(self.h_fdk, 0x0300, 2) 
            fdk.aacEncEncode(self.h_fdk, None, None, None, None)
        except Exception as e:
            self.last_ffmpeg_error = f"DLL ERROR: {e}"
            return False

        # 5. Queue and Process Launch
        self.q = queue.Queue(maxsize=1000)
        kwargs = {'creationflags': 0x08000000} if platform.system() == "Windows" else {}
        self.process = subprocess.Popen(cmd_in, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, **kwargs)

        def network_worker():
            try:
                while self.running:
                    try:
                        data = self.q.get(timeout=0.2)
                        for s in list(self.active_sockets):
                            try: s.sendall(data)
                            except: 
                                s.close()
                                if s in self.active_sockets: self.active_sockets.remove(s)
                                
                        for int_srv in self.internal_servers:
                            int_srv.broadcast(data)
                            
                        for usock, ip, port in getattr(self, 'rtp_sockets', []):
                            try: usock.sendto(data, (ip, port))
                            except: pass
                            
                        if not self.active_sockets and not getattr(self, 'internal_servers', []) and not getattr(self, 'rtp_sockets', []): break
                        self.q.task_done()
                    except queue.Empty: continue
            except: pass
            finally:
                # If the connection is lost, we stop the FFmpeg process without stopping the stream capture
                if self.running and self.process:
                    try: 
                        self.process.terminate()
                        self.process.kill()
                    except: pass

        threading.Thread(target=network_worker, daemon=True).start()

        # Encoding Loop (Accumulator and Stable Memory)
        def encode_loop():
            self.f_sz = self.frame_len * target_ch * 2
            self.b_pcm = ctypes.create_string_buffer(self.f_sz)
            self.b_aac = ctypes.create_string_buffer(65536)
            self.p_i = (ctypes.c_void_p * 1)(ctypes.addressof(self.b_pcm))
            self.s_i = (ctypes.c_int * 1)(self.f_sz)
            self.id_i = (ctypes.c_int * 1)(0)
            self.e_i = (ctypes.c_int * 1)(2)
            self.p_o = (ctypes.c_void_p * 1)(ctypes.addressof(self.b_aac))
            self.s_o = (ctypes.c_int * 1)(65536)
            self.id_o = (ctypes.c_int * 1)(3)
            self.e_o = (ctypes.c_int * 1)(1)
            d_i = AACENC_BufDesc(1, ctypes.addressof(self.p_i), ctypes.addressof(self.id_i), ctypes.addressof(self.s_i), ctypes.addressof(self.e_i))
            d_o = AACENC_BufDesc(1, ctypes.addressof(self.p_o), ctypes.addressof(self.id_o), ctypes.addressof(self.s_o), ctypes.addressof(self.e_o))
            a_i = AACENC_InArgs(self.frame_len * target_ch, 0); a_o = AACENC_OutArgs(0, 0, 0)
            acc = bytearray()
            try:
                while self.running and self.process.poll() is None:
                    chunk = self.process.stdout.read(self.f_sz - len(acc))
                    if not chunk: break
                    acc.extend(chunk)
                    if len(acc) < self.f_sz: continue
                    ctypes.memmove(self.b_pcm, bytes(acc), self.f_sz)
                    acc.clear()
                    
                    self.s_i[0] = self.f_sz; self.s_o[0] = 65536
                    a_i.numInSamples = self.frame_len * target_ch
                    if fdk.aacEncEncode(self.h_fdk, ctypes.byref(d_i), ctypes.byref(d_o), ctypes.byref(a_i), ctypes.byref(a_o)) == 0:
                        if a_o.numOutBytes > 0:
                            if not self.q.full(): self.q.put(self.b_aac.raw[:a_o.numOutBytes])
            finally:
                try: fdk.aacEncClose(ctypes.byref(self.h_fdk))
                except: pass
                for s in self.active_sockets: s.close()

        threading.Thread(target=encode_loop, daemon=True).start()
        return True

    def _monitor_audio_silence_only(self):
        loss_thresh = float(self.config.get("loss_threshold_db", -45.0))
        loss_timeout = float(self.config.get("loss_timeout_sec", 10.0))
        rec_thresh = float(self.config.get("recovery_threshold_db", -35.0))
        rec_timeout = float(self.config.get("recovery_timeout_sec", 5.0))
        alert_silent = self.config.get("alert_silent", False)

        while self.running:
            time.sleep(0.5)
            if not alert_silent: continue
            
            current_vu = max(self.vu_l, self.vu_r)
            now = time.time()

            if current_vu < loss_thresh:
                self.recovery_start_time = 0
                if self.silence_start_time == 0:
                    self.silence_start_time = now
                else:
                    if (now - self.silence_start_time) >= loss_timeout and not self.is_silent_state:
                        self.is_silent_state = True
                        self._send_email_alert("SILENT", f"Silence detected on \"{self.config.get('name', 'Unknown')}\" (Below {loss_thresh}dB for {loss_timeout}s)")
            else:
                self.silence_start_time = 0
                if self.is_silent_state:
                    if self.recovery_start_time == 0:
                        self.recovery_start_time = now
                    else:
                        if (now - self.recovery_start_time) >= rec_timeout:
                            self.is_silent_state = False
                            self._send_email_alert("RECOVERED", f"Stream \"{self.config.get('name', 'Unknown')}\" is no longer silent.", bypass_spam=True)

    def _pcm_writer(self):
        import queue
        import time
        try:
            while self.running:
                try:
                    scheduled_time, data = self.pcm_queue.get(timeout=0.1)
                    
                    current_time = time.time()
                    if current_time < scheduled_time:
                        time.sleep(scheduled_time - current_time)
                        
                    if self.process and self.process.poll() is None and getattr(self.process, 'stdin', None):
                        try:
                            self.process.stdin.write(data)
                            self.process.stdin.flush()
                        except: pass
                except queue.Empty: continue
                except Exception: pass
        except: pass

    def _monitor_audio(self):
        if getattr(self, 'capture_sd_idx', None) is None: return

        def audio_callback(indata, frames, time_info, status):
            if not self.running: raise sd.CallbackAbort()
            
            gain_db = float(self.config.get("gain", "0"))
            gain_multiplier = 10 ** (gain_db / 20.0)
            data_with_gain = indata * gain_multiplier
            
            pk_l = np.max(np.abs(data_with_gain[:, 0])) if data_with_gain.shape[1] >= 1 else 0
            pk_r = np.max(np.abs(data_with_gain[:, 1])) if data_with_gain.shape[1] >= 2 else pk_l
            
            db_l = float(20 * np.log10(pk_l) if pk_l > 1e-5 else -60.0)
            db_r = float(20 * np.log10(pk_r) if pk_r > 1e-5 else -60.0)
            
            self.peak_l = max(getattr(self, 'peak_l', -60.0), db_l)
            self.peak_r = max(getattr(self, 'peak_r', -60.0), db_r)
            
            self.vu_l = db_l
            self.vu_r = db_r

            if hasattr(self, 'pcm_queue'):
                import queue
                import time
                delay_sec = float(str(self.config.get("audio_delay", "0")).replace(',', '.'))
                release_time = time.time() + delay_sec
                try:
                    self.pcm_queue.put_nowait((release_time, data_with_gain.astype(np.float32).tobytes()))
                except queue.Full:
                    pass

        try:
            import sounddevice as sd
            # Strict Bitperfect Capture: Native frequency and explicit Float32 type
            with sd.InputStream(device=self.capture_sd_idx, channels=2, samplerate=self.capture_native_rate, dtype='float32', blocksize=2048, latency='high', callback=audio_callback):
                while self.running:
                    sd.sleep(100)
        except Exception as e: 
            if getattr(self, 'log_callback', None): self.log_callback("ERROR", f"Audio input error: {e}")

    def _update_metadata(self):
        now = time.time()
        # Secure variable definition for the entire script
        stream_mount = self.config.get("mount", "/live")
        stream_pass = self.config.get("password", "")
        targets = [s for s in self.servers if s["id"] in self.config.get("targets", [])]
        
        # SDP "DIRECT-PLAY" GENERATOR
        if not getattr(self, 'sdp_content', ""):
            for srv in targets:
                if srv["type"] == "rtp_pure":
                    fmt = self.config.get("format", "mp3")
                    sr = int(self.config.get("sample_rate", "48000"))
                    ch = int(self.config.get("channels", "2"))
                    br = self.config.get("bitrate", "128k").replace('k', '')
                    
                    srv_ip = srv['ip']
                    if srv_ip in ['127.0.0.1', 'localhost']:
                        import socket
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            s.connect(("8.8.8.8", 80))
                            srv_ip = s.getsockname()[0]
                            s.close()
                        except: pass
                    
                    sdp =  "v=0\r\n"
                    sdp += f"o=- 0 0 IN IP4 {srv_ip}\r\n"
                    sdp += f"s={self.config.get('name', 'Stream')}\r\n"
                    sdp += f"c=IN IP4 {srv_ip}\r\n"
                    sdp += "t=0 0\r\n"
                    sdp += "a=type:broadcast\r\n"
                    sdp += "a=control:*\r\n"
                    
                    if fmt in ["mp3", "mp2"]:
                        sdp += f"m=audio {srv['port']} RTP/AVP 14\r\n"
                        sdp += f"b=AS:{br}\r\n"
                        sdp += "a=rtpmap:14 MPA/90000\r\n"
                    elif fmt == "opus":
                        sdp += f"m=audio {srv['port']} RTP/AVP 96\r\n"
                        sdp += f"b=AS:{br}\r\n"
                        sdp += "a=rtpmap:96 opus/48000/2\r\n"
                    elif fmt in ["aac", "he_aac", "he_aac_v2", "aac_lc"]:
                        aac_cfg = "1190" if sr == 48000 else "1210"
                        if ch == 1: aac_cfg = "1188" if sr == 48000 else "1208"
                        sdp += f"m=audio {srv['port']} RTP/AVP 96\r\n"
                        sdp += f"b=AS:{br}\r\n"
                        sdp += f"a=rtpmap:96 mpeg4-generic/{sr}/{ch}\r\n"
                        sdp += f"a=fmtp:96 streamtype=5;profile-level-id=1;mode=AAC-hbr;config={aac_cfg};sizelength=13;indexlength=3;indexdeltalength=3\r\n"
                    
                    # We explicitly include RTCP deactivation in the SDP
                    sdp += "a=rtcp-mux\r\n"
                    
                    self.sdp_content = sdp
                    break

        # 2. CALCULATING THE NUMBER OF LISTENERS (Every 15 seconds)
        if now - getattr(self, 'last_listener_check', 0) >= 15.0:
            self.last_listener_check = now
            def fetch_listeners():
                total_listeners = -1
                has_fetched = False
                for srv in targets:
                    if srv["type"] == "internal":
                        if not has_fetched: 
                            total_listeners = 0
                            has_fetched = True
                        for int_srv in getattr(self, 'internal_servers', []):
                            if int_srv.port == int(srv['port']):
                                total_listeners += len(int_srv.clients)
                    try:
                        if srv["type"] == "icecast2":
                            st = requests.get(f"http://{srv['ip']}:{srv['port']}/status-json.xsl", timeout=2).json()
                            sources = st.get('icestats', {}).get('source', [])
                            if isinstance(sources, dict): sources = [sources]
                            for src in sources:
                                if isinstance(src, dict) and src.get('listenurl', '').endswith(stream_mount):
                                    if not has_fetched: 
                                        total_listeners = 0
                                        has_fetched = True
                                    total_listeners += int(src.get('listeners', 0))
                    except: pass
                self.listeners = total_listeners
            threading.Thread(target=fetch_listeners, daemon=True).start()

        # 3. COLLECTING THE CURRENTLY PLAYING METADATA
        meta_source = self.config.get("meta_source", "none")
        if meta_source == "none": return
        
        title = getattr(self, 'pending_title', "")
        
        try:
            # HTTP/HTTPS URL AS SOURCE
            if meta_source == "http":
                http_url = self.config.get("meta_http_url", "").strip()
                if http_url:
                    try: interval = float(self.config.get("meta_http_interval", 7.0))
                    except: interval = 7.0
                    
                    if now - getattr(self, 'last_http_check_time', 0) >= interval:
                        self.last_http_check_time = now
                        try: title = requests.get(http_url, timeout=3).text.strip()
                        except: pass

            # LOCAL FILE AS SOURCE
            elif meta_source == "file":
                file_path = self.config.get("meta_file_path", "").strip()
                if file_path and os.path.exists(file_path):
                    if now - getattr(self, 'last_file_stat_time', 0) >= 2.0:
                        self.last_file_stat_time = now
                        mtime = os.path.getmtime(file_path)
                        if mtime != getattr(self, 'last_txt_mtime', 0):
                            self.last_txt_mtime = mtime
                            try:
                                with open(file_path, 'r', encoding='utf-8') as f: 
                                    title = f.read().strip()
                            except UnicodeDecodeError:
                                # Fallback vital si le fichier n'est pas en UTF-8 pur
                                with open(file_path, 'r', encoding='latin-1') as f: 
                                    title = f.read().strip()

            # POST FUNCTION AS SOURCE
            elif meta_source == "post":
                title = getattr(self, 'post_title', "")
                
            # FIXED TEXT AS SOURCE
            elif meta_source == "fixed":
                title = self.config.get("meta_fixed_text", "").strip()
                
        except Exception:
            pass
            
        # 4. APPLICATION OF THE TITLE (Secured with periodic re-encryption)
        if title and title != self.pending_title:
            self.pending_title = title
            self.pending_title_time = now
            
        if self.pending_title and self.pending_title != getattr(self, 'last_title', ""):
            try: meta_delay = float(self.config.get("meta_delay", 0))
            except: meta_delay = 0.0
            
            if (now - self.pending_title_time) >= meta_delay:
                self.last_title = self.pending_title
                
                # INTERNAL SERVER update
                for int_srv in getattr(self, 'internal_servers', []):
                    try: int_srv.set_metadata(self.last_title)
                    except: pass
                
                # ICECAST update
                for srv in targets:
                    if srv["type"] == "icecast2":
                        def send_icecast_meta(ip, port, mount, song, pwd, user):
                            try:
                                requests.get(
                                    f"http://{ip}:{port}/admin/metadata", 
                                    params={"mount": mount, "mode": "updinfo", "song": song, "charset": "UTF-8"}, 
                                    auth=(user, pwd), 
                                    timeout=3
                                )
                            except: pass
                        threading.Thread(
                            target=send_icecast_meta, 
                            args=(srv['ip'], srv['port'], stream_mount, self.last_title, stream_pass, self.config.get("user", "source")), 
                            daemon=True
                        ).start()

    def _send_email_alert(self, status, context_data, bypass_spam=False):
        smtp = self.settings.get("smtp", {})
        if not smtp.get("enabled") or not smtp.get("server"): return
        recipients = [r.strip() for r in smtp.get("recipients", []) if r.strip()]
        if not recipients: return
        
        now = time.time()
        spam_delay_sec = float(smtp.get("spam_delay", 10)) * 60.0
        
        # The spam bypass is ignored in the event of server outages (managed by GLOBAL_SERVER_STATE)
        if status not in ["SERVER_DOWN", "SERVER_RECOVERED"] and not bypass_spam:
            if (now - self.last_email_sent_time) < spam_delay_sec:
                return 
                
        if status not in ["SERVER_DOWN", "SERVER_RECOVERED"]:
            self.last_email_sent_time = now
            
        from datetime import datetime
        dt_now = datetime.now()
        date_str = dt_now.strftime("%d/%m/%Y")
        time_str = dt_now.strftime("%H:%M:%S")
        
        instance_name = self.settings.get("instance_name", "").strip()
        prefix = f"[WestBroadcast Encoder - {instance_name}]" if instance_name else "[WestBroadcast Encoder]"
        stream_name_up = self.config.get("name", "Unknown").upper()
        
        subject = ""
        body = ""
        
        if status == "SILENT":
            subject = f"{prefix} {stream_name_up} is SILENT!"
            body = f"{stream_name_up} is currently SILENT!\nAnomaly detected on: {date_str} at {time_str}\n\nYou will be notified as soon as the audio is restored."
        elif status == "RECOVERED":
            subject = f"{prefix} Recovery Notification for {stream_name_up}"
            body = f"{stream_name_up} is no longer silent.\nNormal broadcasting has resumed.\n\nNotification sent on: {date_str} at {time_str}"
        elif status == "SERVER_DOWN":
            srv_name = context_data
            subject = f"{prefix} Streaming server {srv_name.upper()} is UNREACHABLE!"
            body = f"Connection to the \"{srv_name}\" streaming server has been lost!\nAnomaly detected on: {date_str} at {time_str}\n\nYou will be notified as soon as the connection is restored."
        elif status == "SERVER_RECOVERED":
            srv_name = context_data
            subject = f"{prefix} Recovery Notification for streaming server {srv_name.upper()}"
            body = f"Connection to the \"{srv_name}\" streaming server has been restored.\nAll broadcasting to this server has resumed.\n\nNotification sent on: {date_str} at {time_str}"
        
        try:
            msg = EmailMessage()
            msg.set_content(body)
            msg['Subject'] = subject
            msg['From'] = smtp.get("sender", "alert@westbroadcast")
            msg['To'] = ", ".join(recipients)
            msg['Date'] = formatdate(localtime=True)

            context = ssl.create_default_context()
            if smtp.get("tls"):
                s = smtplib.SMTP_SSL(smtp["server"], int(smtp.get("port", 587)), context=context, timeout=10)
            else:
                s = smtplib.SMTP(smtp["server"], int(smtp.get("port", 587)), timeout=10)
                s.ehlo()
                s.starttls(context=context)
                s.ehlo()
                
            s.login(smtp["user"], smtp["pass"])
            s.send_message(msg)
            s.quit()
            if self.log_callback: self.log_callback("INFO", f"Email sent via SMTP.")
        except Exception as e: 
            if self.log_callback: self.log_callback("ERROR", f"Failed to send an email via SMTP: {str(e)}")

    def _monitor_audio_silence_only(self):
        loss_thresh = float(self.config.get("loss_threshold_db", -45.0))
        loss_timeout = float(self.config.get("loss_timeout_sec", 10.0))
        rec_thresh = float(self.config.get("recovery_threshold_db", -35.0))
        rec_timeout = float(self.config.get("recovery_timeout_sec", 5.0))
        alert_silent = self.config.get("alert_silent", False)

        while self.running:
            time.sleep(0.5)
            
            # --- SERVER RECOVERY LOGIC (Independent of the silent alert) ---
            if getattr(self, 'is_unreachable_state', False):
                # If the stream is currently encoding again (i.e. connected to the server)
                if self.process and self.process.poll() is None:
                    self.is_unreachable_state = False
                    # Check whether this recovery restores the server globally
                    for target_id in self.config.get('targets', []):
                        if target_id in GLOBAL_SERVER_STATE and GLOBAL_SERVER_STATE[target_id]['is_down']:
                            srv = next((s for s in self.servers if s['id'] == target_id), None)
                            if srv:
                                GLOBAL_SERVER_STATE[target_id]['is_down'] = False
                                GLOBAL_SERVER_STATE[target_id]['email_sent'] = False
                                GLOBAL_SERVER_STATE[target_id]['log_sent'] = False
                                if getattr(self, 'log_callback', None):
                                    self.log_callback("RECOVERY", f"Connection to streaming server \"{srv.get('name', 'Unknown')}\" has been restored.")
                                self._send_email_alert("SERVER_RECOVERED", srv.get('name', 'Unknown'), bypass_spam=True)
            
            if not alert_silent: continue
            
            current_vu = max(self.vu_l, self.vu_r)
            now = time.time()

            if current_vu < loss_thresh:
                self.recovery_start_time = 0
                if self.silence_start_time == 0:
                    self.silence_start_time = now
                else:
                    if (now - self.silence_start_time) >= loss_timeout and not self.is_silent_state:
                        self.is_silent_state = True
                        if getattr(self, 'log_callback', None): 
                            self.log_callback("WARNING", f"Silence detected on \"{self.config.get('name', 'Unknown')}\".")
                        self._send_email_alert("SILENT", "")
            else:
                self.silence_start_time = 0
                if self.is_silent_state:
                    if self.recovery_start_time == 0:
                        self.recovery_start_time = now
                    else:
                        if (now - self.recovery_start_time) >= rec_timeout:
                            self.is_silent_state = False
                            if getattr(self, 'log_callback', None): 
                                self.log_callback("RECOVERY", f"Stream \"{self.config.get('name', 'Unknown')}\" is no longer silent.")
                            self._send_email_alert("RECOVERED", "", bypass_spam=True)

    def get_status(self):
        return {
            "id": self.config["id"],
            "running": self.running,
            "connecting": getattr(self, 'is_connecting', False),
            "error": getattr(self, 'startup_failed', False),
            "error_msg": getattr(self, 'startup_error_msg', ""),
            "uptime": int(time.time() - self.start_time) if self.running and self.start_time else 0,
            "title": self.last_title,
            "vu_l": self.vu_l,
            "vu_r": self.vu_r,
            "listeners": self.listeners,
            "sdp": getattr(self, 'sdp_content', "")
        }