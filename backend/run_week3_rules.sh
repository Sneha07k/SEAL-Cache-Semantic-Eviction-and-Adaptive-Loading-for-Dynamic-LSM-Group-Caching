#!/usr/bin/env bash
# Decision-rule re-validation under the corrected (shared hot set) protocol.
# Question: does filtering/low-priority placement of maintained groups still only hurt?
# Rules fixed BEFORE running (same as week 2c): compare each variant to zio-naive (always
# install, inherit recency) with paired per-seed CIs; criterion = mean gain vs Group Cache over
# 20/50/80% writes, never worse than Group Cache. Seeds 6-15 (fresh), paper write mix.
# Waits for run_week3.sh to finish (its last CSV) before using the CPUs.
# Usage: cd backend && bash run_week3_rules.sh      WORKERS=12 by default.
set -euo pipefail
W=${WORKERS:-12}
OUT=results/week3
until [ -s "$OUT/warm160k_write_200k.csv" ]; do sleep 30; done
python -m app.experiments.fidelity --sweep write --block-size 48 --values 0.2,0.5,0.8 \
  --caches group,block,zio-naive,zio-lrus,zio-hot,zio-naive-tail,zio-lrus-tail,zio-hot-tail \
  --insert-share 0.5 --keys 200000 --warmup 40000 --ops 40000 --seeds 10 --seed-offset 6 \
  --workers $W --out "$OUT/rules_write_200k.csv" | tee "$OUT/rules_write_200k.log"
