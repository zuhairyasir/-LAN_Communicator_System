# LAN Communicator System

A centralized LAN chat and multimedia communication platform built in Python, combining real time group messaging, private messaging, file sharing, and audio/video calling in a single desktop client.

Built as a lab project for a Computer Networks course, with a deliberate focus on implementing a real client server relay architecture, a custom application layer protocol, and safe concurrent socket programming from the ground up, rather than relying on an existing chat framework.

---

## What it does

- **Group and private messaging** — a "General" channel plus custom channels users can create and join, alongside direct one-to-one messages
- **Live roster** — every client sees connected users update dynamically as they join or leave
- **File sharing** — attach and transmit binary files (images, logs, documents) up to 20MB, automatically saved on the receiving end
- **Real time audio and video calling** — negotiated calls with webcam and microphone streaming between two clients
- **System event broadcasting** — join/leave and disconnect events are surfaced to all connected clients
- **Multi client concurrency** — the server handles many simultaneous sessions without blocking the UI on any client

---

## Network Architecture & Protocol Design

| Aspect | Design Choice | Why |
|---|---|---|
| **Topology** | Centralized client-server (star), pure relay — clients never connect directly to each other | Simpler to reason about and secure than peer-to-peer; the server always knows who's online |
| **Transport** | TCP (`AF_INET`, `SOCK_STREAM`) for all traffic, including media | Reliable, ordered delivery is essential for chat and file integrity; the trade-off is TCP's head-of-line blocking, which causes stuttering in the real-time audio/video streams |
| **Application protocol** | Custom JSON messages, newline-delimited, UTF-8 encoded | A `type` key (`chat`, `private`, `file`, `call_request`, `call_data`, …) dictates how each payload is handled |
| **Binary data** | Base64-encoded before being wrapped in JSON | JSON can't carry raw binary, so file bytes and JPEG/audio frames are encoded as strings first |
| **Concurrency** | Threading — a dedicated daemon thread per connected client on the server, and per-purpose daemon threads (network listener, video/audio capture, video/audio playback) on the client | Keeps the UI responsive and lets media and text flow independently; `threading.Lock()` guards the server's shared state |

---

## Built with

| Layer | Technology |
|---|---|
| Language | Python 3.x |
| Networking | `socket`, `threading` |
| GUI | `tkinter` |
| Media capture/playback | OpenCV (`cv2`), `pyaudio`, Pillow |
| Serialization | `json`, `base64` |

---

## Core Components

| Component | Responsibility |
|---|---|
| **Relay Server** | Binds to `0.0.0.0:5555`; holds `active_clients`, `channels`, and `active_media_sessions` in memory; spawns a `manage_client_session` thread per client |
| **`broadcast()`** | Sends a payload to every connected client (used for roster/user-join updates) |
| **`channel_broadcast()`** | Sends a payload only to the subscribers of a specific channel |
| **`direct_message()`** | Looks up a target user's socket in `active_clients` and forwards a private payload |
| **Client (Tkinter GUI)** | Collects host/port/username, renders chat channels and direct messages, and drives file/media interactions |
| **`video_rx_queue` / `audio_rx_queue`** | Bounded queues (`maxsize=8` / `maxsize=50`) that decouple network receipt from rendering, dropping frames rather than backing up when the renderer falls behind |

---

## Key Engineering Challenges & Solutions

| Challenge | Cause | Solution |
|---|---|---|
| **TCP stream fragmentation** | Rapid payloads (e.g. 30 video frames/sec) can merge multiple JSON objects into a single `recv()` read, breaking naive `json.loads()` parsing | A buffered parser using `json.JSONDecoder().raw_decode()` incrementally extracts complete JSON objects from a running buffer, holding incomplete data for the next read |
| **Memory exhaustion on file upload** | Base64-encoding a large file in memory can freeze or crash the client | Client-side check rejects any file over 20MB before encoding begins |
| **Media stuttering / backlog** | TCP guarantees delivery, so network congestion backs up video frames in the receive queue, freezing the UI as it tries to render stale frames | Bounded queues with `put_nowait()` — when full, new frames are dropped via a caught `queue.Full` exception rather than blocking |

---

## Testing & Performance

The system was validated through manual functional testing, concurrent-client load testing (5 simultaneous clients), and error-handling checks (duplicate usernames, oversized files), all passing against their expected outcomes.

**Key performance findings:**
- **Bandwidth overhead:** Base64 encoding adds roughly 33% overhead to all media and file traffic, on top of JSON's structural padding
- **Server bandwidth scales O(n):** because media is relayed rather than sent peer-to-peer, server bandwidth grows linearly with the number of concurrent video calls, capping how many users can call at once
- **Artificial latency floor:** a hard-coded `time.sleep(VIDEO_FPS_DELAY)` throttles video capture to roughly 20 FPS to keep the TCP socket from saturating
- **No encryption:** Wireshark capture confirms all traffic — including credentials and media — travels as plaintext or trivially decodable Base64

---

## Getting it running

**Prerequisites:** Python 3.x with `tkinter`, `opencv-python`, `pyaudio`, and `Pillow`

```bash
pip install opencv-python pyaudio pillow
```

**Start the relay server:**
```bash
python server.py
```

**Start a client (in a separate terminal, one per user):**
```bash
python client.py
```

In the client's login window, enter the server's IP (`127.0.0.1` for local testing), port (`5555` by default), and a unique username, then click **Connect**.

---

## Known Limitations

- All traffic — including real-time audio/video — is multiplexed over a single TCP socket, causing stuttering under packet loss instead of the graceful degradation UDP would offer
- No encryption or TLS — passwords and media are transmitted in plaintext or easily decodable Base64
- Server bandwidth requirements scale linearly with concurrent video calls, limiting maximum usable concurrency
- A hard-coded frame-rate delay imposes an artificial latency floor rather than adapting to real network conditions
- Dedicated "log sharing" isn't separately implemented — it relies entirely on the general file-sharing mechanism

---

## Possible Future Work

- Move real-time audio/video onto a separate UDP channel, keeping TCP for signaling and chat
- Add TLS encryption across all traffic
- Move video relaying toward a mesh or SFU model to remove the server's O(n) bandwidth bottleneck
- Replace the fixed frame-rate cap with adaptive bitrate/frame-rate based on measured network conditions
- Add real authentication in place of a username-only login

---

## License

Built for academic purposes as part of a Computer Networks course.