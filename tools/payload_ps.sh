#!/bin/bash
ps -eo pid,etimes,args | grep "doom_payloa[d].py" | cut -c1-150
echo "--- payload.log tail:"; tail -6 /root/doom/run/payload.log
echo "--- port 4242:"; ss -ltnp 2>/dev/null | grep 4242
