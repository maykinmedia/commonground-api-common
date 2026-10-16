------------------------------ MODULE EtagToken ------------------------------
(***************************************************************************)
(* Invalidate with a token, fill with a compare-and-set.                   *)
(*                                                                         *)
(* Same world as EtagProposed: one parent resource whose s_rep is its own  *)
(* column plus the set of child rows pointing at it, and request threads   *)
(* running READ COMMITTED transactions with row locks and one savepoint.   *)
(* Marking follows the proposal's rules (affected(w)), but instead of      *)
(* scheduling a recompute, a writer sets the parent's _etag to a token in  *)
(* the same transaction.  Fillers (a GET, an on_commit callback, a task:   *)
(* anyone, any time) replace a token by the ETag they computed, but only   *)
(* if the token is still the one they read.                                *)
(*                                                                         *)
(* The property is stronger than EtagsCorrect: a stored ETag is never      *)
(* wrong, at any state; at worst it is missing (a token).                  *)
(*                                                                         *)
(* One constant per design decision; all TRUE is the design:               *)
(*   FreshToken      every transaction writes its own token; FALSE: one    *)
(*                   shared "empty" marker, as in a naive lazy fill        *)
(*   InvalidateInTx  the token is written inside the writing transaction;  *)
(*                   FALSE: by an on_commit callback                       *)
(*   TokenFirst      a filler reads the token before the data it           *)
(*                   serializes; FALSE: after it                           *)
(*   CompareAndSet   a fill is UPDATE ... WHERE _etag = <token read>;      *)
(*                   FALSE: an unconditional UPDATE                        *)
(*   WriterFills     a writer may store the real ETag of a parent it has   *)
(*                   invalidated instead of the token: the general form of *)
(*                   track_object_serializer.  FALSE: tokens only          *)
(*   FillUnderLock   that writer serializes after taking the parent's row  *)
(*                   lock; FALSE: it may use data read before              *)
(*   DropFillOnWrite a later write in the same transaction that marks the  *)
(*                   parent turns its stored value back into the token     *)
(*                                                                         *)
(* Batching, as batched_invalidation(): the threads in BatchedTxs collect  *)
(* the parents they invalidate without writing their tokens, and Flush     *)
(* writes them all at once, taking their row locks.  Writes after the      *)
(* flush lock at once.  A savepoint rollback keeps what was collected, as  *)
(* the set in Python memory does.                                          *)
(*   FlushBeforeCommit  a batched thread flushes before it commits; FALSE: *)
(*                   it may commit unflushed, losing what it collected     *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    Parents, Children, Txs, Fillers, OwnValues, NoParent, MaxWrites, Ops,
    Savepoints,
    NoTok,        \* the token field of a real ETag
    Bottom,       \* the shared marker when FreshToken = FALSE
    FreshToken, InvalidateInTx, TokenFirst, CompareAndSet,
    WriterFills, FillUnderLock, DropFillOnWrite,
    BatchedTxs, FlushBeforeCommit

VARIABLES
    db,       \* committed rows, the _etag column included
    phase,    \* per thread: "idle", "active", "callbacks" or "done"
    wlog,     \* per thread: uncommitted data writes, in order
    nw,       \* per thread: writes made so far, including rolled-back ones
    sp,       \* per thread: the savepoint, if any
    inv,      \* per thread: parents invalidated by uncommitted writes
    fills,    \* per thread: real ETags it will store instead of its token
    rd,       \* per thread: representations it serialized earlier (FillUnderLock = FALSE)
    pending,  \* per thread: invalidations left for on_commit (InvalidateInTx = FALSE)
    fs,       \* per filler: the fill in progress
    flushed,  \* per thread in BatchedTxs: whether it wrote what it collected
    hist      \* history, for the non-vacuity checks only

vars == <<db, phase, wlog, nw, sp, inv, fills, rd, pending, fs, flushed, hist>>

-----------------------------------------------------------------------------
(* Rows, representations and stored values *)

Members(p, d) == {c \in Children : d.parentOf[c] = p}

Rep(p, d) == [own |-> d.own[p], mem |-> Members(p, d)]

Reps == [own : OwnValues, mem : SUBSET Children]

AnyRep == [own |-> CHOOSE v \in OwnValues : TRUE, mem |-> {}]

\* _etag holds either a real ETag (tok = NoTok) or a token.
Stored == [tok : Txs \cup {NoTok, Bottom}, rep : Reps]

Etag(r) == [tok |-> NoTok, rep |-> r]

Token(t) == [tok |-> IF FreshToken THEN t ELSE Bottom, rep |-> AnyRep]

IsToken(s) == s.tok # NoTok

Data == [parentOf : [Children -> Parents \cup {NoParent}],
         own : [Parents -> OwnValues]]

Rows == [parentOf : [Children -> Parents \cup {NoParent}],
         own : [Parents -> OwnValues],
         etag : [Parents -> Stored]]

Apply(d, w) ==
    CASE w.kind = "fk"    -> [d EXCEPT !.parentOf[w.c] = w.to]
      [] w.kind = "own"   -> [d EXCEPT !.own[w.p] = w.v]
      [] w.kind = "touch" -> d

RECURSIVE ApplyAll(_, _)
ApplyAll(d, ws) ==
    IF ws = <<>> THEN d ELSE ApplyAll(Apply(d, Head(ws)), Tail(ws))

View(t) == ApplyAll(db, wlog[t])

Invalidate(d, ps, t) ==
    [d EXCEPT !.etag = [p \in Parents |-> IF p \in ps THEN Token(t) ELSE d.etag[p]]]

\* Whether the parents thread t invalidates are written, so locked: at once,
\* or for a batched thread once it flushed.
Locks(t) == t \notin BatchedTxs \/ flushed[t]

\* What thread t stores in _etag at commit: its real ETag where it filled
\* one, its token for every other parent it invalidated.  A batched thread
\* that commits unflushed stores nothing (FlushBeforeCommit = FALSE).
FillOf(t, p) == {e \in fills[t] : e.p = p}

CommitEtags(d, t) ==
    [d EXCEPT !.etag =
        [p \in Parents |->
            IF p \notin inv[t] \/ ~Locks(t) THEN d.etag[p]
            ELSE IF FillOf(t, p) # {} THEN Etag((CHOOSE e \in FillOf(t, p) : TRUE).rep)
            ELSE Token(t)]]

Row(w) == IF w.kind = "own" THEN w.p ELSE w.c

\* Rows a writer has locked: those it wrote, and the parents whose _etag it
\* set inside the transaction.
WriterRows(u) ==
    {Row(wlog[u][i]) : i \in 1..Len(wlog[u])}
        \cup (IF InvalidateInTx /\ Locks(u) THEN inv[u] ELSE {})

LockedByWriter(row, except) == \E u \in Txs \ except : row \in WriterRows(u)

-----------------------------------------------------------------------------
(* Writers *)

NoSp == [st |-> "none", w |-> 0, inv |-> {}, fills |-> {}]

Begin(t) ==
    /\ phase[t] = "idle"
    /\ phase' = [phase EXCEPT ![t] = "active"]
    /\ UNCHANGED <<db, wlog, nw, sp, inv, fills, rd, pending, fs, hist, flushed>>

\* A write locks its own row and, inside the transaction, the parents it
\* invalidates.
CanWrite(t, row, ps) ==
    /\ phase[t] = "active"
    /\ nw[t] < MaxWrites
    /\ \A r \in {row} \cup (IF InvalidateInTx /\ Locks(t) THEN ps ELSE {}) :
          ~LockedByWriter(r, {t})

\* Record write w and invalidate the parents in ps: affected(w).  A real
\* ETag the transaction stored for one of them earlier is now stale.
DoWrite(t, w, ps) ==
    LET dropped == {e \in fills[t] : e.p \in ps} IN
    /\ wlog' = [wlog EXCEPT ![t] = Append(@, w)]
    /\ nw' = [nw EXCEPT ![t] = @ + 1]
    /\ inv' = [inv EXCEPT ![t] = @ \cup ps]
    /\ fills' = [fills EXCEPT ![t] = IF DropFillOnWrite THEN @ \ dropped ELSE @]
    /\ hist' = IF dropped # {} THEN [hist EXCEPT !.fillDropped = @ \cup {t}] ELSE hist
    /\ UNCHANGED <<db, phase, sp, rd, pending, fs, flushed>>

Insert(t, c, p) ==
    /\ "insert" \in Ops
    /\ CanWrite(t, c, {p})
    /\ View(t).parentOf[c] = NoParent
    /\ DoWrite(t, [kind |-> "fk", c |-> c, to |-> p], {p})

Delete(t, c) ==
    LET old == View(t).parentOf[c] IN
    /\ "delete" \in Ops
    /\ old # NoParent
    /\ CanWrite(t, c, {old})
    /\ DoWrite(t, [kind |-> "fk", c |-> c, to |-> NoParent], {old})

Move(t, c, p) ==
    LET old == View(t).parentOf[c] IN
    /\ "move" \in Ops
    /\ old \notin {NoParent, p}
    /\ CanWrite(t, c, {old, p})
    /\ DoWrite(t, [kind |-> "fk", c |-> c, to |-> p], {old, p})

Touch(t, c) ==
    /\ "touch" \in Ops
    /\ View(t).parentOf[c] # NoParent
    /\ CanWrite(t, c, {})
    /\ DoWrite(t, [kind |-> "touch", c |-> c], {})

Own(t, p, v) ==
    /\ "own" \in Ops
    /\ View(t).own[p] # v
    /\ CanWrite(t, p, {p})
    /\ DoWrite(t, [kind |-> "own", p |-> p, v |-> v], {p})

\* FillUnderLock = FALSE: the transaction serializes a parent without
\* holding its row lock (the result stays in Python memory).
WriterRead(t, p) ==
    /\ WriterFills
    /\ ~FillUnderLock
    /\ phase[t] = "active"
    /\ rd' = [rd EXCEPT ![t] = {e \in @ : e.p # p} \cup {[p |-> p, rep |-> Rep(p, View(t))]}]
    /\ UNCHANGED <<db, phase, wlog, nw, sp, inv, fills, pending, fs, hist, flushed>>

\* The transaction stores the real ETag of a parent it invalidated, so of a
\* parent whose row lock it holds.  FillUnderLock: it serializes now, after
\* taking the lock.  Otherwise it may use what it serialized before.
WriterFill(t, p) ==
    /\ WriterFills
    /\ InvalidateInTx
    /\ phase[t] = "active"
    /\ p \in inv[t]
    /\ Locks(t)
    /\ \E r \in Reps :
          /\ IF FillUnderLock THEN r = Rep(p, View(t))
                              ELSE [p |-> p, rep |-> r] \in rd[t]
          /\ fills' = [fills EXCEPT ![t] = {e \in @ : e.p # p} \cup {[p |-> p, rep |-> r]}]
    /\ UNCHANGED <<db, phase, wlog, nw, sp, inv, rd, pending, fs, hist, flushed>>

OpenSavepoint(t) ==
    /\ Savepoints
    /\ phase[t] = "active"
    /\ sp[t].st = "none"
    /\ sp' = [sp EXCEPT ![t] = [st |-> "open", w |-> Len(wlog[t]),
                                 inv |-> inv[t], fills |-> fills[t]]]
    /\ UNCHANGED <<db, phase, wlog, nw, inv, fills, rd, pending, fs, hist, flushed>>

\* Postgres undoes the _etag writes made inside the savepoint along with the
\* data; Django drops the on_commit callbacks registered inside it.  What a
\* thread serialized into Python memory stays.
RollbackSavepoint(t) ==
    /\ phase[t] = "active"
    /\ sp[t].st = "open"
    /\ wlog' = [wlog EXCEPT ![t] = SubSeq(@, 1, sp[t].w)]
    /\ inv' = [inv EXCEPT ![t] = IF Locks(t) THEN sp[t].inv ELSE @]
    /\ fills' = [fills EXCEPT ![t] = sp[t].fills]
    /\ sp' = [sp EXCEPT ![t].st = "closed"]
    /\ hist' = IF inv[t] # sp[t].inv THEN [hist EXCEPT !.spUndo = @ \cup {t}] ELSE hist
    /\ UNCHANGED <<db, phase, nw, rd, pending, fs, flushed>>

\* The batch ends: one statement writes the collected tokens, taking the row
\* locks, inside the transaction and outside any savepoint opened in it.
Flush(t) ==
    /\ t \in BatchedTxs
    /\ phase[t] = "active"
    /\ ~flushed[t]
    /\ sp[t].st # "open"
    /\ \A p \in inv[t] : ~LockedByWriter(p, {t})
    /\ flushed' = [flushed EXCEPT ![t] = TRUE]
    /\ hist' = [hist EXCEPT !.flushedInv = @ \/ inv[t] # {}]
    /\ UNCHANGED <<db, phase, wlog, nw, sp, inv, fills, rd, pending, fs>>

ReleaseSavepoint(t) ==
    /\ phase[t] = "active"
    /\ sp[t].st = "open"
    /\ sp' = [sp EXCEPT ![t].st = "closed"]
    /\ UNCHANGED <<db, phase, wlog, nw, inv, fills, rd, pending, fs, hist, flushed>>

\* The data and, inside the transaction, the _etag values become visible
\* together.
Commit(t) ==
    /\ phase[t] = "active"
    /\ sp[t].st # "open"
    /\ FlushBeforeCommit => Locks(t)
    /\ LET d == ApplyAll(db, wlog[t]) IN
       db' = IF InvalidateInTx THEN CommitEtags(d, t) ELSE d
    /\ phase' = [phase EXCEPT ![t] = IF InvalidateInTx THEN "done" ELSE "callbacks"]
    /\ pending' = [pending EXCEPT ![t] = IF InvalidateInTx THEN {} ELSE inv[t]]
    /\ wlog' = [wlog EXCEPT ![t] = <<>>]
    /\ inv' = [inv EXCEPT ![t] = {}]
    /\ fills' = [fills EXCEPT ![t] = {}]
    /\ rd' = [rd EXCEPT ![t] = {}]
    /\ hist' = [hist EXCEPT !.committed = IF wlog[t] # <<>> THEN @ \cup {t} ELSE @,
                            !.writerFilled = @ \/ fills[t] # {}]
    /\ UNCHANGED <<nw, sp, fs, flushed>>

Rollback(t) ==
    /\ phase[t] = "active"
    /\ wlog' = [wlog EXCEPT ![t] = <<>>]
    /\ inv' = [inv EXCEPT ![t] = {}]
    /\ fills' = [fills EXCEPT ![t] = {}]
    /\ rd' = [rd EXCEPT ![t] = {}]
    /\ phase' = [phase EXCEPT ![t] = "done"]
    /\ UNCHANGED <<db, nw, sp, pending, fs, hist, flushed>>

\* InvalidateInTx = FALSE: an on_commit callback writes the token.
InvalidateAfterCommit(t) ==
    /\ phase[t] = "callbacks"
    /\ \E p \in pending[t] :
          /\ ~LockedByWriter(p, {})
          /\ db' = Invalidate(db, {p}, t)
          /\ pending' = [pending EXCEPT ![t] = @ \ {p}]
    /\ UNCHANGED <<phase, wlog, nw, sp, inv, fills, rd, fs, hist, flushed>>

FinishCallbacks(t) ==
    /\ phase[t] = "callbacks"
    /\ pending[t] = {}
    /\ phase' = [phase EXCEPT ![t] = "done"]
    /\ UNCHANGED <<db, wlog, nw, sp, inv, fills, rd, pending, fs, hist, flushed>>

-----------------------------------------------------------------------------
(* Fillers: each statement reads the latest committed rows *)

IdleF == [step |-> "idle", p |-> NoParent, seen |-> Etag(AnyRep),
          own |-> AnyRep.own, mem |-> {}]

\* Load the row: its token and own column come from one statement.
ReadRow(f, p) ==
    /\ TokenFirst
    /\ fs[f].step = "idle"
    /\ IsToken(db.etag[p])
    /\ fs' = [fs EXCEPT ![f] = [step |-> "row", p |-> p, seen |-> db.etag[p],
                                 own |-> db.own[p], mem |-> {}]]
    /\ UNCHANGED <<db, phase, wlog, nw, sp, inv, fills, rd, pending, hist, flushed>>

