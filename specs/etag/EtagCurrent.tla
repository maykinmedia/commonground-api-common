----------------------------- MODULE EtagCurrent -----------------------------
(***************************************************************************)
(* The ETag maintenance protocol of vng_api_common.caching at 78837e0, the *)
(* head of PR #186.  EarlyCutoff = FALSE gives the protocol before it, as  *)
(* on main.                                                                *)
(*                                                                         *)
(* One ETag resource type, the parent (think Zaak).  Its representation    *)
(* s_rep is its own column plus the hyperlink list of child rows pointing  *)
(* at it (think zaakinformatieobjecten).  Children are plain rows whose    *)
(* FK to the parent is on_delete=CASCADE.  The list is a set: we assume    *)
(* it is ordered by pk.                                                    *)
(*                                                                         *)
(* Every request thread runs one READ COMMITTED transaction.  Writes fire  *)
(* Django signals inside it; the receivers call EtagUpdate.mark_affected,  *)
(* which appends a callback to connection.run_on_commit unless one for the *)
(* same model and pk is already there.  After commit the thread runs its   *)
(* callbacks one by one, each in a transaction of its own.                 *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    Parents,      \* parent rows: the ETag resources
    Children,     \* child rows
    Txs,          \* request threads, one transaction each
    OwnValues,    \* values of the parent's own column
    NoParent,     \* parentOf[c] = NoParent: row c does not exist
    MaxWrites,    \* bound on writes per transaction
    Ops,          \* kinds of write allowed: "insert", "delete", "move", "touch", "own"
    Savepoints,   \* TRUE: a transaction may open one savepoint (a nested atomic block)
    EarlyCutoff,  \* TRUE: skip the save when the new ETag equals instance._etag (PR #186)
    SameObject    \* TRUE: a later save of a marked parent goes through the Python
                  \* object captured by the first mark, so that object sees it

VARIABLES
    db,        \* committed rows
    stored,    \* committed _etag column
    phase,     \* per thread: "idle", "active", "callbacks" or "done"
    wlog,      \* per thread: uncommitted writes, in order
    nw,        \* per thread: writes made so far, including rolled-back ones
    sp,        \* per thread: the savepoint, if any
    onCommit,  \* per thread: connection.run_on_commit
    rc         \* per thread: the callback that is running

vars == <<db, stored, phase, wlog, nw, sp, onCommit, rc>>

-----------------------------------------------------------------------------
(* Rows and representations *)

Rows == [parentOf : [Children -> Parents \cup {NoParent}],
         own : [Parents -> OwnValues]]

Members(p, d) == {c \in Children : d.parentOf[c] = p}

\* s_rep(p, d), and the ETag we store for it (a perfect hash).
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

\* What thread t reads: committed rows plus its own writes.
View(t) == ApplyAll(db, wlog[t])

Row(w) == IF w.kind = "own" THEN w.p ELSE w.c

\* Writes lock their row until the transaction ends, or until the savepoint
\* they were made in is rolled back.
LockedByWriter(row, except) ==
    \E u \in Txs \ except : \E i \in 1..Len(wlog[u]) : Row(wlog[u][i]) = row

-----------------------------------------------------------------------------
(* EtagUpdate.mark_affected *)

Pending(cbs, p) == \E i \in 1..Len(cbs) : cbs[i].p = p

\* The marked instance was loaded inside the transaction: it carries the
\* transaction's view of the own column and the committed _etag.  A callback
\* for the same pk already in run_on_commit wins; the new one is dropped.
Mark(cbs, p, d) ==
    IF Pending(cbs, p) THEN cbs
    ELSE Append(cbs, [p |-> p, old |-> stored[p], own |-> d.own[p]])

\* Saving through the captured object mutates it.  Python objects are not
\* restored when a savepoint rolls back.
Refresh(cbs, p, v) ==
    [i \in 1..Len(cbs) |-> IF cbs[i].p = p THEN [cbs[i] EXCEPT !.own = v]
                                           ELSE cbs[i]]

-----------------------------------------------------------------------------
(* Request transactions *)

NoSp == [st |-> "none", w |-> 0, m |-> 0]
IdleRc == [busy |-> FALSE, p |-> NoParent, old |-> AnyRep, new |-> AnyRep]

Init ==
    /\ db \in Rows
    /\ stored = [p \in Parents |-> Rep(p, db)]
    /\ phase = [t \in Txs |-> "idle"]
    /\ wlog = [t \in Txs |-> <<>>]
    /\ nw = [t \in Txs |-> 0]
    /\ sp = [t \in Txs |-> NoSp]
    /\ onCommit = [t \in Txs |-> <<>>]
    /\ rc = [t \in Txs |-> IdleRc]

Begin(t) ==
    /\ phase[t] = "idle"
    /\ phase' = [phase EXCEPT ![t] = "active"]
    /\ UNCHANGED <<db, stored, wlog, nw, sp, onCommit, rc>>

CanWrite(t, row) ==
    /\ phase[t] = "active"
    /\ nw[t] < MaxWrites
    /\ ~LockedByWriter(row, {t})

DoWrite(t, w, cbs) ==
    /\ wlog' = [wlog EXCEPT ![t] = Append(@, w)]
    /\ nw' = [nw EXCEPT ![t] = @ + 1]
    /\ onCommit' = [onCommit EXCEPT ![t] = cbs]
    /\ UNCHANGED <<db, stored, phase, sp, rc>>

\* post_save(child): the registry follows the child's FK, so its parent is marked.
Insert(t, c, p) ==
    LET w == [kind |-> "fk", c |-> c, to |-> p] IN
    /\ "insert" \in Ops
    /\ CanWrite(t, c)
    /\ View(t).parentOf[c] = NoParent
    /\ DoWrite(t, w, Mark(onCommit[t], p, Apply(View(t), w)))

\* post_delete(child): Dependency.get_related_objects returns [] because
\* is_delete and the FK is CASCADE.  Nothing is marked.
Delete(t, c) ==
    LET w == [kind |-> "fk", c |-> c, to |-> NoParent] IN
    /\ "delete" \in Ops
    /\ CanWrite(t, c)
    /\ View(t).parentOf[c] # NoParent
    /\ DoWrite(t, w, onCommit[t])

\* post_save(child) sees only the new FK value: the new parent is marked.
Move(t, c, p) ==
    LET w == [kind |-> "fk", c |-> c, to |-> p] IN
    /\ "move" \in Ops
    /\ CanWrite(t, c)
    /\ View(t).parentOf[c] \notin {NoParent, p}
    /\ DoWrite(t, w, Mark(onCommit[t], p, Apply(View(t), w)))

\* A save that changes nothing the parent reads, like open-zaak#2577's second
\* zio.save().  The parent is marked anyway.
Touch(t, c) ==
    LET w == [kind |-> "touch", c |-> c] IN
    /\ "touch" \in Ops
    /\ CanWrite(t, c)
    /\ View(t).parentOf[c] # NoParent
    /\ DoWrite(t, w, Mark(onCommit[t], View(t).parentOf[c], View(t)))

\* post_save(parent): an ETag model marks itself.
Own(t, p, v) ==
    LET w == [kind |-> "own", p |-> p, v |-> v]
        cbs == Mark(onCommit[t], p, Apply(View(t), w))
    IN
    /\ "own" \in Ops
    /\ CanWrite(t, p)
    /\ View(t).own[p] # v
    /\ DoWrite(t, w, IF SameObject THEN Refresh(cbs, p, v) ELSE cbs)

OpenSavepoint(t) ==
    /\ Savepoints
    /\ phase[t] = "active"
    /\ sp[t].st = "none"
    /\ sp' = [sp EXCEPT ![t] = [st |-> "open", w |-> Len(wlog[t]),
                                 m |-> Len(onCommit[t])]]
    /\ UNCHANGED <<db, stored, phase, wlog, nw, onCommit, rc>>

\* Django drops the on_commit callbacks registered inside the savepoint, and
\* Postgres releases the row locks taken inside it.
RollbackSavepoint(t) ==
    /\ phase[t] = "active"
    /\ sp[t].st = "open"
    /\ wlog' = [wlog EXCEPT ![t] = SubSeq(@, 1, sp[t].w)]
    /\ onCommit' = [onCommit EXCEPT ![t] = SubSeq(@, 1, sp[t].m)]
    /\ sp' = [sp EXCEPT ![t].st = "closed"]
    /\ UNCHANGED <<db, stored, phase, nw, rc>>

ReleaseSavepoint(t) ==
    /\ phase[t] = "active"
    /\ sp[t].st = "open"
    /\ sp' = [sp EXCEPT ![t].st = "closed"]
    /\ UNCHANGED <<db, stored, phase, wlog, nw, onCommit, rc>>

Commit(t) ==
    /\ phase[t] = "active"
    /\ sp[t].st # "open"
    /\ db' = ApplyAll(db, wlog[t])
    /\ wlog' = [wlog EXCEPT ![t] = <<>>]
    /\ phase' = [phase EXCEPT ![t] = "callbacks"]
    /\ UNCHANGED <<stored, nw, sp, onCommit, rc>>

Rollback(t) ==
    /\ phase[t] = "active"
    /\ wlog' = [wlog EXCEPT ![t] = <<>>]
    /\ onCommit' = [onCommit EXCEPT ![t] = <<>>]
    /\ phase' = [phase EXCEPT ![t] = "done"]
    /\ UNCHANGED <<db, stored, nw, sp, rc>>

-----------------------------------------------------------------------------
(* EtagUpdate.calculate_new_value, after commit *)

\* ETagMixin.calculate_etag_value serializes the in-memory instance: own
\* columns come from the object, the hyperlink list from a fresh query.
Compute(t) ==
    /\ phase[t] = "callbacks"
    /\ ~rc[t].busy
    /\ onCommit[t] # <<>>
    /\ LET cb == Head(onCommit[t]) IN
       rc' = [rc EXCEPT ![t] = [busy |-> TRUE, p |-> cb.p, old |-> cb.old,
                                new |-> [own |-> cb.own, mem |-> Members(cb.p, db)]]]
    /\ onCommit' = [onCommit EXCEPT ![t] = Tail(@)]
    /\ UNCHANGED <<db, stored, phase, wlog, nw, sp>>

