#!/usr/bin/env bash
set -o pipefail

docker exec apollo_dev_ser bash -lc '
cd /apollo
git config --global --add safe.directory /apollo || true
./apollo.sh build_cpu cyber common_msgs dreamview monitor localization routing planning prediction control canbus transform map
'