\* The serializer's query for the hyperlink list.
ReadMembers(f) ==
    /\ fs[f].step = "row"
    /\ fs' = [fs EXCEPT ![f].step = "ready", ![f].mem = Members(fs[f].p, db)]
    /\ UNCHANGED <<db, phase, wlog, nw, sp, inv, fills, rd, pending, hist, flushed>>

\* TokenFirst = FALSE: serialize first, then look at _etag.
ReadData(f, p) ==
    /\ ~TokenFirst
    /\ fs[f].step = "idle"
    /\ fs' = [fs EXCEPT ![f] = [step |-> "data", p |-> p, seen |-> Etag(AnyRep),
                                 own |-> db.own[p], mem |-> Members(p, db)]]
    /\ UNCHANGED <<db, phase, wlog, nw, sp, inv, fills, rd, pending, hist, flushed>>

ReadToken(f) ==
    /\ fs[f].step = "data"
    /\ fs' = [fs EXCEPT ![f] = IF IsToken(db.etag[fs[f].p])
                                THEN [@ EXCEPT !.step = "ready", !.seen = db.etag[fs[f].p]]
                                ELSE IdleF]
    /\ UNCHANGED <<db, phase, wlog, nw, sp, inv, fills, rd, pending, hist, flushed>>

\* UPDATE ... SET _etag = <new> WHERE pk = p AND _etag = <token read>.
\* It waits for writers holding the row, then checks the latest value.
Fill(f) ==
    LET p == fs[f].p
        cur == db.etag[p]
        ok == ~CompareAndSet \/ cur = fs[f].seen
    IN
    /\ fs[f].step = "ready"
    /\ ~LockedByWriter(p, {})
    /\ db' = IF ok THEN [db EXCEPT !.etag[p] = Etag([own |-> fs[f].own, mem |-> fs[f].mem])]
                   ELSE db
    /\ hist' = [hist EXCEPT !.filled = @ \/ ok,
                            !.filledBeforeFlush = @ \/ (ok /\ \E u \in BatchedTxs :
                                phase[u] = "active" /\ ~flushed[u] /\ p \in inv[u]),
                            !.lostToWriter = @ \/ (~ok /\ IsToken(cur)),
                            !.lostToFiller = @ \/ (~ok /\ ~IsToken(cur))]
    /\ fs' = [fs EXCEPT ![f] = IdleF]
    /\ UNCHANGED <<phase, wlog, nw, sp, inv, fills, rd, pending, flushed>>

