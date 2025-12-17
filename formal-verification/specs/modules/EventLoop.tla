------------------------------ MODULE EventLoop ------------------------------
(*
 * Formal model of Flowno's EventLoop with AsyncQueue support.
 * EXTENDS EventLoopBasic with queue operations.
 * 
 * Maps to Python:
 *   AsyncQueue.get()  → YieldGet, blocks if empty, wakes when item available
 *   AsyncQueue.put()  → YieldPut, blocks if full, wakes when space available  
 *   AsyncQueue.close() → CloseQueue, wakes all waiters with exception
 *
 * Note: This module requires Value to be defined (set of possible queue values).
 * To run TLC, create a new module that EXTENDS EventLoop and defines Value and
 * MaxQueueSize(q).
 *   
 * Queue model:
 *   - Queues are identified by natural numbers 0..MaxQueueId
 *   - Each queue has: contents (sequence), max size (0 = unbounded), closed flag
 *   - We track actual VALUES so refinements can reason about message flow
 *)
EXTENDS EventLoopBasic, Sequences

CONSTANT MaxQueueId     \* Bounds state space: queues are 0..MaxQueueId
CONSTANT MaxQueueSize(_) \* Max items per queue (for bounded queues)
CONSTANT Value          \* Set of possible values that can be put in queues
CONSTANT NoPut          \* Sentinel for "not waiting to put"

Queues == 0..MaxQueueId

(* ===== ADDITIONAL TASK STATES ===== *)

WaitingGet == "waitingGet"
WaitingPut == "waitingPut"

(* ===== QUEUE VARIABLES ===== *)

VARIABLES
    queueContents,  \* Queue ID -> Seq(Value), actual items in FIFO order
    queueMaxSize,   \* Queue ID -> max size (0 means unbounded)
    queueClosed,    \* Queue ID -> boolean, whether queue is closed
    getWaiters,     \* Queue ID -> set of tasks waiting to get
    putWaiters,     \* Queue ID -> set of tasks waiting to put
    pendingPut      \* Task ID -> Value ∪ {NoPut}, value a blocked putter wants to put

queueVars == <<queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut>>
allVars == <<taskState, joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut>>

(* ===== EXTENDED STATE PREDICATES ===== *)

IsWaitingGet(t) == taskState[t].state = WaitingGet
IsWaitingPut(t) == taskState[t].state = WaitingPut

WaitQueue(t) == taskState[t].queue

IsBlockedExt(t) == 
    \/ taskState[t].state \in {Sleeping, Joining}
    \/ IsWaitingGet(t)
    \/ IsWaitingPut(t)

IsAliveExt(t) == Exists(t) /\ taskState[t].state \notin {Done, Error}

\* Queue predicates
HasSpace(q) == 
    \/ queueMaxSize[q] = 0
    \/ Len(queueContents[q]) < queueMaxSize[q]

HasItems(q) == queueContents[q] # <<>>

IsEmpty(q) == queueContents[q] = <<>>

IsOpen(q) == ~queueClosed[q]

\* Helper: number of items
QueueLen(q) == Len(queueContents[q])

\* Helper: head of queue (only call when HasItems)
QueueHead(q) == Head(queueContents[q])

(* ===== PRECONDITION OPERATORS ===== *)

CanPutImmediate(t, q) ==
    /\ IsRunning(t)
    /\ IsOpen(q)
    /\ HasSpace(q)

CanGetImmediate(t, q) ==
    /\ IsRunning(t)
    /\ IsOpen(q)
    /\ HasItems(q)

(* ===== BRANCH CONDITION OPERATORS ===== *)

HasWaitingGetter(q) == getWaiters[q] # {}
HasWaitingPutter(q) == putWaiters[q] # {}

(* ===== TYPE INVARIANT ===== *)

TypeOKFull ==
    /\ taskState \in [Tasks -> 
        [state: {Nonexistent}] \cup
        [state: {Ready}] \cup
        [state: {Running}] \cup
        [state: {Sleeping}] \cup
        [state: {Joining}, target: Tasks] \cup
        [state: {Done}] \cup
        [state: {Error}] \cup
        [state: {WaitingGet}, queue: Queues] \cup
        [state: {WaitingPut}, queue: Queues]]
    /\ joinWaiters \in [Tasks -> SUBSET Tasks]
    /\ queueContents \in [Queues -> Seq(Value)]
    /\ queueMaxSize \in [Queues -> Nat]
    /\ queueClosed \in [Queues -> BOOLEAN]
    /\ getWaiters \in [Queues -> SUBSET Tasks]
    /\ putWaiters \in [Queues -> SUBSET Tasks]
    /\ pendingPut \in [Tasks -> Value \cup {NoPut}]

