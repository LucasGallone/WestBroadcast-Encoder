import json
import os
import sys
import psutil
import threading
import webbrowser
import platform
import subprocess
import time
import socket
import logging
from flask import Flask, request, jsonify, render_template, session, redirect, send_file, cli
from flask_socketio import SocketIO
import tkinter as tk
from tkinter import messagebox
from stream_manager import StreamManager, get_ffmpeg_path

cli.show_server_banner = lambda *args: None
logging.getLogger('werkzeug').setLevel(logging.ERROR)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'), static_folder=os.path.join(BASE_DIR, 'static'))
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SESSION_COOKIE_NAME'] = 'wb_encoder_session'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
streams_engines = {}
SYSTEM_START_TIME = time.time()

# --- Internal logs management ---
INTERNAL_LOGS = []

# --- Login bruteforce protection (Access locked for 90 seconds after 3 failed attempts) ---
LOGIN_ATTEMPTS = {}

def add_log(level, event):
    timestamp = time.strftime("%d/%m/%Y %H:%M:%S")
    INTERNAL_LOGS.append({"timestamp": timestamp, "level": level, "event": event})
    if len(INTERNAL_LOGS) > 1000:
        INTERNAL_LOGS.pop(0)
    print(f"{timestamp} - [{level}] {event}")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"
    
# --- Configuration ---
def load_config():
    if not os.path.exists(CONFIG_FILE):
        default = {
            "password": "admin", 
            "settings": {
                "language": "en",
                "instance_name": "",
                "hide_instance_on_login": False,
                "dark_mode": False,
                "reconnect_delay": 5, "enable_monitoring": False, "web_port": 8090,
                "smtp": {
                    "enabled": False, "server": "", "port": 587, "user": "", "pass": "", 
                    "sender": "", "tls": False, "spam_delay": 10,
                    "recipients": ["", "", "", ""]
                }
            }, 
            "servers": [], 
            "streams": []
        }
        save_config(default)
        return default
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f: 
        try:
            data = json.load(f)
            if 'streams' not in data: data['streams'] = []
            if 'servers' not in data: data['servers'] = []
            for srv in data['servers']:
                if 'user' not in srv: srv['user'] = "source"
            if 'settings' not in data: data['settings'] = {}
            s = data['settings']
            if 'web_port' not in s: s['web_port'] = 8090
            if 'language' not in s: s['language'] = 'en'
            
            # Instance options
            if 'instance_name' not in s: s['instance_name'] = ""
            if 'hide_instance_on_login' not in s: s['hide_instance_on_login'] = False
            if 'dark_mode' not in s: s['dark_mode'] = False
            
            # SMTP configuration
            if 'smtp' not in s: 
                s['smtp'] = {"enabled": False, "server": "", "port": 587, "user": "", "pass": "", "sender": "", "tls": False, "spam_delay": 10, "recipients": ["", "", "", ""]}
            if 'recipients' not in s['smtp'] or len(s['smtp']['recipients']) < 4:
                s['smtp']['recipients'] = ["", "", "", ""]
            if 'tls' not in s['smtp']: s['smtp']['tls'] = False
            if 'spam_delay' not in s['smtp']: s['smtp']['spam_delay'] = 10
            
            # Streams settings
            for st in data['streams']:
                if 'auto_start' not in st: st['auto_start'] = False
                if 'user' not in st: st['user'] = "source"
                if 'loss_threshold_db' not in st: st['loss_threshold_db'] = -45.0
                if 'loss_timeout_sec' not in st: st['loss_timeout_sec'] = 10.0
                if 'recovery_threshold_db' not in st: st['recovery_threshold_db'] = -35.0
                if 'recovery_timeout_sec' not in st: st['recovery_timeout_sec'] = 5.0
                if 'alert_silent' not in st: st['alert_silent'] = False
                if 'alert_unreachable' not in st: st['alert_unreachable'] = False
                if 'unreachable_timeout_sec' not in st: st['unreachable_timeout_sec'] = 15.0
                if 'sample_rate' not in st: st['sample_rate'] = "48000"
                if 'channels' not in st: st['channels'] = "2"
                if 'bit_depth' not in st:
                    if st.get('format') == 'wav': st['bit_depth'] = "32"
                    elif st.get('format') == 'flac': st['bit_depth'] = "24"
                    else: st['bit_depth'] = "0"
                if 'audio_delay' not in st: st['audio_delay'] = "0.000"
                if 'meta_delay' not in st: st['meta_delay'] = 0
                
                # Currently playing metadata configuration
                if 'meta_source' not in st:
                    if st.get('enable_metadata', False):
                        if st.get('txt_path', '').startswith('http'):
                            st['meta_source'] = 'http'
                            st['meta_http_url'] = st.get('txt_path', '')
                        else:
                            st['meta_source'] = 'file'
                            st['meta_file_path'] = st.get('txt_path', '')
                    else:
                        st['meta_source'] = 'none'
                if 'meta_file_path' not in st: st['meta_file_path'] = ""
                if 'meta_http_url' not in st: st['meta_http_url'] = ""
                if 'meta_custom_id' not in st: st['meta_custom_id'] = "my-radio-station"
                if 'meta_http_interval' not in st: st['meta_http_interval'] = 7
                if 'meta_post_key' not in st: st['meta_post_key'] = ""
                if 'meta_fixed_text' not in st: st['meta_fixed_text'] = ""

            return data
        except:
            return {"password": "admin", "settings": {"instance_name": "", "hide_instance_on_login": False, "dark_mode": False, "reconnect_delay": 5, "enable_monitoring": False, "web_port": 8090, "smtp": {"enabled": False, "server": "", "port": 587, "user": "", "pass": "", "sender": "", "tls": False, "spam_delay": 10, "recipients": ["", "", "", ""]}}, "servers": [], "streams": []}

