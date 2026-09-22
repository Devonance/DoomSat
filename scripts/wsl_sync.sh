#!/bin/bash
# Copy the flight-side sources from the Windows repo into the F´ project in WSL.
set -e
SRC=/mnt/c/Users/Kevin/Genai/DoomSat/flight
DST=/root/doom/DoomSat
mkdir -p $DST/DoomMission/Components/Doom $DST/DoomMission/config
cp $SRC/Components/Doom/Doom.fpp $SRC/Components/Doom/Doom.hpp $SRC/Components/Doom/Doom.cpp $SRC/Components/Doom/CMakeLists.txt $DST/DoomMission/Components/Doom/
cp $SRC/DoomSat/Top/topology.fpp $SRC/DoomSat/Top/instances.fpp $SRC/DoomSat/Top/DoomSatTopology.cpp $DST/DoomSat/Top/
cp $SRC/config/FpConstants.fpp $SRC/config/CMakeLists.txt $DST/DoomMission/config/
grep -q "/Doom/" $DST/DoomMission/Components/CMakeLists.txt || echo 'add_fprime_subdirectory("${CMAKE_CURRENT_LIST_DIR}/Doom/")' >> $DST/DoomMission/Components/CMakeLists.txt
grep -q "/config" $DST/DoomMission/CMakeLists.txt || sed -i '1i add_fprime_subdirectory("${CMAKE_CURRENT_LIST_DIR}/config/")' $DST/DoomMission/CMakeLists.txt
# Rate group rename (20 Hz base clock) must also apply to the health ping entries
sed -i 's/rateGroup_0_5Hz/rateGroup_20Hz/g' $DST/DoomSat/Top/DoomSatTopologyDefs.hpp
# Undo the earlier (wrong) whole-directory config override attempt if present
sed -i '/^config_directory/d' $DST/settings.ini
rm -rf $DST/config
echo SYNCED
