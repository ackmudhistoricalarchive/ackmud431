#!/bin/bash
set -euo pipefail
TARGET="deploy@10.1.0.242"
SSH="ssh -o StrictHostKeyChecking=no"
# Build
cd src
make
cd -
# Stop service, deploy binary, restart
$SSH $TARGET "sudo systemctl stop mud"
scp -o StrictHostKeyChecking=no src/ack $TARGET:/opt/mud/src/src/ack
$SSH $TARGET "sudo systemctl start mud"
echo "Deployed to ackmud431"