def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f: 
        json.dump(data, f, indent=4)

def list_audio_devices():
    try:
        import sounddevice as sd
        devices = []
        hostapis = sd.query_hostapis()
        for d in sd.query_devices():
            if d['max_input_channels'] > 0:
                # Collects the audio engine name (WASAPI, MME, ...)
                api_name = hostapis[d['hostapi']]['name'].replace("Windows ", "")
                devices.append(f"[{api_name}] {d['name']}")
        return sorted(list(set(devices))) if devices else ["No audio devices found. Make sure the software has the necessary permissions to detect the devices."]
    except Exception as e:
        return [f"Error: {str(e)}"]

@app.before_request
def check_auth():
    if request.path.startswith('/api/metadata/'):
        return
    if request.path.startswith('/api/') and not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

@app.route('/', methods=['GET', 'POST'])
def index():
    error = ""
    client_ip = request.remote_addr
    now = time.time()
    config = load_config()
    lang = config.get('settings', {}).get('language', 'en')
    
    # Bruteforce protection: Storing the IP address after 3 failed attempts
    if client_ip not in LOGIN_ATTEMPTS:
        LOGIN_ATTEMPTS[client_ip] = {"count": 0, "lock_until": 0}
        
    # Bruteforce protection: Temporary access block for 90 seconds after 3 failed attempts
    if LOGIN_ATTEMPTS[client_ip]["lock_until"] > now:
        error = "Due to multiple failed login attempts, your access to the server has been blocked for 90 seconds. Please wait and try again." if lang == 'en' else "En raison de multiples tentatives de connexion échouées, votre accès est temporairement bloqué pendant 90 secondes. Veuillez patienter, puis réessayez."
        return render_template('index.html', logged_in=session.get('logged_in'), error=error, config=config, lang=lang)

    if request.method == 'POST':
        if request.form.get('password') == config.get('password', 'admin'):
            session['logged_in'] = True
            LOGIN_ATTEMPTS[client_ip] = {"count": 0, "lock_until": 0}
            add_log("AUTH", f"Successful login from IP {client_ip}" if lang == 'en' else f"Connexion réussie depuis l'IP {client_ip}")
            return redirect('/')
        else:
            LOGIN_ATTEMPTS[client_ip]["count"] += 1
            if LOGIN_ATTEMPTS[client_ip]["count"] >= 3:
                LOGIN_ATTEMPTS[client_ip]["lock_until"] = now + 90
                error = "Due to multiple failed login attempts, your access to the server has been blocked for 90 seconds. Please wait and try again." if lang == 'en' else "En raison de multiples tentatives de connexion échouées, votre accès est temporairement bloqué pendant 90 secondes. Veuillez patienter, puis réessayez."
            else:
                error = "Incorrect password. Please try again." if lang == 'en' else "Mot de passe incorrect. Veuillez réessayer."
            add_log("AUTH", f"Failed login attempt from IP {client_ip}" if lang == 'en' else f"Tentative de connexion échouée depuis l'IP {client_ip}")

    return render_template('index.html', logged_in=session.get('logged_in'), error=error, config=config, lang=lang)