-----------------------------------------------------------------------------

Init ==
    /\ \E d \in Data : db = [parentOf |-> d.parentOf, own |-> d.own,
                              etag |-> [p \in Parents |-> Etag(Rep(p, d))]]
    /\ phase = [t \in Txs |-> "idle"]
    /\ wlog = [t \in Txs |-> <<>>]
    /\ nw = [t \in Txs |-> 0]
    /\ sp = [t \in Txs |-> NoSp]
    /\ inv = [t \in Txs |-> {}]
    /\ fills = [t \in Txs |-> {}]
    /\ rd = [t \in Txs |-> {}]
    /\ pending = [t \in Txs |-> {}]
    /\ fs = [f \in Fillers |-> IdleF]
    /\ flushed = [t \in Txs |-> FALSE]
    /\ hist = [filled |-> FALSE, filledBeforeFlush |-> FALSE, flushedInv |-> FALSE, lostToWriter |-> FALSE, lostToFiller |-> FALSE,
               writerFilled |-> FALSE, fillDropped |-> {},
               spUndo |-> {}, committed |-> {}]

Next ==
    \/ \E t \in Txs :
          \/ Begin(t) \/ Commit(t) \/ Rollback(t)
          \/ OpenSavepoint(t) \/ RollbackSavepoint(t) \/ ReleaseSavepoint(t)
          \/ \E c \in Children :
                \/ Delete(t, c) \/ Touch(t, c)
                \/ \E p \in Parents : Insert(t, c, p) \/ Move(t, c, p)
          \/ \E p \in Parents, v \in OwnValues : Own(t, p, v)
          \/ \E p \in Parents : WriterRead(t, p) \/ WriterFill(t, p)
          \/ InvalidateAfterCommit(t) \/ FinishCallbacks(t) \/ Flush(t)
    \/ \E f \in Fillers :
          \/ \E p \in Parents : ReadRow(f, p) \/ ReadData(f, p)
          \/ ReadMembers(f) \/ ReadToken(f) \/ Fill(f)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Properties *)

