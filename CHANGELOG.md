# Changelog

## 0.2.0

This release has 18 commits since 0.1.0. Seven of them are daily ledger data commits.

### Added

- The daily performance ledger. `coreglass ledger run` runs a frozen suite on each Mac. The suite is Qwen3.8-2B 4-bit and Qwen3-4B 4-bit on mlx-lm and oMLX, plus ANE and GPU matmul cells. It writes `docs/ledger.json` and `docs/LEDGER.md`. Each row is the median of 3 reps with its min and max.
- `coreglass ledger mark`, `add` and `render`. `mark` flags a row as contaminated. The row stays on the page and is never a baseline. `add` merges finished captures that a run never merged. `render` rewrites the page from the data file.
- `coreglass ledger run --stack` measures only the named stacks. It skips the server cells.
- `quiet_set` and `quiet_clear` per target in `ledger.toml`. They reserve a Mac for one rep.
- Power state per rep, read from the Mac's SMC. If the reps of a row ran more than 20 percent apart in loaded system power, the row is marked NOISY. It is never a baseline or a regression.
- `docs/BY-FEATURE.md`. It is a page by feature, with the driver commit and the source record on every row.

### Changed

- The ledger page renders `n/a` for a missing cell.
- `README.md` and `docs/DESIGN.md` now cover the capture frame, the summary, the ledger and the run flags. They also cover the `ingest-lab`, `ledger mark`, `ledger add` and `ledger render` commands.
- `AGENTS.md` states the review and merge rule for pull requests.
- `FUNDING.yml` lists Ko-fi.

### Measured in this release

- `docs/ledger.json` holds 85 rows from 2026-10-05 to 2026-10-15. There are 78 Linux rows and 7 macOS reference rows on 4 chips.
- One example row is the Apple M2 Max on 2026-10-15 with Qwen3.8-2B 4-bit mlx-lm decode, median of 3 reps. The release stack reads 96.8 tok/s (min 96.4, max 97.1). The main stack reads 100.4 tok/s (min 100.3, max 100.6).
- On the same day the page flags the Apple M1 main stack as 4.6 percent slower than its release stack, for 2B mlx-lm decode.
- The test suite runs 30 tests. All of them pass.
