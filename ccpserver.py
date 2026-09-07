import socket
import threading
import json
from datetime import datetime

class RelayServer:
    def __init__(self, host='0.0.0.0', port=5555):
        self.host = host
        self.port = port
        
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.active_clients = {}         
        self.client_lock = threading.Lock()

        self.channels = {'General': []}  
        self.channel_lock = threading.Lock()

        self.active_media_sessions = {}    

    def start(self):
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen()
        print(f"[CORE] Relay Server bound to {self.host}:{self.port}")
        
        try:
            while True:
                client_sock, addr = self.server_sock.accept()
                threading.Thread(target=self.manage_client_session, args=(client_sock, addr), daemon=True).start()
        except KeyboardInterrupt:
            print("\n[CORE] Graceful shutdown initiated.")
        finally:
            self.server_sock.close()

    def push_payload(self, target_sock, payload):
        try:
            serialized = json.dumps(payload) + "\n"
            target_sock.send(serialized.encode('utf-8'))
        except Exception as e:
            print(f"[WARN] Delivery failure: {e}")

    def direct_message(self, username, payload):
        with self.client_lock:
            sock = self.active_clients.get(username)
            if sock:
                self.push_payload(sock, payload)

    def broadcast(self, payload, exclude=None):
        with self.client_lock:
            for uname, sock in list(self.active_clients.items()):
                if uname != exclude:
                    self.push_payload(sock, payload)

    def channel_broadcast(self, channel, payload, exclude=None):
        with self.channel_lock:
            subscribers = list(self.channels.get(channel, []))
            
        for uname in subscribers:
            if uname != exclude:
                self.direct_message(uname, payload)

    def sync_active_users(self):
        with self.client_lock:
            client_roster = list(self.active_clients.keys())
        self.broadcast({'type': 'client_list', 'clients': client_roster})

    def manage_client_session(self, client_sock, addr):
        username = None
        try:
            init_data = client_sock.recv(4096)
            if not init_data:
                client_sock.close()
                return
                
            username = init_data.decode('utf-8').strip()
            if not username:
                client_sock.close()
                return

            with self.client_lock:
                if username in self.active_clients:
                    self.push_payload(client_sock, {'type': 'error', 'message': 'Username conflict'})
                    client_sock.close()
                    return
                self.active_clients[username] = client_sock

            with self.channel_lock:
                if 'General' not in self.channels:
                    self.channels['General'] = []
                if username not in self.channels['General']:
                    self.channels['General'].append(username)

            print(f"[AUTH] {username} authenticated from {addr}")

            self.push_payload(client_sock, {
                'type': 'welcome',
                'message': f'Connection established, {username}.',
                'rooms': list(self.channels.keys())
            })

            self.broadcast({
                'type': 'user_joined',
                'username': username,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            }, exclude=username)
            
            self.sync_active_users()

            buffer = ""
            decoder = json.JSONDecoder()
            
            while True:
                chunk = client_sock.recv(1024 * 1024)
                if not chunk: break
                
                buffer += chunk.decode('utf-8', errors='ignore')
                while buffer:
                    buffer = buffer.lstrip()
                    try:
                        obj, idx = decoder.raw_decode(buffer)
                        buffer = buffer[idx:]
                        self.route_payload(username, obj)
                    except ValueError:
                        break

        except Exception as e:
            print(f"[ERROR] Session handler crashed for {username}: {e}")
        finally:
            self.terminate_session(username)

    def route_payload(self, sender, payload):
        payload_type = payload.get('type')
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        if payload_type == 'chat':
            room = payload.get('room', 'General')
            self.channel_broadcast(room, {
                'type': 'chat', 'sender': sender, 'message': payload.get('message'),
                'room': room, 'timestamp': timestamp
            }, exclude=sender)

        elif payload_type == 'private':
            self.direct_message(payload.get('recipient'), {
                'type': 'private', 'sender': sender, 'message': payload.get('message'),
                'timestamp': timestamp
            })

        elif payload_type == 'file':
            target = payload.get('recipient')
            forward_data = {
                'type': 'file', 'sender': sender, 'filename': payload.get('filename'),
                'filedata': payload.get('filedata'), 'filetype': payload.get('filetype'),
                'timestamp': timestamp
            }
            if target:
                self.direct_message(target, forward_data)
            else:
                self.channel_broadcast(payload.get('room', 'General'), forward_data, exclude=sender)

        elif payload_type == 'create_room':
            room_name = payload.get('room_name')
            with self.channel_lock:
                if room_name not in self.channels:
                    self.channels[room_name] = [sender]
            self.broadcast({'type': 'room_created', 'room_name': room_name, 'creator': sender})
            
        elif payload_type == 'join_room':
            room = payload.get('room_name')
            with self.channel_lock:
                if room in self.channels and sender not in self.channels[room]:
                    self.channels[room].append(sender)
            self.channel_broadcast(room, {'type': 'user_joined_room', 'username': sender, 'room': room})

        elif payload_type == 'call_request':
            self.direct_message(payload.get('recipient'), {
                'type': 'call_request', 'caller': sender, 'call_type': payload.get('call_type'),
                'timestamp': timestamp
            })

        elif payload_type == 'call_response':
            caller = payload.get('caller')
            accepted = payload.get('accepted')
            
            if accepted:
                self.active_media_sessions[sender] = caller
                self.active_media_sessions[caller] = sender
                
            self.direct_message(caller, {
                'type': 'call_response', 'responder': sender, 'accepted': accepted,
                'call_type': payload.get('call_type', 'both')
            })

        elif payload_type == 'call_data':
            self.direct_message(payload.get('peer'), {
                'type': 'call_data', 'sender': sender, 'data': payload.get('data'),
                'data_type': payload.get('data_type')
            })

        elif payload_type == 'end_call':
            if sender in self.active_media_sessions:
                peer = self.active_media_sessions.pop(sender, None)
                if peer and peer in self.active_media_sessions:
                    self.active_media_sessions.pop(peer, None)
                    self.direct_message(peer, {'type': 'call_ended', 'peer': sender})
            self.direct_message(sender, {'type': 'call_ended', 'peer': sender})

    def terminate_session(self, username):
        if not username: return
        
        with self.client_lock:
            sock = self.active_clients.pop(username, None)
            if sock:
                try: sock.close()
                except Exception: pass
                
        with self.channel_lock:
            for users in self.channels.values():
                if username in users:
                    users.remove(username)
                    
        if username in self.active_media_sessions:
            peer = self.active_media_sessions.pop(username, None)
            if peer and peer in self.active_media_sessions:
                self.active_media_sessions.pop(peer, None)
                self.direct_message(peer, {'type': 'call_ended', 'peer': username})

        print(f"[AUTH] {username} disconnected.")
        self.broadcast({'type': 'user_left', 'username': username, 'timestamp': datetime.now().strftime('%H:%M:%S')})
        self.sync_active_users()

if __name__ == '__main__':
    server_instance = RelayServer(host='0.0.0.0', port=5555)   
    server_instance.start()