TypeOK ==
    /\ db \in Rows
    /\ phase \in [Txs -> {"idle", "active", "callbacks", "done"}]
    /\ nw \in [Txs -> 0..MaxWrites]
    /\ \A t \in Txs : fills[t] \subseteq [p : Parents, rep : Reps]
    /\ \A f \in Fillers : fs[f].step \in {"idle", "row", "data", "ready"}
    /\ flushed \in [Txs -> BOOLEAN]

\* At every state: a stored ETag is right, or it is a token.
NeverWrong == \A p \in Parents : IsToken(db.etag[p]) \/ db.etag[p].rep = Rep(p, db)

Quiescent ==
    /\ \A t \in Txs : phase[t] \in {"idle", "done"}
    /\ \A f \in Fillers : fs[f].step = "idle"

(* Non-vacuity.  Each NV_ invariant is meant to be violated: the trace TLC *)
(* prints is a witness that the situation it negates is reachable.         *)

\* Writers do invalidate: a token becomes visible.
NV_Token == \A p \in Parents : ~IsToken(db.etag[p])

\* A fill succeeds.
NV_Filled == ~hist.filled

\* A filler computes from data that a writer then changes; the
\* compare-and-set rejects the fill.
NV_LostToWriter == ~hist.lostToWriter

\* Two fillers race on one token; the second fill is rejected.
NV_LostToFiller == ~hist.lostToFiller

