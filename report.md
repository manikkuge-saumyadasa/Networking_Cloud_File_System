# CloudFS — Cloud File System
### CSC474/574 Computer Networks — Programming Assignment

**Author:** [Your Name]  
**Language:** Python 3 (Flask)  
**Public Access:** Tailscale Funnel (HTTPS)

---

## How to Run

### Prerequisites
- Python 3.8+
- pip
- [Tailscale](https://tailscale.com/download) installed and logged in (for public access)

### Step 1 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 2 — Start the server
```bash
python server.py
```
Server listens on `http://0.0.0.0:8080`

### Step 3 — Expose publicly via Tailscale Funnel
In a second terminal:
```bash
tailscale funnel 8080
```
Tailscale will print a public HTTPS URL like:
```
https://your-machine-name.tail12345.ts.net
```
Share this URL with anyone — they can access your cloud from any browser.

---

## How It Works (TCP + Sockets)

Flask runs an HTTP server bound to TCP port 8080. Every browser request
(upload, download, list, delete) is a TCP connection:

```
Browser ──TCP:443──► Tailscale Funnel ──TCP:8080──► Flask Server
```

Tailscale Funnel:
- Accepts public HTTPS traffic on port 443
- Decrypts TLS and forwards plain TCP to your local port 8080
- No port forwarding or public IP needed

---

## Requirements Coverage

| Requirement | Implementation |
|---|---|
| Read files | GET /api/files/<user> |
| Write/upload files | POST /api/upload/<user> |
| List directory | GET /api/files/<user> returns JSON list |
| Multiple users | Each user gets their own folder under /storage/ |
| Remotely accessible | Tailscale Funnel provides public HTTPS URL |

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/users` | GET | List all users |
| `/api/users` | POST | Create or login user |
| `/api/files/<user>` | GET | List user's files |
| `/api/upload/<user>` | POST | Upload file(s) |
| `/api/download/<user>/<file>` | GET | Download a file |
| `/api/delete/<user>/<file>` | DELETE | Delete a file |