(* ===== INITIAL STATE ===== *)

InitExt ==
    /\ Init
    /\ queueContents = [q \in Queues |-> <<>>]
    /\ queueMaxSize = [q \in Queues |-> MaxQueueSize(q)]
    /\ queueClosed = [q \in Queues |-> FALSE]
    /\ getWaiters = [q \in Queues |-> {}]
    /\ putWaiters = [q \in Queues |-> {}]
    /\ pendingPut = [t \in Tasks |-> NoPut]

(* ===== SUB-ACTIONS ===== *)

(*
 * PutDirectToWaiter: Item bypasses queue, goes directly to waiting getter.
 * The getter will see this value as "delivered" when it resumes.
 * We track it in pendingPut[waiter] temporarily (repurposed as "received").
 * 
 * Actually, cleaner: add a "delivered" variable. But let's keep it simple
 * and just document that the refinement should capture the value.
 *)
PutDirectToWaiter(t, q, v, waiter) ==
    /\ getWaiters' = [getWaiters EXCEPT ![q] = @ \ {waiter}]
    /\ taskState' = [taskState EXCEPT 
        ![t] = [state |-> Ready],
        ![waiter] = [state |-> Ready]]
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, putWaiters, pendingPut>>

(*
 * PutIntoQueue: Item goes into queue (no waiting getter).
 *)
PutIntoQueue(t, q, v) ==
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Ready]]
    /\ queueContents' = [queueContents EXCEPT ![q] = Append(@, v)]
    /\ UNCHANGED <<joinWaiters, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut>>

(*
 * GetFromQueueWakePutter: Get head of queue, wake a blocked putter.
 * The putter's pending value enters the queue.
 * Net queue length unchanged (we take head, putter adds their value).
 *)
GetFromQueueWakePutter(t, q, putter) ==
    /\ putWaiters' = [putWaiters EXCEPT ![q] = @ \ {putter}]
    /\ taskState' = [taskState EXCEPT
        ![t] = [state |-> Ready],
        ![putter] = [state |-> Ready]]
    \* Take head, append putter's pending value
    /\ queueContents' = [queueContents EXCEPT ![q] = Append(Tail(@), pendingPut[putter])]
    /\ pendingPut' = [pendingPut EXCEPT ![putter] = NoPut]
    /\ UNCHANGED <<joinWaiters, queueMaxSize, queueClosed, getWaiters>>

(*
 * GetFromQueue: Get head of queue (no waiting putter).
 *)
GetFromQueue(t, q) ==
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Ready]]
    /\ queueContents' = [queueContents EXCEPT ![q] = Tail(@)]
    /\ UNCHANGED <<joinWaiters, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut>>

(* ===== COMPOSITE ACTIONS ===== *)

(*
 * YieldPutImmediate: Put item into queue that has space.
 * If getter waiting: item goes directly to them.
 * Otherwise: item goes into queue.
 *)
YieldPutImmediate(t, q, v) ==
    /\ CanPutImmediate(t, q)
    /\ IF HasWaitingGetter(q)
       THEN \E waiter \in getWaiters[q] : PutDirectToWaiter(t, q, v, waiter)
       ELSE PutIntoQueue(t, q, v)

(*
 * YieldPutBlocks: Queue is full, task blocks waiting for space.
 * We record the pending value so it can be delivered when space opens.
 *)
YieldPutBlocks(t, q, v) ==
    /\ IsRunning(t)
    /\ IsOpen(q)
    /\ ~HasSpace(q)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> WaitingPut, queue |-> q]]
    /\ putWaiters' = [putWaiters EXCEPT ![q] = @ \cup {t}]
    /\ pendingPut' = [pendingPut EXCEPT ![t] = v]
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters>>

(*
 * YieldGetImmediate: Get item from non-empty queue.
 * Refinement should read QueueHead(q) BEFORE calling this to capture the value.
 * If putter waiting: their pending value enters queue.
 * Otherwise: queue shrinks by one.
 *)
YieldGetImmediate(t, q) ==
    /\ CanGetImmediate(t, q)
    /\ IF HasWaitingPutter(q)
       THEN \E putter \in putWaiters[q] : GetFromQueueWakePutter(t, q, putter)
       ELSE GetFromQueue(t, q)

(*
 * YieldGetBlocks: Queue is empty, task blocks waiting for item.
 *)
