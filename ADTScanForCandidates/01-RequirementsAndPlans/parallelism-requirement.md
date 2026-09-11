# Requirement: Parallelism for the ADT Scan

## Why

The scan reads ~50 million small ADT files, one GET per file. Run sequentially
from a PC that is roughly 1–3 weeks of wall-clock time. The cost is the same
either way (one GET per file regardless of concurrency), but parallelism turns
a multi-week laptop run into a few days. Speed is not the goal of the project,
but a run that finishes in a reasonable time is worth having.

## Requirement

The scanner shall support **configurable parallelism** for downloading and
parsing files, while preserving every guarantee from the main requirements
(restart-safe, never process a file twice, complete and correct match output).

### Configuration
- A single config value controls worker count, e.g. `WORKERS` (or
  `MAX_WORKERS`) in `config.py`.
- **Default is 1** (pure sequential) so behavior is unchanged unless a user
  opts in. The user dials it up (e.g. 8–16) for a laptop run.
- Concurrency applies to the per-file work (S3 GET + parse + match). Bucket
  listing stays a single paginated stream that feeds the workers.

### Correctness guarantees that MUST hold with parallelism on
1. **Never process the same file twice.** The processed-files ledger remains
   the single source of truth. A worker checks the ledger before downloading,
   and a file is only added to the ledger AFTER its result is written.
2. **Restart-safe.** If the run is interrupted, restarting skips everything in
   the ledger and continues. At most a small, bounded number of in-flight
   files may be re-processed after a crash — re-processing is harmless
   (idempotent match output), never a lost file.
3. **No corrupted / interleaved output.** Writes to the matches file, the
   ledger, and the errors log must be serialized (a lock or a single writer
   thread) so concurrent workers cannot interleave partial lines.
4. **A file is marked done only after its match rows are durably written.**
   Order of operations per file: parse → write any match rows → append key to
   ledger. If the process dies between steps, the file is simply retried next
   run (it is not in the ledger yet).
5. **Errors do not enter the ledger.** A file that fails download/parse is
   logged to the errors log and left OUT of the ledger so it is retried on the
   next run — same as the sequential behavior.

### Implementation guidance (not prescriptive)
- A bounded thread pool (e.g. `concurrent.futures.ThreadPoolExecutor`) is a
  good fit: the work is I/O-bound (network + small parse), so threads are
  effective and simpler than processes. `boto3` clients are not thread-safe to
  share for all operations — give each worker its own client/session, or use a
  thread-safe pattern.
- Keep a single writer for each output file (matches, ledger, errors) guarded
  by a lock, so serialization is trivial and lines never interleave.
- Flush the ledger and outputs on the same cadence as sequential
  (`FLUSH_EVERY`), measured in completed files.
- Progress reporting should remain accurate under concurrency (count completed
  files, not dispatched files).

### Non-goals
- No distributed / multi-machine coordination. Single process, multiple
  worker threads.
- No change to cost. Concurrency does not add GET requests; it only overlaps
  their latency.
- No requirement to preserve file processing order.

## Acceptance
- Setting `WORKERS = 1` behaves exactly like the original sequential scanner.
- Setting `WORKERS = 12` (for example) completes the same scan faster, with
  identical match output and a ledger containing every processed key exactly
  once.
- Killing the process mid-run and restarting resumes without re-GETting files
  already in the ledger and without dropping any un-processed file.
