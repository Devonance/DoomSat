#!/bin/bash
# One-time WSL provisioning for the Doom mission demo (runs inside the ros2 distro as root).
set -x
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq python3-venv python3-pip > /root/doom/apt_venv.log 2>&1 && echo APT_VENV_OK
cd /root/doom || exit 1
rm -rf payload-venv bootstrap-venv doom-mission
python3 -m venv payload-venv && ./payload-venv/bin/pip install -q --upgrade pip && ./payload-venv/bin/pip install -q vizdoom==1.3.0 numpy pillow && echo PAYLOAD_VENV_OK
python3 -m venv bootstrap-venv && ./bootstrap-venv/bin/pip install -q fprime-bootstrap && echo BOOTSTRAP_OK
printf "doom-mission\nDoomMission\n" | ./bootstrap-venv/bin/fprime-bootstrap project --path /root/doom --tag v4.3.0 && echo PROJECT_OK
cd /root/doom/DoomSat && . fprime-venv/bin/activate && pip install -q fprime-yamcs && pip list 2>/dev/null | grep -i -E "fprime|yamcs" && echo YAMCS_PIP_OK
