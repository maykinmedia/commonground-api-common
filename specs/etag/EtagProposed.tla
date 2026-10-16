---------------------------- MODULE EtagProposed ----------------------------
(***************************************************************************)
(* A proposed ETag maintenance protocol, not chosen: recompute after       *)
(* commit under a row lock.  Same world as EtagCurrent: one parent         *)
(* resource whose s_rep is its own column plus the set of child rows       *)
(* pointing at it.                                                         *)
(*                                                                         *)
(* Differences from EtagCurrent, one constant each so every decision can   *)
(* be reverted on its own (all TRUE is the proposal):                      *)
(*   MarkOnDelete    a deleted child marks its parent                      *)
(*   MarkOldParent   a moved child marks its old parent too                *)
(*   SavepointAware  marks made in a rolled-back savepoint are dropped,    *)
(*                   and only those                                        *)
(*   UseLock         a recompute takes the parent's row lock               *)
(*                   (select_for_update) before it reads                   *)
(*   FreshRead       a recompute loads the row by key, not the in-memory   *)
(*                   instance captured at mark time                        *)
(*   CompareWithDb   the early cutoff compares with the _etag read under   *)
(*                   the lock, not with instance._etag                     *)
(* Touching a child (a save that changes nothing the parent reads) marks   *)
(* nothing.  Marks are a set of keys; a thread recomputes them in any      *)
(* order.                                                                  *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    Parents, Children, Txs, OwnValues, NoParent, MaxWrites, Ops, Savepoints,
    EarlyCutoff,
    MarkOnDelete, MarkOldParent, SavepointAware, UseLock, FreshRead,
    CompareWithDb

VARIABLES
    db,        \* committed rows
    stored,    \* committed _etag column
    phase,     \* per thread: "idle", "active", "callbacks" or "done"
    wlog,      \* per thread: uncommitted writes, in order
    nw,        \* per thread: writes made so far, including rolled-back ones
    sp,        \* per thread: the savepoint, if any
    dirty,     \* per thread: marked parents, with what the instance held at the first mark
    flush,     \* per thread: the single flush callback (only SavepointAware = FALSE)
    rc,        \* per thread: the recompute that is running
    hist       \* history, for the non-vacuity checks only

vars == <<db, stored, phase, wlog, nw, sp, dirty, flush, rc, hist>>

-----------------------------------------------------------------------------
(* Rows and representations: as in EtagCurrent *)

Rows == [parentOf : [Children -> Parents \cup {NoParent}],
         own : [Parents -> OwnValues]]

Members(p, d) == {c \in Children : d.parentOf[c] = p}

Rep(p, d) == [own |-> d.own[p], mem |-> Members(p, d)]

Reps == [own : OwnValues, mem : SUBSET Children]

AnyRep == [own |-> CHOOSE v \in OwnValues : TRUE, mem |-> {}]

Apply(d, w) ==
    CASE w.kind = "fk"    -> [d EXCEPT !.parentOf[w.c] = w.to]
      [] w.kind = "own"   -> [d EXCEPT !.own[w.p] = w.v]
      [] w.kind = "touch" -> d

RECURSIVE ApplyAll(_, _)
ApplyAll(d, ws) ==
    IF ws = <<>> THEN d ELSE ApplyAll(Apply(d, Head(ws)), Tail(ws))

View(t) == ApplyAll(db, wlog[t])

Row(w) == IF w.kind = "own" THEN w.p ELSE w.c

LockedByWriter(row, except) ==
    \E u \in Txs \ except : \E i \in 1..Len(wlog[u]) : Row(wlog[u][i]) = row

\* select_for_update in a recompute holds the parent's row until it saves.
LockedByRecompute(row) == UseLock /\ \E u \in Txs : rc[u].busy /\ rc[u].p = row

-----------------------------------------------------------------------------
(* Marking: affected(w) adds keys to the thread's dirty set *)

Marked(ds) == {e.p : e \in ds}

\* The snapshot is what an in-memory instance would hold.  Only the
\* FreshRead = FALSE and CompareWithDb = FALSE variants read it; otherwise
\* it is left blank to keep the state space small.
Snap(p, d) == [p |-> p,
               old |-> IF CompareWithDb THEN AnyRep ELSE stored[p],
               own |-> IF FreshRead THEN AnyRep.own ELSE d.own[p]]

AddMarks(ds, ps, d) == ds \cup {Snap(p, d) : p \in ps \ Marked(ds)}

NoFlush == [reg |-> FALSE, inSp |-> FALSE]

\* Without savepoint awareness: one on_commit flush, registered by the first
\* mark, inside whatever savepoint is open at that moment.
FlushAfter(t, ps) ==
    IF Marked(dirty[t]) = {} /\ ps # {}
    THEN [reg |-> TRUE, inSp |-> sp[t].st = "open"]
    ELSE flush[t]

-----------------------------------------------------------------------------
(* Request transactions *)

NoSp == [st |-> "none", w |-> 0, ds |-> {}]
IdleRc == [busy |-> FALSE, p |-> NoParent, old |-> AnyRep, new |-> AnyRep]

Init ==
    /\ db \in Rows
    /\ stored = [p \in Parents |-> Rep(p, db)]
    /\ phase = [t \in Txs |-> "idle"]
    /\ wlog = [t \in Txs |-> <<>>]
    /\ nw = [t \in Txs |-> 0]
    /\ sp = [t \in Txs |-> NoSp]
    /\ dirty = [t \in Txs |-> {}]
    /\ flush = [t \in Txs |-> NoFlush]
    /\ rc = [t \in Txs |-> IdleRc]
    /\ hist = [staleWrite |-> FALSE, skipped |-> FALSE, moved |-> FALSE,
               spUndo |-> {}, committed |-> {}]

Begin(t) ==
    /\ phase[t] = "idle"
    /\ phase' = [phase EXCEPT ![t] = "active"]
    /\ UNCHANGED <<db, stored, wlog, nw, sp, dirty, flush, rc, hist>>

CanWrite(t, row) ==
    /\ phase[t] = "active"
    /\ nw[t] < MaxWrites
    /\ ~LockedByWriter(row, {t})
    /\ ~LockedByRecompute(row)

\* Record write w and mark the parents in ps.
DoWrite(t, w, ps) ==
    /\ wlog' = [wlog EXCEPT ![t] = Append(@, w)]
    /\ nw' = [nw EXCEPT ![t] = @ + 1]
    /\ dirty' = [dirty EXCEPT ![t] = AddMarks(@, ps, Apply(View(t), w))]
    /\ flush' = IF SavepointAware THEN flush ELSE [flush EXCEPT ![t] = FlushAfter(t, ps)]
    /\ UNCHANGED <<db, stored, phase, sp, rc, hist>>

Insert(t, c, p) ==
    /\ "insert" \in Ops
    /\ CanWrite(t, c)
    /\ View(t).parentOf[c] = NoParent
    /\ DoWrite(t, [kind |-> "fk", c |-> c, from |-> NoParent, to |-> p], {p})

\* Members: the parent the child pointed at loses a member.
Delete(t, c) ==
    LET old == View(t).parentOf[c] IN
    /\ "delete" \in Ops
    /\ CanWrite(t, c)
    /\ old # NoParent
    /\ DoWrite(t, [kind |-> "fk", c |-> c, from |-> old, to |-> NoParent],
               IF MarkOnDelete THEN {old} ELSE {})

\* Members: both the old and the new parent.  The old value is read at write
\* time, under the child's row lock.
Move(t, c, p) ==
    LET old == View(t).parentOf[c] IN
    /\ "move" \in Ops
    /\ CanWrite(t, c)
    /\ old \notin {NoParent, p}
    /\ DoWrite(t, [kind |-> "fk", c |-> c, from |-> old, to |-> p],
               {p} \cup (IF MarkOldParent THEN {old} ELSE {}))

\* No column the parent reads changed: nothing is marked.
Touch(t, c) ==
    /\ "touch" \in Ops
    /\ CanWrite(t, c)
    /\ View(t).parentOf[c] # NoParent
    /\ DoWrite(t, [kind |-> "touch", c |-> c], {})

\* Own: the parent itself.
Own(t, p, v) ==
    /\ "own" \in Ops
    /\ CanWrite(t, p)
    /\ View(t).own[p] # v
    /\ DoWrite(t, [kind |-> "own", p |-> p, v |-> v], {p})

OpenSavepoint(t) ==
    /\ Savepoints
    /\ phase[t] = "active"
    /\ sp[t].st = "none"
    /\ sp' = [sp EXCEPT ![t] = [st |-> "open", w |-> Len(wlog[t]), ds |-> dirty[t]]]
    /\ UNCHANGED <<db, stored, phase, wlog, nw, dirty, flush, rc, hist>>

\* Savepoint aware: the dirty set goes back to what it was at the savepoint.
\* Naive: the dirty set stays, but a flush registered inside the savepoint
\* is dropped by Django.
RollbackSavepoint(t) ==
    /\ phase[t] = "active"
    /\ sp[t].st = "open"
    /\ wlog' = [wlog EXCEPT ![t] = SubSeq(@, 1, sp[t].w)]
    /\ IF SavepointAware
       THEN /\ dirty' = [dirty EXCEPT ![t] = sp[t].ds]
            /\ UNCHANGED flush
       ELSE /\ flush' = [flush EXCEPT ![t] = [reg |-> @.reg /\ ~@.inSp, inSp |-> FALSE]]
            /\ UNCHANGED dirty
    /\ sp' = [sp EXCEPT ![t].st = "closed"]
    /\ hist' = IF dirty[t] # sp[t].ds THEN [hist EXCEPT !.spUndo = @ \cup {t}] ELSE hist
    /\ UNCHANGED <<db, stored, phase, nw, rc>>

ReleaseSavepoint(t) ==
    /\ phase[t] = "active"
    /\ sp[t].st = "open"
    /\ sp' = [sp EXCEPT ![t].st = "closed"]
    /\ flush' = [flush EXCEPT ![t].inSp = FALSE]
    /\ UNCHANGED <<db, stored, phase, wlog, nw, dirty, rc, hist>>

IsMove(w) == w.kind = "fk" /\ w.from # NoParent /\ w.to # NoParent

Commit(t) ==
    /\ phase[t] = "active"
    /\ sp[t].st # "open"
    /\ db' = ApplyAll(db, wlog[t])
    /\ wlog' = [wlog EXCEPT ![t] = <<>>]
    /\ phase' = [phase EXCEPT ![t] = "callbacks"]
    /\ dirty' = [dirty EXCEPT ![t] = IF SavepointAware \/ flush[t].reg THEN @ ELSE {}]
    /\ hist' = [hist EXCEPT
                  !.committed = IF wlog[t] # <<>> THEN @ \cup {t} ELSE @,
                  !.moved = @ \/ \E i \in 1..Len(wlog[t]) : IsMove(wlog[t][i])]
    /\ UNCHANGED <<stored, nw, sp, flush, rc>>

Rollback(t) ==
    /\ phase[t] = "active"
    /\ wlog' = [wlog EXCEPT ![t] = <<>>]
    /\ dirty' = [dirty EXCEPT ![t] = {}]
    /\ flush' = [flush EXCEPT ![t] = NoFlush]
    /\ phase' = [phase EXCEPT ![t] = "done"]
    /\ UNCHANGED <<db, stored, nw, sp, rc, hist>>

-----------------------------------------------------------------------------
(* Recompute, after commit, in a transaction of its own *)

\* Load the row by key (under select_for_update when UseLock), then
\* serialize it and read the stored _etag.
Read(t) ==
    /\ phase[t] = "callbacks"
    /\ ~rc[t].busy
    /\ \E e \in dirty[t] :
          /\ UseLock => ~LockedByWriter(e.p, {}) /\ ~LockedByRecompute(e.p)
          /\ rc' = [rc EXCEPT ![t] =
                      [busy |-> TRUE, p |-> e.p,
                       old |-> IF CompareWithDb THEN stored[e.p] ELSE e.old,
                       new |-> [own |-> IF FreshRead THEN db.own[e.p] ELSE e.own,
                                mem |-> Members(e.p, db)]]]
          /\ dirty' = [dirty EXCEPT ![t] = @ \ {e}]
    /\ UNCHANGED <<db, stored, phase, wlog, nw, sp, flush, hist>>

\* Save only when the ETag changed; the UPDATE needs the row lock.
Save(t) ==
    LET p == rc[t].p
        skip == EarlyCutoff /\ rc[t].new = rc[t].old
    IN
    /\ rc[t].busy
    /\ skip \/ ~LockedByWriter(p, {})
    /\ stored' = IF skip THEN stored ELSE [stored EXCEPT ![p] = rc[t].new]
    /\ hist' = [hist EXCEPT
                  !.skipped = @ \/ skip,
                  !.staleWrite = @ \/ (~skip /\ rc[t].new # Rep(p, db))]
    /\ rc' = [rc EXCEPT ![t] = IdleRc]
    /\ UNCHANGED <<db, phase, wlog, nw, sp, dirty, flush>>

Finish(t) ==
    /\ phase[t] = "callbacks"
    /\ ~rc[t].busy
    /\ dirty[t] = {}
    /\ phase' = [phase EXCEPT ![t] = "done"]
    /\ UNCHANGED <<db, stored, wlog, nw, sp, dirty, flush, rc, hist>>

Next ==
    \E t \in Txs :
        \/ Begin(t) \/ Commit(t) \/ Rollback(t)
        \/ OpenSavepoint(t) \/ RollbackSavepoint(t) \/ ReleaseSavepoint(t)
        \/ \E c \in Children :
              \/ Delete(t, c) \/ Touch(t, c)
              \/ \E p \in Parents : Insert(t, c, p) \/ Move(t, c, p)
        \/ \E p \in Parents, v \in OwnValues : Own(t, p, v)
        \/ Read(t) \/ Save(t) \/ Finish(t)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Properties *)

TypeOK ==
    /\ db \in Rows
    /\ stored \in [Parents -> Reps]
    /\ phase \in [Txs -> {"idle", "active", "callbacks", "done"}]
    /\ nw \in [Txs -> 0..MaxWrites]
    /\ \A t \in Txs : Marked(dirty[t]) \subseteq Parents

Quiescent == \A t \in Txs : phase[t] \in {"idle", "done"}

Consistent == \A p \in Parents : stored[p] = Rep(p, db)

EtagsCorrect == Quiescent => Consistent

(* Non-vacuity.  Each NV_ invariant is meant to be violated: the trace TLC *)
(* prints is a witness that the situation it negates is reachable.         *)

\* Stored ETags do lag behind s_rep: EtagsCorrect is not true at every state.
NV_Lag == Consistent

\* Every thread commits a write and all work drains.
NV_AllCommit == ~(Quiescent /\ hist.committed = Txs)

\* A recompute saves an ETag that a later commit already made stale, and
\* all work still drains (a later recompute repairs it).
NV_StaleWrite == ~(Quiescent /\ hist.staleWrite)

\* The early cutoff skips a save.
NV_Skip == ~(Quiescent /\ hist.skipped)

\* A savepoint rollback discards a mark, in a thread that then commits.
NV_SpUndo == ~(Quiescent /\ hist.spUndo \cap hist.committed # {})

\* A committed move.
NV_Move == ~(Quiescent /\ hist.moved)

Sym == Permutations(Parents) \cup Permutations(Children) \cup Permutations(Txs)
=============================================================================
