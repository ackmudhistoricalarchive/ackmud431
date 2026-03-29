#!/bin/bash
set -euo pipefail
TARGET="deploy@10.1.0.242"
SSH="ssh -o StrictHostKeyChecking=no"
# Build
cd src
make
cd -
# Deploy binary
scp -o StrictHostKeyChecking=no src/ack $TARGET:/opt/mud/src/src/ack
# Restart service
$SSH $TARGET "sudo systemctl restart mud"
echo "Deployed to ackmud431"
