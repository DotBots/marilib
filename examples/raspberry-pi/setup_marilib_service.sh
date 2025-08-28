# === Step 1: Clone or unzip marilib repo ===
cd /home/pi/marilib

# === Step 2: Install marilib ===
sudo chmod +x install_marilib.sh
source install_marilib.sh

# === Step 3: bind the gateway to systemlink port /dev/ttyACM10 ===
cd /home/pi/marilib/examples/raspberry-pi
sudo chmod +x bind_interface.sh
source bind_interface.sh

# === Step 4: create the service to run marilib on boot once the gateway is connected ===
cat <<'EOF' | sudo tee /etc/systemd/system/setup_marilib.service

[Unit]
Description=run marilib on boot
#If the gateway disconnects, stop the service

[Service]
User=pi
WorkingDirectory=/home/pi/marilib

#refuse to start if the gateway device is missing
ExecStartPre=/bin/sleep 5

#check that ttyACM10 is available not just that it exists
ExecStartPre=/usr/bin/udevadm settle
ExecStartPre=/bin/bash -c "for i in {1..600}; do exec 3<>/dev/ttyACM10 && exit 0 || sleep 0.2; done; echo 'Gateway port: ttyACM10 not ready, the service has stopped and will not restart, check connections and reboot' >&2; exit 1"

#run basic.py
ExecStart=/usr/bin/tmux new-session -s marilib -d "/home/pi/marilib/venv/bin/python /home/pi/marilib/examples/mari_edge.py -p /dev/ttyACM10"
ExecStop=/usr/bin/tmux kill-session -t marilib
Type=forking

Restart=on-failure
RestartSec=1

[Install]
WantedBy=multi-user.target
EOF

# === Step 5:  create a path unit that triggers when the gateway device appears ===
cat <<'EOF' | sudo tee /etc/systemd/system/setup_marilib.path
[Unit]
Description=Launch marilib when the gateway appears on /dev/ttyACM10

[Path]
PathExists=/dev/ttyACM10

[Install]
WantedBy=multi-user.target
EOF

# reload systemd units and enable
sudo systemctl daemon-reload
sudo systemctl enable --now setup_marilib.path
sudo systemctl enable setup_marilib.service