YieldGetBlocks(t, q) ==
    /\ IsRunning(t)
    /\ IsOpen(q)
    /\ ~HasItems(q)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> WaitingGet, queue |-> q]]
    /\ getWaiters' = [getWaiters EXCEPT ![q] = @ \cup {t}]
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, putWaiters, pendingPut>>

(*
 * YieldGetClosed: Try to get from closed empty queue -> error.
 *)
YieldGetClosed(t, q) ==
    /\ IsRunning(t)
    /\ queueClosed[q]
    /\ ~HasItems(q)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Error]]
    /\ UNCHANGED <<joinWaiters, queueVars>>

(*
 * YieldPutClosed: Try to put into closed queue -> error.
 *)
YieldPutClosed(t, q) ==
    /\ IsRunning(t)
    /\ queueClosed[q]
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Error]]
    /\ UNCHANGED <<joinWaiters, queueVars>>

(*
 * CloseQueue: Close queue, wake all waiters with error.
 * Blocked putters lose their pending values.
 *)
CloseQueue(t, q) ==
    /\ IsRunning(t)
    /\ IsOpen(q)
    /\ queueClosed' = [queueClosed EXCEPT ![q] = TRUE]
    /\ taskState' = [task \in Tasks |->
        IF task = t THEN [state |-> Ready]
        ELSE IF task \in getWaiters[q] THEN [state |-> Error]
        ELSE IF task \in putWaiters[q] THEN [state |-> Error]
        ELSE taskState[task]]
    /\ getWaiters' = [getWaiters EXCEPT ![q] = {}]
    /\ putWaiters' = [putWaiters EXCEPT ![q] = {}]
    \* Clear pending puts for closed waiters
    /\ pendingPut' = [task \in Tasks |->
        IF task \in putWaiters[q] THEN NoPut
        ELSE pendingPut[task]]
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize>>

(* ===== NEXT STATE ===== *)

NextExt ==
    \/ \E t \in Tasks : Schedule(t) /\ UNCHANGED queueVars
    \/ \E t \in Tasks : YieldReady(t) /\ UNCHANGED queueVars
    \/ \E t \in Tasks : YieldSleep(t) /\ UNCHANGED queueVars
    \/ \E t \in Tasks : WakeFromSleep(t) /\ UNCHANGED queueVars
    \/ \E t \in Tasks : Complete(t) /\ UNCHANGED queueVars
    \/ \E t \in Tasks : Fail(t) /\ UNCHANGED queueVars
    \/ \E t, target \in Tasks : YieldJoin(t, target) /\ UNCHANGED queueVars
    \/ \E t, target \in Tasks : JoinComplete(t, target) /\ UNCHANGED queueVars
    \/ \E t, target \in Tasks : JoinAlreadyDone(t, target) /\ UNCHANGED queueVars
    \/ \E t, newTask \in Tasks : Spawn(t, newTask) /\ UNCHANGED queueVars
    \/ \E t \in Tasks, q \in Queues, v \in Value : YieldPutImmediate(t, q, v)
    \/ \E t \in Tasks, q \in Queues, v \in Value : YieldPutBlocks(t, q, v)
    \/ \E t \in Tasks, q \in Queues : YieldGetImmediate(t, q)
    \/ \E t \in Tasks, q \in Queues : YieldGetBlocks(t, q)
    \/ \E t \in Tasks, q \in Queues : YieldGetClosed(t, q)
    \/ \E t \in Tasks, q \in Queues : YieldPutClosed(t, q)
    \/ \E t \in Tasks, q \in Queues : CloseQueue(t, q)

SpecExt == InitExt /\ [][NextExt]_allVars

(* ===== INVARIANTS ===== *)

GetWaitersConsistent ==
    \A q \in Queues : HasItems(q) => getWaiters[q] = {}

PutWaitersConsistent ==
    \A q \in Queues : HasSpace(q) => putWaiters[q] = {}

WaiterStateConsistent ==
    /\ \A q \in Queues : \A t \in getWaiters[q] : 
        IsWaitingGet(t) /\ WaitQueue(t) = q
    /\ \A q \in Queues : \A t \in putWaiters[q] : 
        IsWaitingPut(t) /\ WaitQueue(t) = q

PendingPutConsistent ==
    \A t \in Tasks :
        (IsWaitingPut(t) => pendingPut[t] # NoPut) /\
        (~IsWaitingPut(t) => pendingPut[t] = NoPut)

ClosedQueueNoWaiters ==
    \A q \in Queues : queueClosed[q] => 
        (getWaiters[q] = {} /\ putWaiters[q] = {})

=============================================================================