\* PR #186 compares with instance._etag, the value loaded at mark time.
\* save(update_fields=["_etag"]) waits for writers holding the parent's row.
Save(t) ==
    LET p == rc[t].p
        skip == EarlyCutoff /\ rc[t].new = rc[t].old
    IN
    /\ rc[t].busy
    /\ skip \/ ~LockedByWriter(p, {})
    /\ stored' = IF skip THEN stored ELSE [stored EXCEPT ![p] = rc[t].new]
    /\ rc' = [rc EXCEPT ![t] = IdleRc]
    /\ UNCHANGED <<db, phase, wlog, nw, sp, onCommit>>

Finish(t) ==
    /\ phase[t] = "callbacks"
    /\ ~rc[t].busy
    /\ onCommit[t] = <<>>
    /\ phase' = [phase EXCEPT ![t] = "done"]
    /\ UNCHANGED <<db, stored, wlog, nw, sp, onCommit, rc>>

Next ==
    \E t \in Txs :
        \/ Begin(t) \/ Commit(t) \/ Rollback(t)
        \/ OpenSavepoint(t) \/ RollbackSavepoint(t) \/ ReleaseSavepoint(t)
        \/ \E c \in Children :
              \/ Delete(t, c) \/ Touch(t, c)
              \/ \E p \in Parents : Insert(t, c, p) \/ Move(t, c, p)
        \/ \E p \in Parents, v \in OwnValues : Own(t, p, v)
        \/ Compute(t) \/ Save(t) \/ Finish(t)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Properties *)

TypeOK ==
    /\ db \in Rows
    /\ stored \in [Parents -> Reps]
    /\ phase \in [Txs -> {"idle", "active", "callbacks", "done"}]
    /\ nw \in [Txs -> 0..MaxWrites]

\* No transaction is running and every callback has run.
Quiescent == \A t \in Txs : phase[t] \in {"idle", "done"}

Consistent == \A p \in Parents : stored[p] = Rep(p, db)

\* Once the work has drained, every stored ETag matches s_rep.
EtagsCorrect == Quiescent => Consistent

Sym == Permutations(Parents) \cup Permutations(Children) \cup Permutations(Txs)
=============================================================================
