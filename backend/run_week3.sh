#!/usr/bin/env bash
# Week-3 final evaluation: every sweep, fresh seeds 6-15, paper write mix (insert-share 0.5).
# Protocol (calibrated on seeds 100-102 AFTER the shared-hot-set fix; rule: <1% change on
# doubling warm-up, met only in the update-only diagnostic at 40K; see results/week3/calibrate_*):
#   200K keys, 40K warm-up ops, 40K measured ops, 48-key blocks, cache 5% of initial data.
# Usage: cd backend && bash run_week3.sh [sweep ...]   (default: all)   WORKERS=12 by default.
set -euo pipefail
W=${WORKERS:-12}
OUT=results/week3
CACHES=none,block,range,group,zio-naive,group+seed,group+complete
COMMON="--insert-share 0.5 --keys 200000 --warmup 40000 --ops 40000 --seeds 10 --seed-offset 6 --workers $W"
mkdir -p "$OUT"
run() { name=$1; shift
  echo "== $name"; python -m app.experiments.fidelity "$@" --caches "$CACHES" $COMMON \
    --out "$OUT/$name.csv" | tee "$OUT/$name.log"; }

SWEEPS=("$@"); [ ${#SWEEPS[@]} -eq 0 ] && SWEEPS=(write scan size zipf tiering block16 warm160k)

for s in "${SWEEPS[@]}"; do case $s in
  write)   run write_sweep_200k --sweep write --block-size 48 ;;
  scan)    run scan_sweep_200k  --sweep scan  --block-size 48 --write-ratio 0.5 --values 0.2,0.5,0.8 ;;
  size)    run size_sweep_200k  --sweep size  --block-size 48 --write-ratio 0.5 ;;
  zipf)    run zipf_sweep_200k  --sweep zipf  --block-size 48 --write-ratio 0.5 ;;
  tiering) run tiering_write_200k --sweep write --block-size 48 --policy tiering ;;
  block16) run block16_write_200k --sweep write --block-size 16 ;;
  warm160k) python -m app.experiments.fidelity --sweep write --block-size 48 --values 0.5 \
              --caches "$CACHES" --insert-share 0.5 --keys 200000 --warmup 160000 --ops 40000 \
              --seeds 10 --seed-offset 6 --workers $W --out "$OUT/warm160k_write_200k.csv" \
              | tee "$OUT/warm160k_write_200k.log" ;;
  *) echo "unknown sweep $s"; exit 2 ;;
esac; done
