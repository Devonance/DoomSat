#!/bin/bash
# Windows-side wrapper: control the WSL flight side. Usage: flight.sh start|stop|status|check|build|rebuild
case "$1" in
  build)   MSYS_NO_PATHCONV=1 wsl -d ros2 -u root -- bash /mnt/c/Users/Kevin/Genai/doom-mission/scripts/wsl_build.sh ;;
  rebuild) MSYS_NO_PATHCONV=1 wsl -d ros2 -u root -- bash /mnt/c/Users/Kevin/Genai/doom-mission/scripts/wsl_rebuild.sh ;;
  check)   MSYS_NO_PATHCONV=1 wsl -d ros2 -u root -- bash /mnt/c/Users/Kevin/Genai/doom-mission/scripts/wsl_check.sh ;;
  *)       MSYS_NO_PATHCONV=1 wsl -d ros2 -u root -- bash /mnt/c/Users/Kevin/Genai/doom-mission/scripts/wsl_run_flight.sh "${1:-start}" ;;
esac
