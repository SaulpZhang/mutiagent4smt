#!/bin/bash
set -e

cd "$(dirname "$0")"

RUN_ID="run_$(date +%Y%m%d_%H%M%S)"

groups=(
  "0 13" "13 26" "26 39" "39 52" "52 65"
  "65 78" "78 90" "90 102" "102 114" "114 126"
)

for i in "${!groups[@]}"; do
  g=${groups[$i]}
  from=$(echo "$g" | cut -d' ' -f1)
  to=$(echo "$g" | cut -d' ' -f2)
  conda run -n AI_Normal python main.py run \
    --runid "$RUN_ID" --from "$from" --to "$to" &
done

wait
