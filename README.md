# Wiretide Controller

**Wiretide** is a lightweight controller for managing **OpenWRT devices** via a central server.  
It provides a simple web interface, REST API, and agent integration for registration, monitoring, and remote management.

> **Status:** ⚠️ ALPHA — Expect bugs and breaking changes.  
> The Wiretide agent is still under development and requires further testing.

---

## ✨ Features

- Centralized management for OpenWRT devices
- Web-based UI with login and device overview
- Agent registration and status (heartbeat) endpoints
- HTTPS enabled by default (with self-signed certificate)
- Simple SQLite backend — no external DB required

---

## 🚀 Installation (Ubuntu 24.04 or newer)

### Install the controller on your server:

```bash
wget https://raw.githubusercontent.com/simonsays-techtalk/wiretide-controller/main/install.sh -O install.sh
chmod +x install.sh
sudo ./install.sh
```

### Install the Wiretide agent on an OpenWRT device:

```bash
wget -O - http://<server-ip>/static/agent/install.sh | sh
```

### After installation:

- Visit the controller: `https://<server-ip>/`
- Default login:
  - **Username:** `admin`
  - **Password:** `wiretide`
- A **pre-shared API token** (for agent registration) will be shown at the end of the install process.

---

## 🔐 Notes

- A self-signed TLS certificate is used by default. Your browser will show a warning.

---

## 🛣️ Roadmap

- Finalize and stabilize the Wiretide Agent for OpenWRT
- Add audit logging and configurable device actions
- Improve Web UI with more device details
- Support upgrades, backups, and uninstall