def get_restarting_page(message, target_port=None, lang='en'):
    redirect_url = "'/'"
    if target_port:
        redirect_url = f"window.location.protocol + '//' + window.location.hostname + ':{target_port}/'"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>System Restart - WestBroadcast Encoder</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; text-align: center; padding-top: 100px; background: #f4f7f6; color: #333; height: 100vh; margin: 0; }}
            .card {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); display: inline-block; min-width: 400px; }}
            h2 {{ color: #0d6efd; margin-top: 0; font-weight: bold; font-size: 1.5rem; }}
            .loader {{ border: 4px solid #f3f3f3; border-top: 4px solid #0d6efd; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="loader"></div>
            <h2>{message}</h2>
            <p>{"Please wait. You will be automatically redirected to the login page in 5 seconds." if lang == 'en' else "Veuillez patienter. Vous serez automatiquement redirigé vers la page de connexion dans 5 secondes."}</p>
        </div>
        <script>
            setTimeout(function() {{ window.location.href = {redirect_url}; }}, 5000);
        </script>
    </body>
    </html>
    """

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/')

@app.route('/api/system_stats')
def system_stats():
    return jsonify({"cpu": psutil.cpu_percent(interval=0.1), "ram": psutil.virtual_memory().percent})

@app.route('/api/streams_status')
def streams_status():
    return jsonify([engine.get_status() for engine in streams_engines.values()])

@app.route('/api/start/<stream_id>')
def start_stream(stream_id):
    if stream_id in streams_engines:
        if not streams_engines[stream_id].running:
            streams_engines[stream_id].start()
            lang = load_config().get('settings', {}).get('language', 'en')
            add_log("SYSTEM", f"Stream \"{streams_engines[stream_id].config['name']}\" started." if lang == 'en' else f"Flux \"{streams_engines[stream_id].config['name']}\" démarré.")
    return jsonify({"status": "ok"})

@app.route('/api/stop/<stream_id>')
def stop_stream(stream_id):
    if stream_id in streams_engines:
        if streams_engines[stream_id].running:
            streams_engines[stream_id].stop()
            lang = load_config().get('settings', {}).get('language', 'en')
            add_log("SYSTEM", f"Stream \"{streams_engines[stream_id].config['name']}\" stopped." if lang == 'en' else f"Flux \"{streams_engines[stream_id].config['name']}\" arrêté.")
    return jsonify({"status": "ok"})

@app.route('/api/sdp/<stream_id>')
def download_sdp(stream_id):
    if stream_id in streams_engines and streams_engines[stream_id].sdp_content:
        from flask import Response
        sdp_data = streams_engines[stream_id].sdp_content
        return Response(sdp_data, mimetype="application/sdp", headers={"Content-Disposition": f"attachment;filename=stream_{stream_id}.sdp"})
    return "SDP file not available or stream offline.", 404

@app.route('/api/config', methods=['GET'])
def get_config():
    config = load_config()
    config['audio_devices_list'] = list_audio_devices() 
    config['local_ip'] = get_local_ip()
    config['fdk_installed'] = os.path.exists(os.path.join(BASE_DIR, "libfdk-aac.dll"))
    config['system_start_time'] = SYSTEM_START_TIME
    return jsonify(config)

@app.route('/api/config', methods=['POST'])
def update_config():
    old_config = load_config()
    new_config = request.json
    lang = new_config.get('settings', {}).get('language', 'en')
    
    # Comparing webserver ports before saving
    old_port = int(old_config.get('settings', {}).get('web_port', 8090))
    new_port = int(new_config.get('settings', {}).get('web_port', 8090))
    
    save_config(new_config)
    
    if old_port != new_port:
        add_log("SYSTEM", f"Webserver port changed from {old_port} to {new_port}. Restarting system..." if lang == 'en' else f"Port du serveur web modifié de {old_port} à {new_port}. Redémarrage du système...")
        def do_restart():
            time.sleep(1)
            cleanup_all_processes()
            subprocess.Popen([sys.executable] + sys.argv)
            os._exit(0)
        threading.Thread(target=do_restart, daemon=True).start()
        return jsonify({"status": "restarting", "new_port": new_port})
    
    add_log("SYSTEM", "Configuration saved." if lang == 'en' else "Configuration sauvegardée.")
    # Configuration apply in the background
    threading.Thread(target=apply_dynamic_config, args=(old_config, new_config), daemon=True).start()
    return jsonify({"status": "success"})

def apply_dynamic_config(old_config, new_config):
    lang = new_config.get('settings', {}).get('language', 'en')
    old_streams = {s['id']: s for s in old_config.get('streams', [])}
    new_streams = {s['id']: s for s in new_config.get('streams', [])}
    
    old_servers_dict = {s['id']: s for s in old_config.get('servers', [])}
    new_servers_dict = {s['id']: s for s in new_config.get('servers', [])}
    new_servers_list = new_config.get('servers', [])
    
    # 1. Function to update / delete the existing streams
    for sid, engine in list(streams_engines.items()):
        if sid not in new_streams:
            if engine.running:
                engine.stop()
                add_log("SYSTEM", f"Stream \"{engine.config.get('name', sid)}\" stopped (deleted)." if lang == 'en' else f"Flux \"{engine.config.get('name', sid)}\" arrêté (supprimé).")
            else:
                engine.stop()
            del streams_engines[sid]
        else:
            stream_changed = (old_streams.get(sid) != new_streams[sid])
    
            targets_changed = False
            for target_id in new_streams[sid].get('targets', []):
                if old_servers_dict.get(target_id) != new_servers_dict.get(target_id):
                    targets_changed = True
                    break
                    
            needs_restart = stream_changed or targets_changed
            
            if needs_restart:
                was_running = engine.running
                engine.stop()
                # Utilisation de new_servers_list au lieu de new_servers
                new_engine = StreamManager(new_streams[sid], new_servers_list, new_config['settings'], log_callback=add_log)
                streams_engines[sid] = new_engine
                
                if was_running:
                    new_engine.start()
                    add_log("SYSTEM", f"Stream \"{new_streams[sid].get('name', sid)}\" updated and restarted." if lang == 'en' else f"Flux \"{new_streams[sid].get('name', sid)}\" mis à jour et redémarré.")
                else:
                    add_log("SYSTEM", f"Stream \"{new_streams[sid].get('name', sid)}\" updated." if lang == 'en' else f"Flux \"{new_streams[sid].get('name', sid)}\" mis à jour.")
            else:
                # Simple references update without restart
                engine.config = new_streams[sid]
                engine.servers = new_servers_list
                engine.settings = new_config['settings']
                
    # 2. New streams creation and startup
    for sid, s_conf in new_streams.items():
        if sid not in streams_engines:
            # Utilisation de new_servers_list
            new_engine = StreamManager(s_conf, new_servers_list, new_config['settings'], log_callback=add_log)
            streams_engines[sid] = new_engine
            if s_conf.get('auto_start', False):
                new_engine.start()
                add_log("SYSTEM", f"Stream \"{s_conf.get('name', sid)}\" created and started." if lang == 'en' else f"Flux \"{s_conf.get('name', sid)}\" créé et démarré.")

@app.route('/api/sys/export')
def sys_export():
    try:
        # config.json file export
        return send_file(CONFIG_FILE, as_attachment=True, download_name='config.json')
    except Exception as e:
        add_log("ERROR", f"Configuration export failed: {str(e)}")
        return "Configuration export failed: File not found or inaccessible.", 404

# --- Route logs ---
@app.route('/api/logs')
def api_logs():
    page = int(request.args.get('page', 1))
    filter_type = request.args.get('filter', 'ALL')
    
    filtered = [l for l in reversed(INTERNAL_LOGS) if filter_type == 'ALL' or l['level'] == filter_type]
    total = len(filtered)
    per_page = 50
    total_pages = max(1, (total + per_page - 1) // per_page)
    
    if page > total_pages: page = total_pages
    if page < 1: page = 1
    
    start = (page - 1) * per_page
    end = start + per_page
    return jsonify({'logs': filtered[start:end], 'page': page, 'total_pages': total_pages})

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    INTERNAL_LOGS.clear()
    lang = load_config().get('settings', {}).get('language', 'en')
    add_log("SYSTEM", "Logs cleared by user." if lang == 'en' else "Journaux effacés par l'utilisateur.")
    return jsonify({'status': 'ok'})

@app.route('/api/logs/export')
def export_logs():
    from flask import Response
    lang = load_config().get('settings', {}).get('language', 'en')
    header = "Timestamp | Type | Event\n--------------------------\n" if lang == 'en' else "Horodatage | Type | Événement\n--------------------------\n"
    def generate():
        yield header
        for l in INTERNAL_LOGS: yield f"{l['timestamp']} | {l['level']} | {l['event']}\n"
    return Response(generate(), mimetype="text/plain", headers={"Content-Disposition": "attachment;filename=logs.txt"})

# --- System routes ---
@app.route('/api/sys/restart')
def sys_restart():
    lang = load_config().get('settings', {}).get('language', 'en')
    add_log("SYSTEM", "System restart requested." if lang == 'en' else "Redémarrage du système demandé.")
    def do_restart():
        time.sleep(1)
        cleanup_all_processes()
        subprocess.Popen([sys.executable] + sys.argv)
        os._exit(0)
    threading.Thread(target=do_restart, daemon=True).start()
    return get_restarting_page("The encoder is restarting..." if lang == 'en' else "L'encodeur redémarre...", lang=lang)

@app.route('/api/sys/reset')
def sys_reset():
    lang = load_config().get('settings', {}).get('language', 'en')
    if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
    add_log("SYSTEM", "Factory reset requested." if lang == 'en' else "Restauration des paramètres d'usine demandée.")
    def do_reset():
        time.sleep(1)
        cleanup_all_processes()
        subprocess.Popen([sys.executable] + sys.argv)
        os._exit(0)
    threading.Thread(target=do_reset, daemon=True).start()
    # Forcing automatic redirect to port 8090 after factory reset
    return get_restarting_page("Factory reset complete. The encoder is restarting..." if lang == 'en' else "Restauration d'usine terminée. L'encodeur redémarre...", target_port=8090, lang=lang)

@app.route('/api/sys/import', methods=['POST'])
def sys_import():
    lang = load_config().get('settings', {}).get('language', 'en')
    file = request.files.get('config_file')
    if file and file.filename.endswith('.json'):
        file.save(CONFIG_FILE)
        add_log("SYSTEM", "Configuration imported. Restarting backend..." if lang == 'en' else "Configuration importée. Redémarrage du backend...")
        
        # Checking webserver port in the imported configuration to automatically redirect the user after restart
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                new_port = json.load(f).get('settings', {}).get('web_port', 8090)
        except:
            new_port = 8090

        import sys
        import time
        def do_restart():
            time.sleep(1)
            cleanup_all_processes()
            subprocess.Popen([sys.executable] + sys.argv)
            os._exit(0)
        threading.Thread(target=do_restart, daemon=True).start()
        return jsonify({"status": "ok", "new_port": new_port})
    return jsonify({"status": "error", "message": "Invalid file format. JSON required."})

@app.route('/api/smtp/test', methods=['POST'])
def smtp_test():
    import smtplib, ssl
    from email.message import EmailMessage
    from email.utils import formatdate
    cfg_smtp = load_config()['settings'].get('smtp', {})
    if not cfg_smtp.get('server'): return jsonify({"status": "error", "message": "Unable to send a test email: The service is not configured.\n\nIf you have just made the configuration, make sure you have saved it before running a test."})
    
    recipients = [r for r in cfg_smtp.get('recipients', []) if r.strip()]
    if not recipients: return jsonify({"status": "error", "message": "No recipients configured."})
    
    try:
        msg = EmailMessage()
        msg.set_content("This is a test email from WestBroadcast Encoder.\n\nThis confirms that the SMTP configuration has been set up correctly.\nYou can now receive email alerts based on the criteria you have set in the interface.")
        msg['Subject'] = "WestBroadcast Encoder - Test Email"
        msg['From'] = cfg_smtp["sender"]
        msg['To'] = ", ".join(recipients)
        msg['Date'] = formatdate(localtime=True)
        
        context = ssl.create_default_context()
        if cfg_smtp.get("tls"):
            s = smtplib.SMTP_SSL(cfg_smtp["server"], int(cfg_smtp["port"]), context=context, timeout=10)
        else:
            s = smtplib.SMTP(cfg_smtp["server"], int(cfg_smtp["port"]), timeout=10)
            s.ehlo()
            s.starttls(context=context)
            s.ehlo()
            
        s.login(cfg_smtp["user"], cfg_smtp["pass"])
        s.send_message(msg)
        s.quit()
        lang = load_config().get('settings', {}).get('language', 'en')
        add_log("SYSTEM", "SMTP Test email sent successfully." if lang == 'en' else "Email de test SMTP envoyé avec succès.")
        return jsonify({"status": "ok", "message": "Test OK. Email sent." if lang == 'en' else "Test OK. Mail envoyé."})
    except Exception as e:
        lang = load_config().get('settings', {}).get('language', 'en')
        add_log("ERROR", f"SMTP Test failed: {str(e)}" if lang == 'en' else f"Échec du test SMTP : {str(e)}")
        return jsonify({"status": "error", "message": f"SMTP Error: {str(e)}"})

@app.route('/api/fdk/download', methods=['POST'])
def download_fdk():
    lang = load_config().get('settings', {}).get('language', 'en')
    try:
        import urllib.request
        # Link for the automatic download of Libfdk-AAC
        url = "https://master.dl.sourceforge.net/project/butt/butt%20OLD/butt-0.1.37/AAC/libfdk-aac-2.dll?viasf=1"
        dest = os.path.join(BASE_DIR, "libfdk-aac.dll")
        
        # Using a User-Agent argument for the automatic download request
        opener = urllib.request.build_opener()
        opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')]
        urllib.request.install_opener(opener)
        
        urllib.request.urlretrieve(url, dest)
        add_log("SYSTEM", "libfdk-aac.dll was downloaded and installed successfully." if lang == 'en' else "libfdk-aac.dll a été téléchargé et installé avec succès.")
        return jsonify({"status": "ok"})
    except Exception as e:
        add_log("ERROR", f"Failed to download libfdk-aac.dll: {str(e)}" if lang == 'en' else f"Échec du téléchargement de libfdk-aac.dll : {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def init_engines():
    config = load_config()
    lang = config.get('settings', {}).get('language', 'en')
    for engine in streams_engines.values(): engine.stop()
    streams_engines.clear()
    for st in config['streams']:
        engine = StreamManager(st, config['servers'], config['settings'], log_callback=add_log)
        streams_engines[st['id']] = engine
        if st.get('auto_start', False):
            add_log("SYSTEM", f"Stream \"{st.get('name', st['id'])}\" started automatically." if lang == 'en' else f"Flux \"{st.get('name', st['id'])}\" démarré automatiquement.")
            engine.start()

# Memory from the last valid level to "compensate" for the technical jitter
last_valid_vu = {}
last_update_ts = {}

@app.route('/api/metadata/<custom_id>', methods=['GET', 'POST'])
def update_metadata_post(custom_id):
    provided_key = request.values.get('key')
    artist = request.values.get('artist')
    title_val = request.values.get('title')
    
    if artist and title_val:
        final_title = f"{artist.strip()} - {title_val.strip()}"
    elif title_val:
        final_title = title_val.strip()
    else:
        final_title = request.get_data(as_text=True)
    
    if not final_title or str(final_title).strip() == "":
        return jsonify({"status": "error", "message": "Empty content"}), 400
        
    found_id = False
    for engine in streams_engines.values():
        if engine.config.get("meta_source") == "post" and str(engine.config.get("meta_custom_id")).lower() == str(custom_id).lower():
            found_id = True
            # Checking the security key
            required_key = engine.config.get("meta_post_key", "")
            if required_key and str(provided_key) != str(required_key):
                return jsonify({"status": "error", "message": "Invalid Key"}), 401
            
            engine.post_title = str(final_title).strip()
            
    if found_id:
        return jsonify({"status": "ok"})
    
    return jsonify({"status": "error", "message": "Unknown ID"}), 404

def broadcast_vu_meters():
    while True:
        status_update = []
        for stream_id, engine in list(streams_engines.items()):
            state = engine.get_status()
            
            state['vu'] = {
                'l': float(getattr(engine, 'peak_l', -60.0)),
                'r': float(getattr(engine, 'peak_r', -60.0))
            }

            engine.peak_l = -60.0
            engine.peak_r = -60.0
            
            status_update.append(state)
            
        socketio.emit('status_all_update', status_update)
        time.sleep(0.1)

def run_flask(): 
    threading.Thread(target=broadcast_vu_meters, daemon=True).start()
    port = int(load_config()['settings'].get('web_port', 8090))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

def open_browser(): 
    port = load_config()['settings'].get('web_port', 8090)
    webbrowser.open(f"http://127.0.0.1:{port}")

def cleanup_all_processes():
    # Stop call for the streams engines
    for engine in streams_engines.values():
        engine.stop()
        sdp_file = f"stream_{engine.config['id']}.sdp"
        if os.path.exists(sdp_file):
            try: os.remove(sdp_file)
            except: pass

import atexit
atexit.register(cleanup_all_processes)

def run_gui():
    cleanup_all_processes()

    config = load_config()
    lang = config.get('settings', {}).get('language', 'en')
    add_log("SYSTEM", "Backend started." if lang == 'en' else "Backend démarré.")
    port = config['settings'].get('web_port', 8090)
    
    root = tk.Tk()
    root.title("WestBroadcast Encoder")
    root.geometry("450x230")
    root.configure(bg="#eef2f5")
    root.eval('tk::PlaceWindow . center')
    
    def on_closing():
        current_lang = load_config().get('settings', {}).get('language', 'en')
        title = "Confirmation Request" if current_lang == 'en' else "Demande de confirmation"
        msg = "Are you sure you want to stop WestBroadcast Encoder?\n\nWARNING: Closing this window will cause all encoders to stop." if current_lang == 'en' else "Êtes-vous sûr de vouloir arrêter WestBroadcast Encoder ?\n\nATTENTION : La fermeture de cette fenêtre occasionnera l'interruption de tous les encodeurs."
        if messagebox.askyesno(title, msg):
            cleanup_all_processes()
            root.destroy()
            os._exit(0)
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    ip = get_local_ip()
    
    lbl1 = f"WEBSERVER IS RUNNING ON PORT {port}" if lang == 'en' else f"SERVEUR WEB ACTIF SUR LE PORT {port}"
    lbl2 = "PLEASE KEEP THIS WINDOW OPEN FOR THE STREAMS ENCODING!" if lang == 'en' else "PENSEZ À GARDER CETTE FENÊTRE OUVERTE POUR L'ENCODAGE DES FLUX !"
    btn_txt = "CLICK HERE TO OPEN THE WEBSERVER INTERFACE\n(Default password: admin)" if lang == 'en' else "CLIQUEZ ICI POUR ACCÉDER À L'INTERFACE WEB\n(Mot de passe par défaut : admin)"
    txt_ip = f"IP: {ip}" if lang == 'en' else f"IP : {ip}"
    
    tk.Label(root, text=lbl1, fg="#198754", bg="#eef2f5", font=("Segoe UI", 13, "bold")).pack(pady=(20, 5))
    tk.Label(root, text=lbl2, fg="#dc3545", bg="#eef2f5", font=("Segoe UI", 9)).pack(pady=(0, 10))
    tk.Label(root, text=txt_ip, fg="#555", bg="#eef2f5", font=("Segoe UI", 11)).pack(pady=(0, 15))
    
    btn = tk.Button(root, text=btn_txt, bg="#3c8dbc", fg="white", activebackground="#337ab7", activeforeground="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, cursor="hand2", command=open_browser)
    btn.pack(fill=tk.X, padx=40, pady=(0, 15), ipadx=10, ipady=6)
    
    lbl_counter = tk.Label(root, text="", fg="#333", bg="#eef2f5", font=("Segoe UI", 10, "bold"))
    lbl_counter.pack(pady=(0, 10))
    
    def update_counter():
        total = len(streams_engines)
        active = sum(1 for engine in streams_engines.values() if engine.running)
        if lang == 'fr':
            lbl_counter.config(text=f"Encodeurs actifs : {active}/{total}")
        else:
            lbl_counter.config(text=f"Active encoders: {active}/{total}")
        root.after(1000, update_counter)
        
    update_counter()
    
    threading.Thread(target=run_flask, daemon=True).start()
    init_engines()
    root.mainloop()

if __name__ == '__main__':
    run_gui()