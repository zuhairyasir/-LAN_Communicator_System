import socket
import threading
import json
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox, simpledialog
import base64
import os
from datetime import datetime
import cv2
import pyaudio
from PIL import Image, ImageTk
import io
import queue
import time

VIDEO_WIDTH = 320
VIDEO_HEIGHT = 240
VIDEO_QUALITY = 30 
VIDEO_FPS_DELAY = 0.05  
AUDIO_RATE = 44100
AUDIO_CHANNELS = 1
AUDIO_FORMAT = pyaudio.paInt16
AUDIO_CHUNK = 1024  

class ChatClient:
    def __init__(self, root):
        self.root = root
        self.root.title("LAN Communicator")
        self.root.geometry("1000x640")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.sock = None
        self.username = None
        self.is_connected = False

        self.current_room = 'General'
        self.active_private_target = None
        self.interface_loaded = False
        self.pending_payloads = []

        self.group_history = {}
        self.private_history = {}

        self.in_call = False
        self.call_peer = None
        self.call_mode = None  
        self.pending_call_mode = None

        self.video_capture = None
        self.video_tx_thread = None
        self.video_rx_thread = None
        self.video_rx_queue = queue.Queue(maxsize=8)

        self.pa_instance = None
        self.audio_in_stream = None
        self.audio_out_stream = None
        self.audio_tx_thread = None
        self.audio_rx_queue = queue.Queue(maxsize=50)

        self.media_halt_event = threading.Event()

        self.download_dir = os.path.join(os.path.expanduser('~'), 'ChatDownloads')
        os.makedirs(self.download_dir, exist_ok=True)

        self.render_login_screen()

    def render_login_screen(self):
        self.login_frame = tk.Frame(self.root, bg='#1e1e2e')
        self.login_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(self.login_frame, text="LAN Communicator", font=('Arial', 28, 'bold'), bg='#1e1e2e', fg='white').pack(pady=40)

        tk.Label(self.login_frame, text="Server Host:", bg='#1e1e2e', fg='white', font=('Arial', 12)).pack(pady=4)
        self.host_entry = tk.Entry(self.login_frame, font=('Arial', 12), width=30)
        self.host_entry.insert(0, '127.0.0.1')
        self.host_entry.pack(pady=4)

        tk.Label(self.login_frame, text="Server Port:", bg='#1e1e2e', fg='white', font=('Arial', 12)).pack(pady=4)
        self.port_entry = tk.Entry(self.login_frame, font=('Arial', 12), width=30)
        self.port_entry.insert(0, '5555')
        self.port_entry.pack(pady=4)

        tk.Label(self.login_frame, text="Username:", bg='#1e1e2e', fg='white', font=('Arial', 12)).pack(pady=4)
        self.username_entry = tk.Entry(self.login_frame, font=('Arial', 12), width=30)
        self.username_entry.pack(pady=4)
        self.username_entry.bind('<Return>', lambda e: self.establish_connection())

        self.connect_btn = tk.Button(self.login_frame, text="Connect", font=('Arial', 14, 'bold'), bg='#89b4fa', fg='white', width=18, command=self.establish_connection)
        self.connect_btn.pack(pady=18)

        self.status_label = tk.Label(self.login_frame, text="", bg='#1e1e2e', fg='#ffdddd', font=('Arial', 10))
        self.status_label.pack(pady=6)

    def render_main_interface(self):
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_pane = tk.Frame(main_frame, width=240, bg='#1e1e2e')
        left_pane.pack(side=tk.LEFT, fill=tk.Y)
        left_pane.pack_propagate(False)

        tk.Label(left_pane, text=f"👤 {self.username}", bg='#1e1e2e', fg='white', font=('Arial', 12, 'bold')).pack(pady=12)

        tk.Label(left_pane, text="Active Nodes", bg='#1e1e2e', fg='white', font=('Arial', 11, 'bold')).pack(pady=6)
        self.node_listbox = tk.Listbox(left_pane, bg='#34495e', fg='white', selectbackground='#1abc9c', font=('Arial', 11))
        self.node_listbox.pack(fill=tk.BOTH, expand=True, padx=8)
        self.node_listbox.bind('<Double-Button-1>', self.initiate_private_session)

        tk.Button(left_pane, text="💬 Direct Message", command=self.initiate_private_session, bg='#1abc9c', fg='white', font=('Arial', 10)).pack(pady=6)

        call_controls = tk.Frame(left_pane, bg='#1e1e2e')
        call_controls.pack(pady=6)
        tk.Button(call_controls, text="📞 Voice", command=lambda: self.request_call('voice'), bg='#27ae60', fg='white', font=('Arial', 9), width=10).pack(side=tk.LEFT, padx=2)
        tk.Button(call_controls, text="📹 Video", command=lambda: self.request_call('video'), bg='#2980b9', fg='white', font=('Arial', 9), width=10).pack(side=tk.LEFT, padx=2)
        tk.Button(call_controls, text="Hang Up", command=self.drop_call, bg='#c0392b', fg='white', font=('Arial', 9), width=10).pack(side=tk.LEFT, padx=2)

        tk.Label(left_pane, text="Channels", bg='#1e1e2e', fg='white', font=('Arial', 11, 'bold')).pack(pady=6)
        self.channel_listbox = tk.Listbox(left_pane, bg='#11111b', fg='white', selectbackground='#1abc9c', font=('Arial', 11), height=6)
        self.channel_listbox.pack(fill=tk.X, padx=8, pady=(0,8))
        self.channel_listbox.insert(tk.END, "General")
        self.channel_listbox.bind('<<ListboxSelect>>', self.change_channel)

        channel_btns = tk.Frame(left_pane, bg='#1e1e2e')
        channel_btns.pack(pady=6)
        tk.Button(channel_btns, text="➕ Create", command=self.create_channel, bg='#16a085', fg='white', width=10).pack(side=tk.LEFT, padx=4)
        tk.Button(channel_btns, text="🚪 Join", command=self.join_channel, bg='#2980b9', fg='white', width=10).pack(side=tk.LEFT, padx=4)

        right_pane = tk.Frame(main_frame, bg='#1e1e2e')
        right_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.header_label = tk.Label(right_pane, text=f"Channel: {self.current_room}", bg='#11111b', fg='white', font=('Arial', 13, 'bold'), pady=10)
        self.header_label.pack(fill=tk.X)

        self.chat_area = scrolledtext.ScrolledText(right_pane, wrap=tk.WORD, font=('Arial', 11), state=tk.DISABLED, bg='white')
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        input_container = tk.Frame(right_pane, bg='white')
        input_container.pack(fill=tk.X, padx=8, pady=8)
        
        self.input_field = tk.Text(input_container, height=3, font=('Arial', 11))
        self.input_field.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.input_field.bind('<Return>', self.dispatch_message)
        self.input_field.bind('<Shift-Return>', lambda e: None)

        action_btns = tk.Frame(input_container, bg='white')
        action_btns.pack(side=tk.LEFT, padx=6)
        tk.Button(action_btns, text="📤 Send", command=self.dispatch_message, bg='#27ae60', fg='white', width=10).pack(pady=4)
        tk.Button(action_btns, text="📎 Attach", command=self.upload_file, bg='#2980b9', fg='white', width=10).pack(pady=4)

        self.interface_loaded = True
        self.root.after(100, self.flush_pending_payloads)

    def establish_connection(self):
        host = self.host_entry.get().strip()
        port = self.port_entry.get().strip()
        username = self.username_entry.get().strip()
        
        if not username:
            self.status_label.config(text="Username is required.")
            return
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((host, int(port)))
            self.sock.send(username.encode('utf-8'))
            
            self.username = username
            self.is_connected = True
            self.login_frame.destroy()
            self.render_main_interface()
            
            threading.Thread(target=self.listen_for_traffic, daemon=True).start()
        except Exception as e:
            self.status_label.config(text=f"Connection failed: {e}")

    def transmit_payload(self, payload):
        try:
            serialized = json.dumps(payload) + "\n"
            self.sock.send(serialized.encode('utf-8'))
        except Exception as e:
            print(f"Transmission failed: {e}")

    def listen_for_traffic(self):
        buffer = ""
        decoder = json.JSONDecoder()
        try:
            while self.is_connected:
                data = self.sock.recv(1024 * 1024 * 4)
                if not data:
                    break
                    
                buffer += data.decode('utf-8', errors='ignore')
                
                # Extract concatenated JSON objects from the TCP stream
                while buffer:
                    buffer = buffer.lstrip()
                    try:
                        obj, idx = decoder.raw_decode(buffer)
                        buffer = buffer[idx:]
                        self.handle_incoming_payload(obj)
                    except ValueError:
                        break
        except Exception as e:
            print(f"Connection dropped: {e}")
        finally:
            self.is_connected = False

    def handle_incoming_payload(self, payload):
        if not self.interface_loaded:
            self.pending_payloads.append(payload)
            return

        msg_type = payload.get('type')
        ts = payload.get('timestamp') or datetime.now().strftime('%H:%M:%S')

        if msg_type == 'welcome':
            self.log_system_event(payload.get('message'))
            for room in payload.get('rooms', []):
                if room not in self.channel_listbox.get(0, tk.END):
                    self.channel_listbox.insert(tk.END, room)
                    
        elif msg_type == 'chat':
            room = payload.get('room')
            sender = payload.get('sender')
            msg = payload.get('message')
            
            self.group_history.setdefault(room, []).append((ts, sender, msg))
            if room == self.current_room and not self.active_private_target:
                self.append_to_chat(sender, msg, ts)
                
        elif msg_type == 'private':
            sender = payload.get('sender')
            msg = payload.get('message')
            
            self.private_history.setdefault(sender, []).append((ts, sender, msg))
            if self.active_private_target == sender:
                self.append_private_chat(sender, msg, ts)
            else:
                self.log_system_event(f"🔒 Incoming direct message from {sender}")
                
        elif msg_type == 'file':
            self.process_incoming_file(
                payload.get('sender'), 
                payload.get('filename'), 
                payload.get('filedata')
            )
            
        elif msg_type == 'user_joined':
            self.log_system_event(f"{payload.get('username')} joined the network.")
            
        elif msg_type == 'user_left':
            self.log_system_event(f"{payload.get('username')} left the network.")
            
        elif msg_type == 'client_list':
            self.refresh_node_list(payload.get('clients', []))
            
        elif msg_type == 'room_created':
            room = payload.get('room_name')
            if room not in self.channel_listbox.get(0, tk.END):
                self.channel_listbox.insert(tk.END, room)
            self.log_system_event(f"Channel '{room}' instantiated.")
            
        elif msg_type == 'call_request':
            self.evaluate_incoming_call(payload.get('caller'), payload.get('call_type'))
            
        elif msg_type == 'call_response':
            self.finalize_call_handshake(payload.get('responder'), payload.get('accepted'), payload.get('call_type', 'video'))
            
        elif msg_type == 'call_data':
            self.route_media_stream(payload.get('data_type'), payload.get('data'))
            
        elif msg_type == 'call_ended':
            self.log_system_event(f"Session with {payload.get('peer')} terminated.")
            self.terminate_media_streams()

    def flush_pending_payloads(self):
        while self.pending_payloads:
            self.handle_incoming_payload(self.pending_payloads.pop(0))

    def append_to_chat(self, sender, message, timestamp):
        if not self.interface_loaded: return
        def update_ui():
            self.chat_area.config(state=tk.NORMAL)
            self.chat_area.insert(tk.END, f"[{timestamp}] ", 'time')
            self.chat_area.insert(tk.END, f"{sender}: ", 'sender')
            self.chat_area.insert(tk.END, f"{message}\n")
            self.chat_area.config(state=tk.DISABLED)
            self.chat_area.see(tk.END)
        self.root.after(0, update_ui)

    def append_private_chat(self, sender, message, timestamp):
        if not self.interface_loaded: return
        def update_ui():
            self.chat_area.config(state=tk.NORMAL)
            self.chat_area.insert(tk.END, f"[{timestamp}] ", 'time')
            self.chat_area.insert(tk.END, f"🔒 {sender}: ", 'private')
            self.chat_area.insert(tk.END, f"{message}\n")
            self.chat_area.config(state=tk.DISABLED)
            self.chat_area.see(tk.END)
        self.root.after(0, update_ui)

    def log_system_event(self, message):
        if not self.interface_loaded: return
        def update_ui():
            self.chat_area.config(state=tk.NORMAL)
            self.chat_area.insert(tk.END, f"[SYSTEM] {message}\n", 'system')
            self.chat_area.config(state=tk.DISABLED)
            self.chat_area.see(tk.END)
        self.root.after(0, update_ui)

    def dispatch_message(self, event=None):
        message = self.input_field.get('1.0', tk.END).strip()
        if not message:
            return 'break' if event else None
            
        if event and event.state & 0x1:
            return
            
        ts = datetime.now().strftime('%H:%M:%S')
        try:
            if self.active_private_target:
                self.transmit_payload({'type': 'private', 'recipient': self.active_private_target, 'message': message})
                self.private_history.setdefault(self.active_private_target, []).append((ts, self.username, message))
                self.append_private_chat(self.username, message, ts)
            else:
                self.transmit_payload({'type': 'chat', 'room': self.current_room, 'message': message})
                self.group_history.setdefault(self.current_room, []).append((ts, self.username, message))
                self.append_to_chat(self.username, message, ts)
                
            self.input_field.delete('1.0', tk.END)
        except Exception as e:
            messagebox.showerror("Transmission Error", str(e))
            
        return 'break' if event else None

    def upload_file(self):
        filepath = filedialog.askopenfilename(title="Select File")
        if not filepath: return
        
        try:
            if os.path.getsize(filepath) > 20 * 1024 * 1024:
                messagebox.showerror("Constraint Violation", "File exceeds 20MB limit.")
                return
                
            with open(filepath, 'rb') as f:
                encoded_data = base64.b64encode(f.read()).decode('utf-8')
                
            filename = os.path.basename(filepath)
            payload = {
                'type': 'file',
                'filename': filename,
                'filedata': encoded_data,
                'filetype': os.path.splitext(filename)[1].lower()
            }
            
            if self.active_private_target:
                payload['recipient'] = self.active_private_target
            else:
                payload['room'] = self.current_room
                
            self.transmit_payload(payload)
            self.log_system_event(f"Transmitted '{filename}'.")
        except Exception as e:
            messagebox.showerror("Upload Failed", str(e))

    def process_incoming_file(self, sender, filename, filedata):
        try:
            raw_bytes = base64.b64decode(filedata)
            save_path = os.path.join(self.download_dir, filename)
            counter = 1
            
            while os.path.exists(save_path):
                name, ext = os.path.splitext(filename)
                save_path = os.path.join(self.download_dir, f"{name}_{counter}{ext}")
                counter += 1
                
            with open(save_path, 'wb') as f:
                f.write(raw_bytes)
                
            self.log_system_event(f"File received: {filename} from {sender} -> {save_path}")
        except Exception as e:
            self.log_system_event(f"Failed to process incoming file: {e}")

    def refresh_node_list(self, active_users):
        if not self.interface_loaded: return
        def update_ui():
            self.node_listbox.delete(0, tk.END)
            for user in active_users:
                if user != self.username:
                    self.node_listbox.insert(tk.END, user)
        self.root.after(0, update_ui)

    def initiate_private_session(self, event=None):
        if event:
            try:
                selection = self.node_listbox.curselection()
                if not selection: return
                target_user = self.node_listbox.get(selection[0])
            except Exception:
                return
        else:
            target_user = simpledialog.askstring("Direct Message", "Enter target username:")
            if not target_user: return
            
        self.active_private_target = target_user
        self.header_label.config(text=f"Direct Message: {target_user}", bg='#8e44ad')
        
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.delete('1.0', tk.END)
        
        history = self.private_history.get(target_user, [])
        for ts, sender, msg in history:
            prefix = "You" if sender == self.username else sender
            self.chat_area.insert(tk.END, f"[{ts}] ", 'time')
            self.chat_area.insert(tk.END, f"🔒 {prefix}: ", 'private')
            self.chat_area.insert(tk.END, f"{msg}\n")
            
        self.chat_area.config(state=tk.DISABLED)
        self.chat_area.see(tk.END)
        self.log_system_event(f"Private channel established with {target_user}")

    def change_channel(self, event):
        selection = self.channel_listbox.curselection()
        if not selection: return
        
        target_room = self.channel_listbox.get(selection[0])
        self.current_room = target_room
        self.active_private_target = None
        self.header_label.config(text=f"Channel: {target_room}", bg='#2980b9')
        
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.delete('1.0', tk.END)
        
        history = self.group_history.get(target_room, [])
        for ts, sender, msg in history:
            self.chat_area.insert(tk.END, f"[{ts}] ", 'time')
            self.chat_area.insert(tk.END, f"{sender}: ", 'sender')
            self.chat_area.insert(tk.END, f"{msg}\n")
            
        self.chat_area.config(state=tk.DISABLED)
        self.chat_area.see(tk.END)
        self.log_system_event(f"Active channel: {target_room}")

    def create_channel(self):
        name = simpledialog.askstring("New Channel", "Enter channel designation:")
        if name:
            self.transmit_payload({'type': 'create_room', 'room_name': name})

    def join_channel(self):
        selection = self.channel_listbox.curselection()
        if not selection: return
        
        target = self.channel_listbox.get(selection[0])
        self.transmit_payload({'type': 'join_room', 'room_name': target})
        self.current_room = target
        self.header_label.config(text=f"Channel: {target}")
        self.log_system_event(f"Subscribed to: {target}")

    def request_call(self, mode):
        selection = self.node_listbox.curselection()
        if not selection:
            messagebox.showinfo("Action Required", "Select a target node first.")
            return
            
        recipient = self.node_listbox.get(selection[0])
        self.transmit_payload({'type': 'call_request', 'recipient': recipient, 'call_type': mode})
        self.log_system_event(f"Dialing {recipient}... ({mode})")
        self.pending_call_mode = mode

    def evaluate_incoming_call(self, caller, mode):
        accepted = messagebox.askyesno("Incoming Transmission", f"{caller} is attempting a {mode} connection. Accept?")
        self.transmit_payload({'type': 'call_response', 'caller': caller, 'accepted': accepted, 'call_type': mode})
        
        if accepted:
            self.call_peer = caller
            self.call_mode = mode
            self.root.after(200, lambda: self.initialize_media_streams(caller, mode))

    def finalize_call_handshake(self, responder, accepted, mode):
        if accepted:
            self.log_system_event(f"{responder} accepted.")
            self.call_peer = responder
            self.call_mode = mode
            self.initialize_media_streams(responder, mode)
        else:
            self.log_system_event(f"{responder} declined.")

    def drop_call(self):
        if not self.in_call: return
        self.transmit_payload({'type': 'end_call'})
        self.terminate_media_streams()
        self.log_system_event("Session terminated.")

    def initialize_media_streams(self, peer, mode):
        if self.in_call: return
        
        self.in_call = True
        self.call_peer = peer
        self.call_mode = mode
        self.media_halt_event.clear()

        if mode in ('voice', 'video', 'both'):
            try:
                self.pa_instance = pyaudio.PyAudio()
                
                try:
                    self.audio_in_stream = self.pa_instance.open(format=AUDIO_FORMAT, channels=AUDIO_CHANNELS, rate=AUDIO_RATE, input=True, frames_per_buffer=AUDIO_CHUNK)
                except Exception:
                    self.audio_in_stream = None

                try:
                    self.audio_out_stream = self.pa_instance.open(format=AUDIO_FORMAT, channels=AUDIO_CHANNELS, rate=AUDIO_RATE, output=True, frames_per_buffer=AUDIO_CHUNK)
                except Exception:
                    self.audio_out_stream = None

                if self.audio_in_stream:
                    threading.Thread(target=self.transmit_audio_loop, daemon=True).start()
                if self.audio_out_stream:
                    threading.Thread(target=self.playback_audio_loop, daemon=True).start()
                    
            except Exception as e:
                print(f"Audio interface failure: {e}")

        if mode in ('video', 'both'):
            try:
                self.video_capture = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                self.video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, VIDEO_WIDTH)
                self.video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, VIDEO_HEIGHT)
                
                if self.video_capture.isOpened():
                    threading.Thread(target=self.transmit_video_loop, daemon=True).start()
                    threading.Thread(target=self.render_video_loop, daemon=True).start()
            except Exception as e:
                print(f"Video interface failure: {e}")

        self.spawn_media_window()

    def route_media_stream(self, data_type, encoded_data):
        try:
            raw_bytes = base64.b64decode(encoded_data)
            if data_type == 'video':
                try:
                    self.video_rx_queue.put_nowait(raw_bytes)
                except queue.Full: pass
            elif data_type == 'audio':
                try:
                    self.audio_rx_queue.put_nowait(raw_bytes)
                except queue.Full: pass
        except Exception:
            pass

    def terminate_media_streams(self):
        self.media_halt_event.set()
        self.in_call = False
        self.call_peer = None
        self.call_mode = None

        if self.video_capture:
            self.video_capture.release()

        try:
            if self.audio_in_stream: self.audio_in_stream.close()
            if self.audio_out_stream: self.audio_out_stream.close()
            if self.pa_instance: self.pa_instance.terminate()
        except Exception: pass

        with self.video_rx_queue.mutex: self.video_rx_queue.queue.clear()
        with self.audio_rx_queue.mutex: self.audio_rx_queue.queue.clear()

        try:
            if hasattr(self, 'media_window') and self.media_window and self.media_window.winfo_exists():
                self.media_window.destroy()
        except Exception: pass

    def transmit_video_loop(self):
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_QUALITY]
        while not self.media_halt_event.is_set() and self.video_capture and self.video_capture.isOpened():
            ret, frame = self.video_capture.read()
            if not ret:
                time.sleep(0.02)
                continue
                
            frame = cv2.resize(frame, (VIDEO_WIDTH, VIDEO_HEIGHT))
            ok, encoded = cv2.imencode('.jpg', frame, encode_params)
            if ok:
                b64 = base64.b64encode(encoded.tobytes()).decode('utf-8')
                self.transmit_payload({'type': 'call_data', 'peer': self.call_peer, 'data': b64, 'data_type': 'video', 'sender': self.username})
            time.sleep(VIDEO_FPS_DELAY)

    def transmit_audio_loop(self):
        while not self.media_halt_event.is_set() and self.audio_in_stream:
            try:
                data = self.audio_in_stream.read(AUDIO_CHUNK, exception_on_overflow=False)
                if data:
                    b64 = base64.b64encode(data).decode('utf-8')
                    self.transmit_payload({'type': 'call_data', 'peer': self.call_peer, 'data': b64, 'data_type': 'audio', 'sender': self.username})
            except Exception:
                break

    def playback_audio_loop(self):
        while not self.media_halt_event.is_set():
            try:
                raw_bytes = self.audio_rx_queue.get(timeout=0.5)
                if self.audio_out_stream:
                    self.audio_out_stream.write(raw_bytes, exception_on_underflow=False)
            except queue.Empty:
                continue
            except Exception:
                pass

    def render_video_loop(self):
        while not self.media_halt_event.is_set():
            try:
                raw_bytes = self.video_rx_queue.get(timeout=0.5)
                image = Image.open(io.BytesIO(raw_bytes))
                tk_image = ImageTk.PhotoImage(image)
                
                def update_canvas():
                    try:
                        if self.in_call and hasattr(self, 'video_canvas') and self.video_canvas.winfo_exists():
                            self.video_canvas.configure(image=tk_image)
                            self.video_canvas.image = tk_image
                    except Exception: pass
                    
                self.root.after(0, update_canvas)
            except queue.Empty:
                continue
            except Exception:
                pass

    def spawn_media_window(self):
        try:
            self.media_window = tk.Toplevel(self.root)
            self.media_window.title(f"Active Session: {self.call_peer}")
            
            if self.call_mode in ('video', 'both'):
                self.media_window.geometry("420x340")
                self.video_canvas = tk.Label(self.media_window, bg='black')
                self.video_canvas.pack(fill=tk.BOTH, expand=True)
            else:
                self.media_window.geometry("300x120")
                self.video_canvas = None

            tk.Label(self.media_window, text=f"Connected to {self.call_peer}", font=('Arial', 10)).pack()
            self.media_window.protocol("WM_DELETE_WINDOW", self.drop_call)
        except Exception as e:
            print(f"Failed to spawn media view: {e}")

    def on_closing(self):
        if self.in_call: self.drop_call()
        if self.is_connected:
            try: self.sock.close()
            except Exception: pass
        self.root.destroy()

if __name__ == '__main__':
    app_root = tk.Tk()
    app = ChatClient(app_root)
    app_root.mainloop()