#!/bin/bash

##############################################################
# This script has to be placed in /home/pi/marilib
##############################################################

# update
sudo apt update
sudo apt install -y python3-venv tmux


# install and activate the virtual environment
python3 -m venv venv
source venv/bin/activate

# Install the Python packages needed by marilib inside the venv
sudo venv/bin/pip install --upgrade pip
sudo venv/bin/pip install -e . --default-timeout=100

