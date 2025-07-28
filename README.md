# Wiretide Controller.

**Wiretide** is a lightweight controller for managing **OpenWRT devices** via a central server.  
It provides a simple web interface, API, and agent integration for device registration, monitoring, and management.

> **Status:** ALPHA — Expect bugs and breaking changes.  
> The agent is still under development and needs testing.

---

## Features
- Centralized management for OpenWRT devices.
- Web UI with login and device dashboard.
- Auto-registration and heartbeat endpoints for agents.
- HTTPS enabled by default (self-signed certificate).
- SQLite-based backend with easy setup.

---

## Installation (Ubuntu 24.04 or newer)

Run the following commands on your server:

```bash
wget https://raw.githubusercontent.com/simonsays-techtalk/wiretide-controller/main/install.sh -O install.sh
chmod +x install.sh
sudo ./install.sh
```

```
Install wiretide agent on openwrt device
wget -O - http://192.168.188.61/static/agent/install.sh | sh
```

After installation:

    Access the controller via your browser: https://<server-ip>/

    Default credentials:

    Username: admin
    Password: wiretide

    An API token (for agents) will be generated and displayed at the end of the install.

Notes

    The included self-signed TLS certificate will trigger browser warnings.
    For testing, curl commands can use -k to skip certificate checks:

curl -k https://server.ip/api/status

All assets (logo, agent download files) are served from /static/.
Place any custom branding or agent packages in:

    /opt/wiretide/wiretide/static/

Roadmap

    Finalize and test the Wiretide Agent for OpenWRT.

    Add audit logging and advanced device configuration.

    Web UI improvements and more device metrics.

    Support for easy upgrades and uninstall.
