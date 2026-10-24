# Changelog

## 0.2.1

This release has 6 commits since 0.2.0. All six are daily ledger data commits, one for each of six ledger days: 2026-10-18 and 2026-10-20 to 2026-10-24. No code changed.

### Measured in this release

- `docs/ledger.json` holds 130 rows from 2026-10-05 to 2026-10-24, which is 45 rows more than 0.2.0. There are 123 Linux rows and 7 macOS reference rows on 4 chips.
- Each release and main row is the median of 3 reps with its min and max.
- One example row is the Apple M2 Max with Qwen3-4B 4-bit mlx-lm decode. On 2026-10-15 the main stack reads 53.9 tok/s (min 53.9, max 53.9). On 2026-10-24 the main stack reads 66.1 tok/s (min 66.0, max 66.3), which is 22.6 percent more. The release stack on 2026-10-24 reads 49.9 tok/s (min 49.7, max 49.9).
- The test suite runs 30 tests. All of them pass.

## 0.2.0

This release has 18 commits since 0.1.0. Seven of them are daily ledger data commits. The ledger itself, with `ledger run`, `mark`, `add` and `render`, already shipped in 0.1.0.

### Added

- `quiet_set` and `quiet_clear` per target in `ledger.toml`. They reserve a Mac for one rep. A failed reservation is logged and the rep still runs.
- Power state per rep, read from the Mac's SMC. The ledger records the system power, the AC input power and the heatpipe power, as the mean of the upper half of the samples of a rep. The page has a new Power state column.
- If the reps of a row ran more than 20 percent apart in loaded system power, the row is marked NOISY. A noisy row is never a baseline or a regression. A noisy rerun does not replace a clean row of the same day.
- `docs/BY-FEATURE.md`. It is a page by feature, with the driver commit and the source record on every row.

### Changed

- `coreglass ledger run --stack` now skips the server cells. It cannot be combined with `--cells-only`.
- The ledger page renders `n/a` for a missing cell.
- `README.md` and `docs/DESIGN.md` now document the capture frame, the summary, the ledger and the run flags. They also document the `ingest-lab`, `ledger mark`, `ledger add` and `ledger render` commands.
- `AGENTS.md` states the review and merge rule for pull requests.
- `FUNDING.yml` lists Ko-fi.

### Measured in this release

- `docs/ledger.json` holds 85 rows from 2026-10-05 to 2026-10-15. There are 78 Linux rows and 7 macOS reference rows on 4 chips.
- Each release and main row is the median of 3 reps with its min and max.
- One example row is the Apple M2 Max on 2026-10-15 with Qwen3.8-2B 4-bit mlx-lm decode. The release stack reads 96.8 tok/s (min 96.4, max 97.1). The main stack reads 100.4 tok/s (min 100.3, max 100.6).
- On the same day the page flags the Apple M1 main stack as 4.6 percent slower than its release stack, for 2B mlx-lm decode.
- The test suite runs 30 tests. All of them pass.
