pytest -q -s \
  --asof  "2025-07-09 00:00:00" \
  --window-h 36 \
  --traj-csv "/data/common/dataiku2/managed_folders/NEATS/Q3xncFlG/Flights_20250709_sample.csv" \
  --zarr-path "/datasave/NEATS_CLEAN/NyYXp7uG" \
  --model-type CTFM \
  --flight-id WZZ6457 --adep LEBL --ades EPKT --reg 9HWBO \
  --expect "expected_values.json"