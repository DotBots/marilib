# bind the nrf gateway to port /dev/ttyACM10
# should only attach one gateway to the Raspberry Pi, if you attach more the last one will be used
sudo tee /etc/udev/rules.d/99-nrf-serial.rules >/dev/null <<'RULE'
# SEGGER J-Link  — map interface 00  to /dev/ttyACM10
SUBSYSTEM=="tty", ATTRS{idVendor}=="1366", ATTRS{idProduct}=="1051", ENV{ID_USB_INTERFACE_NUM}=="00", SYMLINK+="ttyACM10"
RULE

sudo udevadm control --reload
sudo udevadm trigger