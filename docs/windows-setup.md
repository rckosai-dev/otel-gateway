# Running locally on Windows

This project's `Makefile`, `scripts/*.sh`, and overall workflow assume a
Unix-like environment (bash, `make`, `/`-style paths). The right way to run
it on Windows is **not** to port everything to PowerShell — it's to run the
repository inside **WSL2**, with Docker Desktop integrated into it. That
way nothing in the project needs to change; you just get a Linux shell on
Windows that talks to the same Docker engine.

## Which container runtime to use

**Docker Desktop with the WSL2 backend** is the right choice here — free
for personal/portfolio use, full compatibility with the Compose v2 syntax
this project uses (`profiles`, `depends_on: condition: service_healthy`,
`depends_on: condition: service_completed_successfully`), and much better
I/O performance than the old Hyper-V backend.

| Option | Why it's not the best fit here |
|---|---|
| Podman Desktop | Needs `podman-compose` (partial compatibility with `profiles`/`depends_on: condition`) or the Docker-compatible socket — more friction for no real benefit for personal use |
| Rancher Desktop | Works (in "dockerd moby" mode), but it's an extra layer with no advantage over Docker Desktop for this case |
| Docker Engine directly inside WSL2 (no Docker Desktop) | More "CLI-pure" and avoids Docker Desktop's commercial license (irrelevant for personal use), but requires manually configuring the daemon — only worth it if you need to avoid Docker Desktop for corporate policy reasons |

## Prerequisites

1. **Windows 10 version 2004+ (build 19041+) or Windows 11**
2. **Virtualization enabled in BIOS/UEFI** (Intel VT-x or AMD-V) — usually
   already on; check Task Manager → Performance → CPU → "Virtualization: Enabled"
3. **WSL2** with a Linux distro (Ubuntu recommended)
4. **Docker Desktop for Windows** (with WSL2 integration enabled)
5. **Git** (inside WSL2, via `apt`)
6. **Python 3.11+** (inside WSL2)
7. **make** (ships by default on Ubuntu WSL2, or installable via `apt`)

## Step-by-step

### 1. Install and enable WSL2

Open **PowerShell as Administrator**:

```powershell
wsl --install
```

This installs WSL2 and the Ubuntu distro by default. Restart Windows if
prompted.

If WSL was already installed, force version 2:

```powershell
wsl --set-default-version 2
wsl --update
```

Verify:

```powershell
wsl --list --verbose
```

It should show `Ubuntu` with `VERSION 2`.

On first launch of Ubuntu (Start Menu → "Ubuntu"), create your Linux
username/password when prompted.

### 2. Install Docker Desktop

1. Download from https://www.docker.com/products/docker-desktop/
2. During installation, check **"Use WSL 2 instead of Hyper-V"** (the
   default in recent versions)
3. After installing, open Docker Desktop → **Settings → Resources → WSL Integration**
4. Enable **"Enable integration with my default WSL distro"** and check `Ubuntu` specifically
5. Click **Apply & Restart**

Verify from inside the Ubuntu (WSL2) terminal:

```bash
docker --version
docker compose version
```

Both should respond without error — that confirms Docker Desktop is
correctly exposing its daemon into WSL2.

### 3. Prepare the Linux environment (inside WSL2/Ubuntu)

**Important**: clone the repository inside the WSL2 filesystem (`~/`, e.g.
`/home/your-user/otel-gateway`), **not** under `/mnt/c/...` (Windows) —
that avoids severe I/O degradation and permission/line-ending issues.

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv make curl
```

### 4. Clone and set up the project

```bash
git clone <repo-url> ~/otel-gateway
cd ~/otel-gateway

cp .env.example .env

python3 -m venv .venv
source .venv/bin/activate
pip install -r policy-compiler/requirements.txt -r scripts/requirements.txt
```

### 5. Watch out for line endings (CRLF vs LF)

If you ever clone or edit the files from the Windows side (e.g. VS Code
without WSL Remote), Git may convert `scripts/*.sh` and the `Makefile` to
CRLF, breaking execution inside the Linux containers (a common symptom is
`/bin/sh: bad interpreter`). Set this before cloning:

```bash
git config --global core.autocrlf input
```

### 6. Bring the stack up

```bash
make up
```

This runs `make compile-policy` and then `docker compose up -d`.
Endpoints (reachable normally from your **Windows** browser, since Docker
Desktop forwards WSL2 ports to the host's `localhost` automatically):

- Grafana: http://localhost:3000 (admin/admin)
- Prometheus: http://localhost:9090
- MinIO console: http://localhost:9001

### 7. Generate load and validate

```bash
make load-smoke   # short load, 30s
# or
make load         # full load, 5 min
bash scripts/validate-e2e.sh
```

From here on, follow the rest of the flow in `docs/runbook.md` (sections
4–9) as-is — nothing changes, it's the same Linux environment as the rest
of the runbook.

## Windows-specific troubleshooting

| Symptom | Cause / fix |
|---|---|
| `docker: command not found` inside WSL2 | Docker Desktop's WSL integration isn't enabled for the distro — revisit step 2.4 |
| Containers are very slow, `make up` takes minutes | Repo cloned under `/mnt/c/...` instead of `~/` — move it inside the WSL2 filesystem |
| `bad interpreter: /bin/sh^M` or similar error in scripts | CRLF line endings — set `core.autocrlf input` and re-clone |
| Docker Desktop using too much RAM | Create/edit `%UserProfile%\.wslconfig` on Windows to cap memory: <br>`[wsl2]`<br>`memory=6GB`<br>`processors=4` |
| Windows Firewall prompts when Docker Desktop starts | Allow it on both private/public networks — required for the daemon to expose ports |
| Ports 3000/9090/9000 already in use on Windows | Another local service is using the port — stop it or change the published port in `docker-compose.yml` |
