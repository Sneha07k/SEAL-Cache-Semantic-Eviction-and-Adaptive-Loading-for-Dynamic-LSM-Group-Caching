# Mismatched warm-up (SENSITIVITY data only, not the headline protocol)

These runs used the original trace generation: the warm-up trace (seed+1000) and the measured
trace (seed) drew DIFFERENT hot-key permutations (top-100 hot keys shared: 0/100), so caches
were not warm on the measured hot set. Found 2026-10-17; fixed by giving both traces the same
`perm_seed`. Keep as a labelled sensitivity row ("warm-up on a different hot set"):
  write_sweep_200k.csv   seeds 6-15, 200K keys, 40K warm-up/40K measured, 7 caches (complete)
  write_sweep_200k_run1.csv  identical re-run (determinism check; 280/280 rows equal)
calibrate_warmup*.csv: calibration on seeds 100-102 -- its conclusion is NOT valid for the
corrected protocol (it measured tree growth, not cache warm-up). The scan sweep was stopped
before finishing and left no CSV.
