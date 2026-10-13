# ETag maintenance in TLA+

Three models of how stored ETags are kept up to date, checked with TLC:

- `EtagCurrent.tla`: the protocol in `vng_api_common/caching` at 78837e0, the
  head of PR #186; `EarlyCutoff = FALSE` gives the protocol before it, as on main.
- `EtagProposed.tla`: a proposal, not chosen: recompute after commit under a
  row lock. Each design decision is a constant, so it can be reverted on its
  own.
- `EtagToken.tla`: the design chosen. A writer sets `_etag` to a token of its
  own inside the transaction; anyone fills it later with
  `UPDATE … WHERE _etag = <token read>`. Its decisions are constants too.

All three model the same world: one parent resource whose representation is its
own column plus the set of child rows pointing at it (FK `on_delete=CASCADE`),
and request threads running READ COMMITTED transactions with row locks and one
savepoint.

The first two recompute in `on_commit` callbacks, and their property is
`EtagsCorrect`: once all work has drained, every stored ETag equals the
representation. `EtagToken` has independent fillers that may fill any parent at
any time, and a stronger property, `NeverWrong`: at every state, a stored ETag
is right or a token.

## The problem

Storing an ETag is memoisation of a pure function:
`ETag = hash(representation(state, code))`. Keeping it right is cache
invalidation, governed by the laws of memoisation:

1. The memoised ETag depends only on committed state and code.
2. Its key covers every input: the query, the code version, the domain.
3. A write invalidates every memoised ETag whose inputs it touches, before or
   after the write.
4. Invalidation is atomic with the write.
5. An ETag is memoised only if its inputs are unchanged since they were read.

`EtagToken` is these laws: a write replaces the memoised ETag with a fresh
token (3, 4), and a fill is a compare-and-set on that token (5). `NeverWrong`
states the result in one line. Law 2 is outside the models; see
Simplifications.

## Running

```sh
./check.sh                  # every model; exits non-zero on a surprise
./check.sh token            # one model
./check.sh token_mutant     # a group
```

Needs Java, `tla2tools.jar` (default `/opt/TLA+Toolbox/tla2tools.jar`,
override with `TLA2TOOLS`) and preferably a systemd user session. Each config
in `models/` states its expected outcome on its first line; TLC's output,
including counterexample traces, goes to `out/`.

Every run is capped: 8 GB for TLC and its files, with no swap (`TLC_MEMORY`),
a 4 GB heap (`TLC_HEAP`), all cores but 4 (`TLC_WORKERS`) and 15 minutes
(`TLC_TIMEOUT`). A run over a cap is reported as "out of memory" or "timed
out". TLC's state files go
to `out/states/` on disk, because `/tmp` may be a tmpfs, which uses RAM.

| Group | Expected | Shows |
| --- | --- | --- |
| `current_*` | violated, except the two sanity models | each bug in the current protocol, one workload per bug |
| `proposed`, `proposed_three_threads`, `proposed_no_cutoff*` | no error | the proposal is correct in these scopes |
| `proposed_mutant_*` | violated | every design decision is needed |
| `proposed_nv_*` | the `NV_` invariant violated | the situations the proof must cover are reachable |
| `token`, `token_two_fillers`, `token_tokens_only`, `token_three_writers` | no error | the token design is correct in these scopes |
| `token_mutant_*` | violated | every design decision is needed |
| `token_nv_*` | the `NV_` invariant violated | the situations the proof must cover are reachable |

The token configs check writer fills, two racing fillers and savepoints in
pairs: all three together come to about 32 million states, too many for the
caps. Runs that only check `NeverWrong` leave `hist` out of the state with
`VIEW NoHist`.

## Reading

`tla2tex`, in `tla2tools.jar`, typesets a spec as a PDF, which reads more easily
than the ASCII source. It needs `pdflatex`:

```sh
mkdir -p out && cd out
java -cp "${TLA2TOOLS:-/opt/TLA+Toolbox/tla2tools.jar}" tla2tex.TLA \
    -shade -nops -latexCommand pdflatex -out EtagToken ../EtagToken.tla
```

## Simplifications

- A recompute in `EtagProposed` reads its row and the child list in one step.
  Reading them in separate READ COMMITTED queries can mix snapshots, but only
  for a recompute that a later one supersedes. `EtagToken`'s fillers do read
  them in separate statements.
- A delete or move reads the child's old FK at write time, under the row lock.
  The implementation must do the same; an instance loaded earlier may be stale.
- A write and its invalidations lock their rows in one step; lock order and
  deadlocks are not modelled (a blocked transaction may always roll back).
- One relation, no nested serializers, m2m or `expand`; parents are never
  deleted.
- Small scope: 2 parents, 2 children, 2 threads with up to 2 writes each, an
  own column with 2 values; 3 threads with 1 write each, without savepoints.
  `EtagToken` adds 1 or 2 fillers.