\* A savepoint rollback discards an invalidation, in a thread that commits.
NV_SpUndo == ~(hist.spUndo \cap hist.committed # {})

\* A writer commits a real ETag it stored instead of its token.
NV_WriterFilled == ~hist.writerFilled

\* A later write drops a real ETag the writer stored, in a thread that commits.
NV_FillDropped == ~(hist.fillDropped \cap hist.committed # {})

\* A fill succeeds while a batched writer holds the parent's token unwritten;
\* the writer then flushes and commits over it.
NV_FilledBeforeFlush == ~(hist.filledBeforeFlush /\ hist.flushedInv)

\* Every thread commits, every token is filled again, and all work drains.
NV_AllFilled ==
    ~(Quiescent /\ hist.committed = Txs /\ hist.filled
      /\ \A p \in Parents : ~IsToken(db.etag[p]))

\* For runs that only check NeverWrong: states that differ only in hist are
\* the same state.  hist's flags only ever switch on, so keeping them in the
\* fingerprint multiplies the state space for nothing.
NoHist == <<db, phase, wlog, nw, sp, inv, fills, rd, pending, fs, flushed>>

\* Threads are interchangeable unless only some of them batch.
Sym == Permutations(Parents) \cup Permutations(Children)
           \cup (IF BatchedTxs \in {{}, Txs} THEN Permutations(Txs) ELSE {})
           \cup Permutations(Fillers)
=============================================================================
