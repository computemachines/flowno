-------------------- MODULE EventLoopExample --------------------
(*
 * PURPOSE: EventLoop "kitchen sink" example spec.
 *
 * Demonstrates one-to-one modeling of flowno's synchronization primitives
 * (Event, Lock, Condition, AsyncQueue) using the same semantics as the Python event loop.
 *
 * PYTHON CODE:
 *
 * async def main():
 *     t1 = spawn(worker(latch))
 *     t2 = spawn(worker(latch))
 *     t3 = spawn(condition_waiter(lock, cond))
 *     t4 = spawn(condition_notifier(lock, cond))
 *     await t1.join()
 *     await t2.join()
 *     await sleep(1.0)
 *     await latch.wait()
 *     t5 = spawn(producer(queue))
 *     t6 = spawn(consumer(queue))
 *     await t5.join()
 *     await t6.join()
 *
 * async def worker(latch: CountdownLatch):
 *     await sleep(1.0)
 *     async with latch:
 *         await latch.count_down()
 *
 * async def condition_waiter(lock: Lock, cond: Condition):
 *     async with lock:
 *         while not flag:
 *             await cond.wait()
 *
 * async def condition_notifier(lock: Lock, cond: Condition):
 *     await sleep(1.0)
 *     async with lock:
 *         flag = True
 *         await cond.notify()
 *
 * async def producer(queue: AsyncQueue):
 *     await queue.put("item1")
 *     await queue.put("item2")
 *     await queue.close()
 *
 * async def consumer(queue: AsyncQueue):
 *     item1 = await queue.get()
 *     item2 = await queue.get()
 *)

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS 
    NoTask,
    NoLock,
    NoEvent

Tasks == {
    0,    \* main task
    1, 2, \* latch workers
    3,    \* condition waiter
    4,    \* condition notifier
    5,    \* producer
    6     \* consumer
}
Events == {
    0  \* latch 0 uses event 0
}
Locks == {
    0, \* latch 0 uses lock 0
    1, \* condition 0 uses lock 1 (not shared)
    2  \* queue 0 shares lock 2 with conditions 1 and 2
}
Conditions == {
    0, \* standalone condition 0
    1, \* queue 0's _not_empty condition
    2  \* queue 0's _not_full condition
}
Queues == {
    0
}
Latches == {
    0
}

\* Object graph using nested records to mirror Python attribute access.
\* Python: latch._lock, queue._not_empty._lock
\* TLA+:   Latch[l].lock.id, Queue[q].not_empty.lock.id
\*
\* Key insight: Lock 2 is SHARED - it appears in Queue[0].lock.id,
\* Queue[0].not_empty.lock.id, Queue[0].not_full.lock.id, and
\* Condition[1].lock.id and Condition[2].lock.id (intentional duplication).

Condition ==
    [c \in Conditions |-> CASE c = 0 -> [lock |-> [id |-> 1]]
                               [] c = 1 -> [lock |-> [id |-> 2]]  \* _not_empty shares queue's lock
                               [] c = 2 -> [lock |-> [id |-> 2]]  \* _not_full shares queue's lock
                               [] OTHER -> [lock |-> [id |-> NoLock]]]

Latch ==
    [l \in Latches |-> CASE l = 0 -> [lock |-> [id |-> 0], event |-> [id |-> 0]]
                            [] OTHER -> [lock |-> [id |-> NoLock], event |-> [id |-> NoEvent]]]

Queue ==
    [q \in Queues |-> CASE q = 0 -> [
                                lock |-> [id |-> 2],
                                not_empty |-> [
                                    id |-> 1,
                                    lock |-> [id |-> 2]
                                ],
                                not_full |-> [
                                    id |-> 2,
                                    lock |-> [id |-> 2]
                                ]
                            ]
                           [] OTHER -> [
                                lock |-> [id |-> NoLock],
                                not_empty |-> [id |-> -1, lock |-> [id |-> NoLock]],
                                not_full |-> [id |-> -1, lock |-> [id |-> NoLock]]
                            ]]

\* Queue configuration: maxsize for each queue (NoTask represents None/unbounded)
QueueMaxSize == [q \in Queues |-> CASE q = 0 -> 2  \* bounded queue with maxsize=2
                                       [] OTHER -> 0]


\* -- Basic task state options --
\* Only states the event loop can actually observe
Ready == "Ready"
ReadyResuming == "ReadyResuming"
Running == "Running"
NonExistent == "NonExistent"
Sleeping == "Sleeping"
WaitingLock == "WaitingLock"
WaitingEvent == "WaitingEvent"
WaitingCondition == "WaitingCondition"
WaitingJoin == "WaitingJoin"
Done == "Done"

(* --algorithm EventLoopExample {
variables
\* === Core event loop state ===
runningTask = NoTask,
taskState = [t \in Tasks |->
    IF t = 0
    THEN [state |-> Ready]
    ELSE [state |-> NonExistent]
],

\* === CountdownLatch state (Event + Lock) ===
latchCount = [latch \in Latches |-> 2],
lock = [latch \in Locks |-> NoTask],
\* Python semantics: FIFO wait queue (event loop uses deque).
lockWaiters = [latch \in Locks |-> << >>],
eventFired = [latch \in Events |-> FALSE],
eventWaiters = [latch \in Events |-> {}],

\* === Condition state (ConditionWaitCommand / ConditionNotifyCommand) ===
\* conditionWaiters[cond] is a set (Python: self.condition_waiters[cond] is a set)
conditionWaiters = [c \in Conditions |-> {}],
conditionFlag = [c \in Conditions |-> FALSE],

\* === AsyncQueue state ===
\* queueItems[q] is a sequence representing the queue contents
queueItems = [q \in Queues |-> << >>],
\* queueClosed[q] tracks if queue q is closed
queueClosed = [q \in Queues |-> FALSE],

\* === Join state (JoinCommand / watching_task) ===
\* joinWaiters[t] is the set of tasks waiting for task t to complete
joinWaiters = [t \in Tasks |-> {}],

\* === Tracking ===
workersCompleted = 0,
itemsProduced = 0,
itemsConsumed = 0,
lastAction = <<"Init">>;

define {
IsReady(t) == taskState[t].state = Ready
IsWaitingJoin(t) == taskState[t].state = WaitingJoin
IsRunning(t) == taskState[t].state = Running
IsWaitingLock(t) == taskState[t].state = WaitingLock
IsWaitingEvent(t) == taskState[t].state = WaitingEvent
IsWaitingCondition(t) == taskState[t].state = WaitingCondition
IsSleeping(t) == taskState[t].state = Sleeping
IsDone(t) == taskState[t].state = Done

IsSchedulable(t) == IsReady(t)

\* === Queue helper functions ===
QueueLen(q) == Len(queueItems[q])
QueueIsFull(q) == QueueMaxSize[q] # NoTask /\ QueueLen(q) >= QueueMaxSize[q]
QueueIsEmpty(q) == QueueLen(q) = 0

\* === Invariants ===
AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1
LatchCountNonNegative == \A l \in Latches : latchCount[l] >= 0
LatchLockMutex == \A l \in Locks : Cardinality({t \in Tasks : lock[l] = t}) <= 1
EventSetWhenZero == \A l \in Latches : (latchCount[l] = 0) => eventFired[Latch[l].event.id]
MainWaitsUntilZero == IsWaitingEvent(0) => latchCount[0] > 0
QueueBoundsRespected == \A q \in Queues : QueueMaxSize[q] # NoTask => QueueLen(q) <= QueueMaxSize[q]
EventuallyAllDone == <>(taskState = [t \in Tasks |-> [state |-> Done]])
Eventually2WorkersDone == <>(workersCompleted = 2)
Eventually2ItemsProduced == <>(itemsProduced = 2)
Eventually2ItemsConsumed == <>(itemsConsumed = 2)
}

\* === Yield macros ===

macro yield_spawn(t) {
taskState := [taskState EXCEPT ![t]    = [state |-> Ready], 
                                ![self] = [state |-> Ready]];
runningTask := NoTask;
lastAction := <<"Spawn", t, self>>;
}

macro yield_sleep() {
taskState[self] := [state |-> Sleeping];
runningTask := NoTask;
lastAction := <<"Sleep", self>>;
}

macro yield_complete() {
\* Wake all tasks waiting to join this task
taskState := [t \in Tasks |->
    CASE t = self                -> [state |-> Done]
        [] t \in joinWaiters[self] -> [state |-> Ready]
        [] OTHER                   -> taskState[t]
];
joinWaiters[self] := {};
runningTask := NoTask;
lastAction := <<"Complete", self>>;
}

macro yield_join(t) {
\* Wait for task t to complete (matches JoinCommand)
if (IsDone(t)) {
    \* Task already done, return immediately
    taskState[self] := [state |-> Ready];
    runningTask := NoTask;
    lastAction := <<"Join", "Immediate", t, self>>;
} else {
    \* Task not done, wait for it
    taskState[self] := [state |-> WaitingJoin];
    joinWaiters[t] := joinWaiters[t] \union {self};
    runningTask := NoTask;
    lastAction := <<"Join", "Waiting", t, self>>;
}
}

\* === Lock operations ===

macro yield_acquire_lock(l) {
if (lock[l] = NoTask) {
    lock[l] := self;
    taskState[self] := [state |-> Ready];
    runningTask := NoTask;
    lastAction := <<"AcquireLock", "Immediate", l, self>>;
} else {
    taskState[self] := [state |-> WaitingLock];
    \* FIFO enqueue (matches event loop: lock_waiters[lock].append(task)).
    lockWaiters[l] := Append(lockWaiters[l], self);
    runningTask := NoTask;
    lastAction := <<"AcquireLock", "Waiting", l, self>>;
}
}

macro yield_release_lock(l) {
\* Python semantics: only owner may release.
assert lock[l] = self;

if (lockWaiters[l] = << >>) {
    \* No waiters -> unlock.
    lock[l] := NoTask;
    taskState[self] := [state |-> Ready];
    runningTask := NoTask;
    lastAction := <<"ReleaseLock", l, self>>;
} else {
    \* Waiters -> transfer ownership to FIFO head, wake it.
    with (nextOwner = Head(lockWaiters[l])) {
        lock[l] := nextOwner;
        lockWaiters[l] := Tail(lockWaiters[l]);
        taskState := [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                        ![self] = [state |-> Ready]];
        runningTask := NoTask;
        lastAction := <<"ReleaseLock", l, self>>;
    }
}
}

\* === Event operations ===

macro yield_event_wait(e) {
taskState[self] := [state |-> IF eventFired[e] THEN Ready ELSE WaitingEvent];
eventWaiters[e] := IF eventFired[e] THEN eventWaiters[e] ELSE eventWaiters[e] \union {self};
runningTask := NoTask;
lastAction := <<"EventWait", e, self>>;
}

macro yield_event_set(e) {
taskState := LET wasFired == eventFired[e] IN
    IF ~wasFired THEN
        [t \in Tasks |->
            IF t \in eventWaiters[e] THEN [state |-> Ready]
            ELSE IF t = self THEN [state |-> Ready]
            ELSE taskState[t]]
    ELSE
        [taskState EXCEPT ![self] = [state |-> Ready]];
eventWaiters[e] := LET wasFired == eventFired[e] IN IF ~wasFired THEN {} ELSE eventWaiters[e];
eventFired[e] := TRUE;
runningTask := NoTask;
lastAction := <<"EventSet", e, self>>;
}

\* === Condition operations ===

macro yield_condition_wait(c) {
    \* Matches event_loop.py ConditionWaitCommand:
    \* - assert caller owns lock
    \* - atomically: add to condition waiters, release lock  
    \* - if lock had waiters, wake next waiter and transfer ownership

    \* TODO: mimic the actual python implementation more closely and call the release_lock macro?

    assert lock[Condition[c].lock.id] = self;

    \* Capture values before any modifications
    with (hasWaiters = lockWaiters[Condition[c].lock.id] # << >>,
            nextOwner = IF lockWaiters[Condition[c].lock.id] # << >>
                        THEN Head(lockWaiters[Condition[c].lock.id])
                        ELSE NoTask) {
                        
        conditionWaiters[c] := conditionWaiters[c] \union {self};
        lock[Condition[c].lock.id] := nextOwner;
        lockWaiters[Condition[c].lock.id] := IF hasWaiters
                                                THEN Tail(lockWaiters[Condition[c].lock.id])
                                                ELSE << >>;
        taskState := IF hasWaiters
                        THEN [taskState EXCEPT ![self] = [state |-> WaitingCondition],
                                                ![nextOwner] = [state |-> Ready]]
                        ELSE [taskState EXCEPT ![self] = [state |-> WaitingCondition]];
        runningTask := NoTask;
        lastAction := <<"ConditionWait", c, self>>;
    };
}

macro yield_condition_notify(c) {
    \* Matches event_loop.py ConditionNotifyCommand(all=False):
    \* - assert caller owns lock
    \* - pop one arbitrary waiter from condition set
        \* - append it to lock's FIFO waiter queue
    assert lock[Condition[c].lock.id] = self;

    \* Capture values before modifications
    with (hasWaiters = conditionWaiters[c] # {},
            waiter = IF conditionWaiters[c] # {}
                    THEN CHOOSE t \in conditionWaiters[c] : TRUE
                    ELSE NoTask) {
                    
        conditionWaiters[c] := IF hasWaiters
                                THEN conditionWaiters[c] \ {waiter}
                                ELSE conditionWaiters[c];
        lockWaiters[Condition[c].lock.id] := IF hasWaiters
                                                THEN Append(lockWaiters[Condition[c].lock.id], waiter)
                                                ELSE lockWaiters[Condition[c].lock.id];
        taskState := IF hasWaiters
                        THEN [taskState EXCEPT ![waiter] = [state |-> WaitingLock],
                                                ![self] = [state |-> Ready]]
                        ELSE [taskState EXCEPT ![self] = [state |-> Ready]];
        runningTask := NoTask;
        lastAction := <<"ConditionNotify", c, self>>;
    };
}

macro yield_latch_countdown(l) {
    latchCount[l]                   := latchCount[l] - 1;
    eventFired[Latch[l].event.id] := IF   latchCount[l] = 0
                                       THEN TRUE
                                       ELSE eventFired[Latch[l].event.id];
    taskState := IF   latchCount[l] = 0
                 THEN [t \in Tasks |->
                    IF   (t = self) \/ (t \in eventWaiters[Latch[l].event.id])
                    THEN [state |-> Ready]
                    ELSE taskState[t]]
                 ELSE [taskState EXCEPT ![self] = [state |-> Ready]];
    eventWaiters[Latch[l].event.id] := IF   latchCount[l] = 0
                                         THEN {}
                                         ELSE eventWaiters[Latch[l].event.id];
    runningTask := NoTask;
    lastAction  := <<"LatchCountdown", l, self>>;
}

\* === Procedures ===
\* Note: AsyncQueue operations (put, get, close) are implemented as procedures below,
\* not macros, because they need while loops with label breakpoints for proper
\* event loop scheduling. They compose Lock and Condition primitives.

procedure latch_countdown(latch_id)
{
lcd_acquire:  \* await latch.__aenter__()
await runningTask = self;
        yield_acquire_lock(Latch[latch_id].lock.id);

lcd_atomic:  \* await latch.count_down()
await runningTask = self;
yield_latch_countdown(latch_id);

lcd_release:  \* await latch.__aexit__()
await runningTask = self;
        yield_release_lock(Latch[latch_id].lock.id);

lcd_return:
return;
}

\* === Queue procedures ===
\* Python: await queue.put(item)
procedure queue_put(queue_id, item_to_put)
variable item_put_done = FALSE;
{
qput_acquire:  \* await queue._lock.__aenter__()
    await runningTask = self;
    yield_acquire_lock(Queue[queue_id].lock.id);

qput_wait_loop:  \* while maxsize and len(items) >= maxsize: await _not_full.wait()
    await runningTask = self;
    if (QueueIsFull(queue_id) /\ ~queueClosed[queue_id]) {
        \* Queue is full, wait on _not_full condition
        yield_condition_wait(Queue[queue_id].not_full.id);
        goto qput_wait_loop;  \* Loop back after being woken
    } else if (queueClosed[queue_id]) {
        \* Queue closed while waiting
        item_put_done := TRUE;  \* Error case
        goto qput_release;
    } else {
        \* Queue has space, proceed to put
        goto qput_do_put;
    };

qput_do_put:  \* items.append(item); await _not_empty.notify()
    await runningTask = self;
    queueItems[queue_id] := Append(queueItems[queue_id], item_to_put);
    yield_condition_notify(Queue[queue_id].not_empty.id);

qput_release:  \* await queue._lock.__aexit__()
    await runningTask = self;
    yield_release_lock(Queue[queue_id].lock.id);

qput_return:
    return;
}

\* Python: item = await queue.get()
procedure queue_get(queue_id)
variable item_got = NoTask;
{
qget_acquire:  \* await queue._lock.__aenter__()
    await runningTask = self;
    yield_acquire_lock(Queue[queue_id].lock.id);

qget_wait_loop:  \* while not items: await _not_empty.wait()
    await runningTask = self;
    if (QueueIsEmpty(queue_id) /\ ~queueClosed[queue_id]) {
        \* Queue is empty, wait on _not_empty condition
        yield_condition_wait(Queue[queue_id].not_empty.id);
        goto qget_wait_loop;  \* Loop back after being woken
    } else if (queueClosed[queue_id] /\ QueueIsEmpty(queue_id)) {
        \* Queue closed and empty
        item_got := NoTask;  \* Error case
        goto qget_release;
    } else {
        \* Queue has items, proceed to get
        goto qget_do_get;
    };

qget_do_get:  \* item = items.popleft(); await _not_full.notify()
    await runningTask = self;
    item_got := Head(queueItems[queue_id]);
    queueItems[queue_id] := Tail(queueItems[queue_id]);
    yield_condition_notify(Queue[queue_id].not_full.id);

qget_release:  \* await queue._lock.__aexit__()
    await runningTask = self;
    yield_release_lock(Queue[queue_id].lock.id);

qget_return:
    return;
}

\* Python: await queue.close()
procedure queue_close(queue_id)
{
qclose_acquire:  \* await queue._lock.__aenter__()
    await runningTask = self;
    yield_acquire_lock(Queue[queue_id].lock.id);

qclose_do_close:  \* closed = True; await _not_empty.notify_all(); await _not_full.notify_all()
    await runningTask = self;
    queueClosed[queue_id] := TRUE;
    taskState[self] := [state |-> Ready];
    runningTask := NoTask;
    lastAction := <<"QueueClose", queue_id, self>>;

qclose_release:  \* await queue._lock.__aexit__()
    await runningTask = self;
    yield_release_lock(Queue[queue_id].lock.id);

qclose_return:
    return;
}

\* === Scheduler ===
fair process (Scheduler = 99)
{
sched:
while (TRUE) {
    await runningTask = NoTask /\ \E t \in Tasks : IsSchedulable(t);
    with (t \in {t \in Tasks : IsSchedulable(t)}) {
        runningTask := t;
        taskState[t] := [state |-> Running];
        lastAction := <<"Scheduler", "pick", t>>;
    }
}
}

\* === External Wake ===
fair process (ExternalWake = 97)
{
wake:
while (TRUE) {
    await \E t \in Tasks : IsSleeping(t);
    with (t \in {u \in Tasks : IsSleeping(u)}) {
        taskState[t] := [state |-> Ready];
        lastAction := <<"ExternalWake", t>>;
    }
}
}

\* === Main task ===
fair process (Main \in {0})
{
main_spawn1:  \* t1 = spawn(worker(latch))
    await runningTask = self;
    yield_spawn(1);

main_spawn2:  \* t2 = spawn(worker(latch))
    await runningTask = self;
    yield_spawn(2);

main_spawn3:  \* t3 = spawn(condition_waiter(lock, cond))
    await runningTask = self;
    yield_spawn(3);

main_spawn4:  \* t4 = spawn(condition_notifier(lock, cond))
    await runningTask = self;
    yield_spawn(4);

main_join1:  \* await t1.join()
    await runningTask = self;
    yield_join(1);

main_join2:  \* await t2.join()
    await runningTask = self;
    yield_join(2);

main_sleep:  \* await sleep(1.0)
    await runningTask = self;
    yield_sleep();

main_wait:  \* await latch.wait()
    await runningTask = self;
    yield_event_wait(0);

main_spawn5:  \* t5 = spawn(producer(queue))
    await runningTask = self;
    yield_spawn(5);

main_spawn6:  \* t6 = spawn(consumer(queue))
    await runningTask = self;
    yield_spawn(6);

main_join5:  \* await t5.join()
    await runningTask = self;
    yield_join(5);

main_join6:  \* await t6.join()
    await runningTask = self;
    yield_join(6);

main_done:  \* (implicit task completion)
    await runningTask = self;
    yield_complete();
}

\* === Worker tasks (both have same behavior) ===
fair process (Worker \in {1, 2})
{
worker_sleep:  \* await sleep(1.0)
    await runningTask = self;
    yield_sleep();

worker_countdown:  \* async with latch: await latch.count_down()
    await runningTask = self;
    call latch_countdown(0);

worker_done:  \* (implicit task completion)
    await runningTask = self;
    workersCompleted := workersCompleted + 1;
    yield_complete();
}

\* === Condition waiter ===
fair process (ConditionWaiter \in {3})
{
cw_acquire:  \* await lock.__aenter__()
    await runningTask = self;
    yield_acquire_lock(Condition[0].lock.id);

cw_check:  \* while not flag:
    while (~conditionFlag[0]) {
        await runningTask = self;  \* await cond.wait()
        yield_condition_wait(0);
    cw_loop:  \* (loop back to check condition after reacquiring lock)
        await runningTask = self;
    };

cw_release:  \* await lock.__aexit__()
    await runningTask = self;
    yield_release_lock(Condition[0].lock.id);

cw_done:  \* (implicit task completion)
    await runningTask = self;
    yield_complete();
}

\* === Condition notifier ===
fair process (ConditionNotifier \in {4})
{
cn_sleep:  \* await sleep(1.0)
    await runningTask = self;
    yield_sleep();

cn_acquire:  \* await lock.__aenter__()
    await runningTask = self;
    yield_acquire_lock(Condition[0].lock.id);

cn_set_and_notify:  \* flag = True; await cond.notify()
    await runningTask = self;
    conditionFlag[0] := TRUE;
    yield_condition_notify(0);

cn_release:  \* await lock.__aexit__()
    await runningTask = self;
    yield_release_lock(Condition[0].lock.id);

cn_done:  \* (implicit task completion)
    await runningTask = self;
    yield_complete();
}

\* === Producer ===
fair process (Producer \in {5})
{
prod_put1:  \* await queue.put("item1")
    await runningTask = self;
    itemsProduced := itemsProduced + 1;
    call queue_put(0, "item1");

prod_put2:  \* await queue.put("item2")
    await runningTask = self;
    itemsProduced := itemsProduced + 1;
    call queue_put(0, "item2");

prod_close:  \* await queue.close()
    await runningTask = self;
    call queue_close(0);

prod_done:  \* (implicit task completion)
    await runningTask = self;
    yield_complete();
}

\* === Consumer ===
fair process (Consumer \in {6})
{
cons_get1:  \* item1 = await queue.get()
    await runningTask = self;
    call queue_get(0);

cons_get2:  \* item2 = await queue.get()
    await runningTask = self;
    itemsConsumed := itemsConsumed + 1;
    call queue_get(0);

cons_done:  \* (implicit task completion)
    await runningTask = self;
    itemsConsumed := itemsConsumed + 1;
    yield_complete();
}

} *)
\* BEGIN TRANSLATION (chksum(pcal) = "7a53c97b" /\ chksum(tla) = "6a071c8b")
\* Parameter queue_id of procedure queue_put at line 418 col 21 changed to queue_id_
\* Parameter queue_id of procedure queue_get at line 454 col 21 changed to queue_id_q
CONSTANT defaultInitValue
VARIABLES runningTask, taskState, latchCount, lock, lockWaiters, eventFired, 
          eventWaiters, conditionWaiters, conditionFlag, queueItems, 
          queueClosed, joinWaiters, workersCompleted, itemsProduced, 
          itemsConsumed, lastAction, pc, stack

(* define statement *)
IsReady(t) == taskState[t].state = Ready
IsWaitingJoin(t) == taskState[t].state = WaitingJoin
IsRunning(t) == taskState[t].state = Running
IsWaitingLock(t) == taskState[t].state = WaitingLock
IsWaitingEvent(t) == taskState[t].state = WaitingEvent
IsWaitingCondition(t) == taskState[t].state = WaitingCondition
IsSleeping(t) == taskState[t].state = Sleeping
IsDone(t) == taskState[t].state = Done

IsSchedulable(t) == IsReady(t)


QueueLen(q) == Len(queueItems[q])
QueueIsFull(q) == QueueMaxSize[q] # NoTask /\ QueueLen(q) >= QueueMaxSize[q]
QueueIsEmpty(q) == QueueLen(q) = 0


AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1
LatchCountNonNegative == \A l \in Latches : latchCount[l] >= 0
LatchLockMutex == \A l \in Locks : Cardinality({t \in Tasks : lock[l] = t}) <= 1
EventSetWhenZero == \A l \in Latches : (latchCount[l] = 0) => eventFired[Latch[l].event.id]
MainWaitsUntilZero == IsWaitingEvent(0) => latchCount[0] > 0
QueueBoundsRespected == \A q \in Queues : QueueMaxSize[q] # NoTask => QueueLen(q) <= QueueMaxSize[q]
EventuallyAllDone == <>(taskState = [t \in Tasks |-> [state |-> Done]])
Eventually2WorkersDone == <>(workersCompleted = 2)
Eventually2ItemsProduced == <>(itemsProduced = 2)
Eventually2ItemsConsumed == <>(itemsConsumed = 2)

VARIABLES latch_id, queue_id_, item_to_put, item_put_done, queue_id_q, 
          item_got, queue_id

vars == << runningTask, taskState, latchCount, lock, lockWaiters, eventFired, 
           eventWaiters, conditionWaiters, conditionFlag, queueItems, 
           queueClosed, joinWaiters, workersCompleted, itemsProduced, 
           itemsConsumed, lastAction, pc, stack, latch_id, queue_id_, 
           item_to_put, item_put_done, queue_id_q, item_got, queue_id >>

ProcSet == {99} \cup {97} \cup ({0}) \cup ({1, 2}) \cup ({3}) \cup ({4}) \cup ({5}) \cup ({6})

Init == (* Global variables *)
        /\ runningTask = NoTask
        /\ taskState =             [t \in Tasks |->
                           IF t = 0
                           THEN [state |-> Ready]
                           ELSE [state |-> NonExistent]
                       ]
        /\ latchCount = [latch \in Latches |-> 2]
        /\ lock = [latch \in Locks |-> NoTask]
        /\ lockWaiters = [latch \in Locks |-> << >>]
        /\ eventFired = [latch \in Events |-> FALSE]
        /\ eventWaiters = [latch \in Events |-> {}]
        /\ conditionWaiters = [c \in Conditions |-> {}]
        /\ conditionFlag = [c \in Conditions |-> FALSE]
        /\ queueItems = [q \in Queues |-> << >>]
        /\ queueClosed = [q \in Queues |-> FALSE]
        /\ joinWaiters = [t \in Tasks |-> {}]
        /\ workersCompleted = 0
        /\ itemsProduced = 0
        /\ itemsConsumed = 0
        /\ lastAction = <<"Init">>
        (* Procedure latch_countdown *)
        /\ latch_id = [ self \in ProcSet |-> defaultInitValue]
        (* Procedure queue_put *)
        /\ queue_id_ = [ self \in ProcSet |-> defaultInitValue]
        /\ item_to_put = [ self \in ProcSet |-> defaultInitValue]
        /\ item_put_done = [ self \in ProcSet |-> FALSE]
        (* Procedure queue_get *)
        /\ queue_id_q = [ self \in ProcSet |-> defaultInitValue]
        /\ item_got = [ self \in ProcSet |-> NoTask]
        (* Procedure queue_close *)
        /\ queue_id = [ self \in ProcSet |-> defaultInitValue]
        /\ stack = [self \in ProcSet |-> << >>]
        /\ pc = [self \in ProcSet |-> CASE self = 99 -> "sched"
                                        [] self = 97 -> "wake"
                                        [] self \in {0} -> "main_spawn1"
                                        [] self \in {1, 2} -> "worker_sleep"
                                        [] self \in {3} -> "cw_acquire"
                                        [] self \in {4} -> "cn_sleep"
                                        [] self \in {5} -> "prod_put1"
                                        [] self \in {6} -> "cons_get1"]

lcd_acquire(self) == /\ pc[self] = "lcd_acquire"
                     /\ runningTask = self
                     /\ IF lock[(Latch[latch_id[self]].lock.id)] = NoTask
                           THEN /\ lock' = [lock EXCEPT ![(Latch[latch_id[self]].lock.id)] = self]
                                /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                /\ runningTask' = NoTask
                                /\ lastAction' = <<"AcquireLock", "Immediate", (Latch[latch_id[self]].lock.id), self>>
                                /\ UNCHANGED lockWaiters
                           ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingLock]]
                                /\ lockWaiters' = [lockWaiters EXCEPT ![(Latch[latch_id[self]].lock.id)] = Append(lockWaiters[(Latch[latch_id[self]].lock.id)], self)]
                                /\ runningTask' = NoTask
                                /\ lastAction' = <<"AcquireLock", "Waiting", (Latch[latch_id[self]].lock.id), self>>
                                /\ lock' = lock
                     /\ pc' = [pc EXCEPT ![self] = "lcd_atomic"]
                     /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                     conditionWaiters, conditionFlag, 
                                     queueItems, queueClosed, joinWaiters, 
                                     workersCompleted, itemsProduced, 
                                     itemsConsumed, stack, latch_id, queue_id_, 
                                     item_to_put, item_put_done, queue_id_q, 
                                     item_got, queue_id >>

lcd_atomic(self) == /\ pc[self] = "lcd_atomic"
                    /\ runningTask = self
                    /\ latchCount' = [latchCount EXCEPT ![latch_id[self]] = latchCount[latch_id[self]] - 1]
                    /\ eventFired' = [eventFired EXCEPT ![Latch[latch_id[self]].event.id] = IF   latchCount'[latch_id[self]] = 0
                                                                                              THEN TRUE
                                                                                              ELSE eventFired[Latch[latch_id[self]].event.id]]
                    /\ taskState' = (IF   latchCount'[latch_id[self]] = 0
                                     THEN [t \in Tasks |->
                                        IF   (t = self) \/ (t \in eventWaiters[Latch[latch_id[self]].event.id])
                                        THEN [state |-> Ready]
                                        ELSE taskState[t]]
                                     ELSE [taskState EXCEPT ![self] = [state |-> Ready]])
                    /\ eventWaiters' = [eventWaiters EXCEPT ![Latch[latch_id[self]].event.id] = IF   latchCount'[latch_id[self]] = 0
                                                                                                  THEN {}
                                                                                                  ELSE eventWaiters[Latch[latch_id[self]].event.id]]
                    /\ runningTask' = NoTask
                    /\ lastAction' = <<"LatchCountdown", latch_id[self], self>>
                    /\ pc' = [pc EXCEPT ![self] = "lcd_release"]
                    /\ UNCHANGED << lock, lockWaiters, conditionWaiters, 
                                    conditionFlag, queueItems, queueClosed, 
                                    joinWaiters, workersCompleted, 
                                    itemsProduced, itemsConsumed, stack, 
                                    latch_id, queue_id_, item_to_put, 
                                    item_put_done, queue_id_q, item_got, 
                                    queue_id >>

lcd_release(self) == /\ pc[self] = "lcd_release"
                     /\ runningTask = self
                     /\ Assert(lock[(Latch[latch_id[self]].lock.id)] = self, 
                               "Failure of assertion at line 270, column 1 of macro called at line 410, column 9.")
                     /\ IF lockWaiters[(Latch[latch_id[self]].lock.id)] = << >>
                           THEN /\ lock' = [lock EXCEPT ![(Latch[latch_id[self]].lock.id)] = NoTask]
                                /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                /\ runningTask' = NoTask
                                /\ lastAction' = <<"ReleaseLock", (Latch[latch_id[self]].lock.id), self>>
                                /\ UNCHANGED lockWaiters
                           ELSE /\ LET nextOwner == Head(lockWaiters[(Latch[latch_id[self]].lock.id)]) IN
                                     /\ lock' = [lock EXCEPT ![(Latch[latch_id[self]].lock.id)] = nextOwner]
                                     /\ lockWaiters' = [lockWaiters EXCEPT ![(Latch[latch_id[self]].lock.id)] = Tail(lockWaiters[(Latch[latch_id[self]].lock.id)])]
                                     /\ taskState' = [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                                                        ![self] = [state |-> Ready]]
                                     /\ runningTask' = NoTask
                                     /\ lastAction' = <<"ReleaseLock", (Latch[latch_id[self]].lock.id), self>>
                     /\ pc' = [pc EXCEPT ![self] = "lcd_return"]
                     /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                     conditionWaiters, conditionFlag, 
                                     queueItems, queueClosed, joinWaiters, 
                                     workersCompleted, itemsProduced, 
                                     itemsConsumed, stack, latch_id, queue_id_, 
                                     item_to_put, item_put_done, queue_id_q, 
                                     item_got, queue_id >>

lcd_return(self) == /\ pc[self] = "lcd_return"
                    /\ pc' = [pc EXCEPT ![self] = Head(stack[self]).pc]
                    /\ latch_id' = [latch_id EXCEPT ![self] = Head(stack[self]).latch_id]
                    /\ stack' = [stack EXCEPT ![self] = Tail(stack[self])]
                    /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                    lockWaiters, eventFired, eventWaiters, 
                                    conditionWaiters, conditionFlag, 
                                    queueItems, queueClosed, joinWaiters, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, lastAction, queue_id_, 
                                    item_to_put, item_put_done, queue_id_q, 
                                    item_got, queue_id >>

latch_countdown(self) == lcd_acquire(self) \/ lcd_atomic(self)
                            \/ lcd_release(self) \/ lcd_return(self)

qput_acquire(self) == /\ pc[self] = "qput_acquire"
                      /\ runningTask = self
                      /\ IF lock[(Queue[queue_id_[self]].lock.id)] = NoTask
                            THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id_[self]].lock.id)] = self]
                                 /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"AcquireLock", "Immediate", (Queue[queue_id_[self]].lock.id), self>>
                                 /\ UNCHANGED lockWaiters
                            ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingLock]]
                                 /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id_[self]].lock.id)] = Append(lockWaiters[(Queue[queue_id_[self]].lock.id)], self)]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"AcquireLock", "Waiting", (Queue[queue_id_[self]].lock.id), self>>
                                 /\ lock' = lock
                      /\ pc' = [pc EXCEPT ![self] = "qput_wait_loop"]
                      /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                      conditionWaiters, conditionFlag, 
                                      queueItems, queueClosed, joinWaiters, 
                                      workersCompleted, itemsProduced, 
                                      itemsConsumed, stack, latch_id, 
                                      queue_id_, item_to_put, item_put_done, 
                                      queue_id_q, item_got, queue_id >>

qput_wait_loop(self) == /\ pc[self] = "qput_wait_loop"
                        /\ runningTask = self
                        /\ IF QueueIsFull(queue_id_[self]) /\ ~queueClosed[queue_id_[self]]
                              THEN /\ Assert(lock[Condition[(Queue[queue_id_[self]].not_full.id)].lock.id] = self, 
                                             "Failure of assertion at line 325, column 5 of macro called at line 429, column 9.")
                                   /\ LET hasWaiters == lockWaiters[Condition[(Queue[queue_id_[self]].not_full.id)].lock.id] # << >> IN
                                        LET nextOwner == IF lockWaiters[Condition[(Queue[queue_id_[self]].not_full.id)].lock.id] # << >>
                                                         THEN Head(lockWaiters[Condition[(Queue[queue_id_[self]].not_full.id)].lock.id])
                                                         ELSE NoTask IN
                                          /\ conditionWaiters' = [conditionWaiters EXCEPT ![(Queue[queue_id_[self]].not_full.id)] = conditionWaiters[(Queue[queue_id_[self]].not_full.id)] \union {self}]
                                          /\ lock' = [lock EXCEPT ![Condition[(Queue[queue_id_[self]].not_full.id)].lock.id] = nextOwner]
                                          /\ lockWaiters' = [lockWaiters EXCEPT ![Condition[(Queue[queue_id_[self]].not_full.id)].lock.id] = IF hasWaiters
                                                                                                                                                THEN Tail(lockWaiters[Condition[(Queue[queue_id_[self]].not_full.id)].lock.id])
                                                                                                                                                ELSE << >>]
                                          /\ taskState' = IF hasWaiters
                                                             THEN [taskState EXCEPT ![self] = [state |-> WaitingCondition],
                                                                                     ![nextOwner] = [state |-> Ready]]
                                                             ELSE [taskState EXCEPT ![self] = [state |-> WaitingCondition]]
                                          /\ runningTask' = NoTask
                                          /\ lastAction' = <<"ConditionWait", (Queue[queue_id_[self]].not_full.id), self>>
                                   /\ pc' = [pc EXCEPT ![self] = "qput_wait_loop"]
                                   /\ UNCHANGED item_put_done
                              ELSE /\ IF queueClosed[queue_id_[self]]
                                         THEN /\ item_put_done' = [item_put_done EXCEPT ![self] = TRUE]
                                              /\ pc' = [pc EXCEPT ![self] = "qput_release"]
                                         ELSE /\ pc' = [pc EXCEPT ![self] = "qput_do_put"]
                                              /\ UNCHANGED item_put_done
                                   /\ UNCHANGED << runningTask, taskState, 
                                                   lock, lockWaiters, 
                                                   conditionWaiters, 
                                                   lastAction >>
                        /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                        conditionFlag, queueItems, queueClosed, 
                                        joinWaiters, workersCompleted, 
                                        itemsProduced, itemsConsumed, stack, 
                                        latch_id, queue_id_, item_to_put, 
                                        queue_id_q, item_got, queue_id >>

qput_do_put(self) == /\ pc[self] = "qput_do_put"
                     /\ runningTask = self
                     /\ queueItems' = [queueItems EXCEPT ![queue_id_[self]] = Append(queueItems[queue_id_[self]], item_to_put[self])]
                     /\ Assert(lock[Condition[(Queue[queue_id_[self]].not_empty.id)].lock.id] = self, 
                               "Failure of assertion at line 352, column 5 of macro called at line 443, column 5.")
                     /\ LET hasWaiters == conditionWaiters[(Queue[queue_id_[self]].not_empty.id)] # {} IN
                          LET waiter ==  IF conditionWaiters[(Queue[queue_id_[self]].not_empty.id)] # {}
                                        THEN CHOOSE t \in conditionWaiters[(Queue[queue_id_[self]].not_empty.id)] : TRUE
                                        ELSE NoTask IN
                            /\ conditionWaiters' = [conditionWaiters EXCEPT ![(Queue[queue_id_[self]].not_empty.id)] = IF hasWaiters
                                                                                                                        THEN conditionWaiters[(Queue[queue_id_[self]].not_empty.id)] \ {waiter}
                                                                                                                        ELSE conditionWaiters[(Queue[queue_id_[self]].not_empty.id)]]
                            /\ lockWaiters' = [lockWaiters EXCEPT ![Condition[(Queue[queue_id_[self]].not_empty.id)].lock.id] = IF hasWaiters
                                                                                                                                   THEN Append(lockWaiters[Condition[(Queue[queue_id_[self]].not_empty.id)].lock.id], waiter)
                                                                                                                                   ELSE lockWaiters[Condition[(Queue[queue_id_[self]].not_empty.id)].lock.id]]
                            /\ taskState' = IF hasWaiters
                                               THEN [taskState EXCEPT ![waiter] = [state |-> WaitingLock],
                                                                       ![self] = [state |-> Ready]]
                                               ELSE [taskState EXCEPT ![self] = [state |-> Ready]]
                            /\ runningTask' = NoTask
                            /\ lastAction' = <<"ConditionNotify", (Queue[queue_id_[self]].not_empty.id), self>>
                     /\ pc' = [pc EXCEPT ![self] = "qput_release"]
                     /\ UNCHANGED << latchCount, lock, eventFired, 
                                     eventWaiters, conditionFlag, queueClosed, 
                                     joinWaiters, workersCompleted, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

qput_release(self) == /\ pc[self] = "qput_release"
                      /\ runningTask = self
                      /\ Assert(lock[(Queue[queue_id_[self]].lock.id)] = self, 
                                "Failure of assertion at line 270, column 1 of macro called at line 447, column 5.")
                      /\ IF lockWaiters[(Queue[queue_id_[self]].lock.id)] = << >>
                            THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id_[self]].lock.id)] = NoTask]
                                 /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"ReleaseLock", (Queue[queue_id_[self]].lock.id), self>>
                                 /\ UNCHANGED lockWaiters
                            ELSE /\ LET nextOwner == Head(lockWaiters[(Queue[queue_id_[self]].lock.id)]) IN
                                      /\ lock' = [lock EXCEPT ![(Queue[queue_id_[self]].lock.id)] = nextOwner]
                                      /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id_[self]].lock.id)] = Tail(lockWaiters[(Queue[queue_id_[self]].lock.id)])]
                                      /\ taskState' = [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                                                         ![self] = [state |-> Ready]]
                                      /\ runningTask' = NoTask
                                      /\ lastAction' = <<"ReleaseLock", (Queue[queue_id_[self]].lock.id), self>>
                      /\ pc' = [pc EXCEPT ![self] = "qput_return"]
                      /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                      conditionWaiters, conditionFlag, 
                                      queueItems, queueClosed, joinWaiters, 
                                      workersCompleted, itemsProduced, 
                                      itemsConsumed, stack, latch_id, 
                                      queue_id_, item_to_put, item_put_done, 
                                      queue_id_q, item_got, queue_id >>

qput_return(self) == /\ pc[self] = "qput_return"
                     /\ pc' = [pc EXCEPT ![self] = Head(stack[self]).pc]
                     /\ item_put_done' = [item_put_done EXCEPT ![self] = Head(stack[self]).item_put_done]
                     /\ queue_id_' = [queue_id_ EXCEPT ![self] = Head(stack[self]).queue_id_]
                     /\ item_to_put' = [item_to_put EXCEPT ![self] = Head(stack[self]).item_to_put]
                     /\ stack' = [stack EXCEPT ![self] = Tail(stack[self])]
                     /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                     lockWaiters, eventFired, eventWaiters, 
                                     conditionWaiters, conditionFlag, 
                                     queueItems, queueClosed, joinWaiters, 
                                     workersCompleted, itemsProduced, 
                                     itemsConsumed, lastAction, latch_id, 
                                     queue_id_q, item_got, queue_id >>

queue_put(self) == qput_acquire(self) \/ qput_wait_loop(self)
                      \/ qput_do_put(self) \/ qput_release(self)
                      \/ qput_return(self)

qget_acquire(self) == /\ pc[self] = "qget_acquire"
                      /\ runningTask = self
                      /\ IF lock[(Queue[queue_id_q[self]].lock.id)] = NoTask
                            THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id_q[self]].lock.id)] = self]
                                 /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"AcquireLock", "Immediate", (Queue[queue_id_q[self]].lock.id), self>>
                                 /\ UNCHANGED lockWaiters
                            ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingLock]]
                                 /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id_q[self]].lock.id)] = Append(lockWaiters[(Queue[queue_id_q[self]].lock.id)], self)]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"AcquireLock", "Waiting", (Queue[queue_id_q[self]].lock.id), self>>
                                 /\ lock' = lock
                      /\ pc' = [pc EXCEPT ![self] = "qget_wait_loop"]
                      /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                      conditionWaiters, conditionFlag, 
                                      queueItems, queueClosed, joinWaiters, 
                                      workersCompleted, itemsProduced, 
                                      itemsConsumed, stack, latch_id, 
                                      queue_id_, item_to_put, item_put_done, 
                                      queue_id_q, item_got, queue_id >>

qget_wait_loop(self) == /\ pc[self] = "qget_wait_loop"
                        /\ runningTask = self
                        /\ IF QueueIsEmpty(queue_id_q[self]) /\ ~queueClosed[queue_id_q[self]]
                              THEN /\ Assert(lock[Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id] = self, 
                                             "Failure of assertion at line 325, column 5 of macro called at line 465, column 9.")
                                   /\ LET hasWaiters == lockWaiters[Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id] # << >> IN
                                        LET nextOwner == IF lockWaiters[Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id] # << >>
                                                         THEN Head(lockWaiters[Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id])
                                                         ELSE NoTask IN
                                          /\ conditionWaiters' = [conditionWaiters EXCEPT ![(Queue[queue_id_q[self]].not_empty.id)] = conditionWaiters[(Queue[queue_id_q[self]].not_empty.id)] \union {self}]
                                          /\ lock' = [lock EXCEPT ![Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id] = nextOwner]
                                          /\ lockWaiters' = [lockWaiters EXCEPT ![Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id] = IF hasWaiters
                                                                                                                                                  THEN Tail(lockWaiters[Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id])
                                                                                                                                                  ELSE << >>]
                                          /\ taskState' = IF hasWaiters
                                                             THEN [taskState EXCEPT ![self] = [state |-> WaitingCondition],
                                                                                     ![nextOwner] = [state |-> Ready]]
                                                             ELSE [taskState EXCEPT ![self] = [state |-> WaitingCondition]]
                                          /\ runningTask' = NoTask
                                          /\ lastAction' = <<"ConditionWait", (Queue[queue_id_q[self]].not_empty.id), self>>
                                   /\ pc' = [pc EXCEPT ![self] = "qget_wait_loop"]
                                   /\ UNCHANGED item_got
                              ELSE /\ IF queueClosed[queue_id_q[self]] /\ QueueIsEmpty(queue_id_q[self])
                                         THEN /\ item_got' = [item_got EXCEPT ![self] = NoTask]
                                              /\ pc' = [pc EXCEPT ![self] = "qget_release"]
                                         ELSE /\ pc' = [pc EXCEPT ![self] = "qget_do_get"]
                                              /\ UNCHANGED item_got
                                   /\ UNCHANGED << runningTask, taskState, 
                                                   lock, lockWaiters, 
                                                   conditionWaiters, 
                                                   lastAction >>
                        /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                        conditionFlag, queueItems, queueClosed, 
                                        joinWaiters, workersCompleted, 
                                        itemsProduced, itemsConsumed, stack, 
                                        latch_id, queue_id_, item_to_put, 
                                        item_put_done, queue_id_q, queue_id >>

qget_do_get(self) == /\ pc[self] = "qget_do_get"
                     /\ runningTask = self
                     /\ item_got' = [item_got EXCEPT ![self] = Head(queueItems[queue_id_q[self]])]
                     /\ queueItems' = [queueItems EXCEPT ![queue_id_q[self]] = Tail(queueItems[queue_id_q[self]])]
                     /\ Assert(lock[Condition[(Queue[queue_id_q[self]].not_full.id)].lock.id] = self, 
                               "Failure of assertion at line 352, column 5 of macro called at line 480, column 5.")
                     /\ LET hasWaiters == conditionWaiters[(Queue[queue_id_q[self]].not_full.id)] # {} IN
                          LET waiter ==  IF conditionWaiters[(Queue[queue_id_q[self]].not_full.id)] # {}
                                        THEN CHOOSE t \in conditionWaiters[(Queue[queue_id_q[self]].not_full.id)] : TRUE
                                        ELSE NoTask IN
                            /\ conditionWaiters' = [conditionWaiters EXCEPT ![(Queue[queue_id_q[self]].not_full.id)] = IF hasWaiters
                                                                                                                        THEN conditionWaiters[(Queue[queue_id_q[self]].not_full.id)] \ {waiter}
                                                                                                                        ELSE conditionWaiters[(Queue[queue_id_q[self]].not_full.id)]]
                            /\ lockWaiters' = [lockWaiters EXCEPT ![Condition[(Queue[queue_id_q[self]].not_full.id)].lock.id] = IF hasWaiters
                                                                                                                                   THEN Append(lockWaiters[Condition[(Queue[queue_id_q[self]].not_full.id)].lock.id], waiter)
                                                                                                                                   ELSE lockWaiters[Condition[(Queue[queue_id_q[self]].not_full.id)].lock.id]]
                            /\ taskState' = IF hasWaiters
                                               THEN [taskState EXCEPT ![waiter] = [state |-> WaitingLock],
                                                                       ![self] = [state |-> Ready]]
                                               ELSE [taskState EXCEPT ![self] = [state |-> Ready]]
                            /\ runningTask' = NoTask
                            /\ lastAction' = <<"ConditionNotify", (Queue[queue_id_q[self]].not_full.id), self>>
                     /\ pc' = [pc EXCEPT ![self] = "qget_release"]
                     /\ UNCHANGED << latchCount, lock, eventFired, 
                                     eventWaiters, conditionFlag, queueClosed, 
                                     joinWaiters, workersCompleted, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, queue_id >>

qget_release(self) == /\ pc[self] = "qget_release"
                      /\ runningTask = self
                      /\ Assert(lock[(Queue[queue_id_q[self]].lock.id)] = self, 
                                "Failure of assertion at line 270, column 1 of macro called at line 484, column 5.")
                      /\ IF lockWaiters[(Queue[queue_id_q[self]].lock.id)] = << >>
                            THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id_q[self]].lock.id)] = NoTask]
                                 /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"ReleaseLock", (Queue[queue_id_q[self]].lock.id), self>>
                                 /\ UNCHANGED lockWaiters
                            ELSE /\ LET nextOwner == Head(lockWaiters[(Queue[queue_id_q[self]].lock.id)]) IN
                                      /\ lock' = [lock EXCEPT ![(Queue[queue_id_q[self]].lock.id)] = nextOwner]
                                      /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id_q[self]].lock.id)] = Tail(lockWaiters[(Queue[queue_id_q[self]].lock.id)])]
                                      /\ taskState' = [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                                                         ![self] = [state |-> Ready]]
                                      /\ runningTask' = NoTask
                                      /\ lastAction' = <<"ReleaseLock", (Queue[queue_id_q[self]].lock.id), self>>
                      /\ pc' = [pc EXCEPT ![self] = "qget_return"]
                      /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                      conditionWaiters, conditionFlag, 
                                      queueItems, queueClosed, joinWaiters, 
                                      workersCompleted, itemsProduced, 
                                      itemsConsumed, stack, latch_id, 
                                      queue_id_, item_to_put, item_put_done, 
                                      queue_id_q, item_got, queue_id >>

qget_return(self) == /\ pc[self] = "qget_return"
                     /\ pc' = [pc EXCEPT ![self] = Head(stack[self]).pc]
                     /\ item_got' = [item_got EXCEPT ![self] = Head(stack[self]).item_got]
                     /\ queue_id_q' = [queue_id_q EXCEPT ![self] = Head(stack[self]).queue_id_q]
                     /\ stack' = [stack EXCEPT ![self] = Tail(stack[self])]
                     /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                     lockWaiters, eventFired, eventWaiters, 
                                     conditionWaiters, conditionFlag, 
                                     queueItems, queueClosed, joinWaiters, 
                                     workersCompleted, itemsProduced, 
                                     itemsConsumed, lastAction, latch_id, 
                                     queue_id_, item_to_put, item_put_done, 
                                     queue_id >>

queue_get(self) == qget_acquire(self) \/ qget_wait_loop(self)
                      \/ qget_do_get(self) \/ qget_release(self)
                      \/ qget_return(self)

qclose_acquire(self) == /\ pc[self] = "qclose_acquire"
                        /\ runningTask = self
                        /\ IF lock[(Queue[queue_id[self]].lock.id)] = NoTask
                              THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id[self]].lock.id)] = self]
                                   /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                   /\ runningTask' = NoTask
                                   /\ lastAction' = <<"AcquireLock", "Immediate", (Queue[queue_id[self]].lock.id), self>>
                                   /\ UNCHANGED lockWaiters
                              ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingLock]]
                                   /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id[self]].lock.id)] = Append(lockWaiters[(Queue[queue_id[self]].lock.id)], self)]
                                   /\ runningTask' = NoTask
                                   /\ lastAction' = <<"AcquireLock", "Waiting", (Queue[queue_id[self]].lock.id), self>>
                                   /\ lock' = lock
                        /\ pc' = [pc EXCEPT ![self] = "qclose_do_close"]
                        /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                        conditionWaiters, conditionFlag, 
                                        queueItems, queueClosed, joinWaiters, 
                                        workersCompleted, itemsProduced, 
                                        itemsConsumed, stack, latch_id, 
                                        queue_id_, item_to_put, item_put_done, 
                                        queue_id_q, item_got, queue_id >>

qclose_do_close(self) == /\ pc[self] = "qclose_do_close"
                         /\ runningTask = self
                         /\ queueClosed' = [queueClosed EXCEPT ![queue_id[self]] = TRUE]
                         /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                         /\ runningTask' = NoTask
                         /\ lastAction' = <<"QueueClose", queue_id[self], self>>
                         /\ pc' = [pc EXCEPT ![self] = "qclose_release"]
                         /\ UNCHANGED << latchCount, lock, lockWaiters, 
                                         eventFired, eventWaiters, 
                                         conditionWaiters, conditionFlag, 
                                         queueItems, joinWaiters, 
                                         workersCompleted, itemsProduced, 
                                         itemsConsumed, stack, latch_id, 
                                         queue_id_, item_to_put, item_put_done, 
                                         queue_id_q, item_got, queue_id >>

qclose_release(self) == /\ pc[self] = "qclose_release"
                        /\ runningTask = self
                        /\ Assert(lock[(Queue[queue_id[self]].lock.id)] = self, 
                                  "Failure of assertion at line 270, column 1 of macro called at line 506, column 5.")
                        /\ IF lockWaiters[(Queue[queue_id[self]].lock.id)] = << >>
                              THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id[self]].lock.id)] = NoTask]
                                   /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                   /\ runningTask' = NoTask
                                   /\ lastAction' = <<"ReleaseLock", (Queue[queue_id[self]].lock.id), self>>
                                   /\ UNCHANGED lockWaiters
                              ELSE /\ LET nextOwner == Head(lockWaiters[(Queue[queue_id[self]].lock.id)]) IN
                                        /\ lock' = [lock EXCEPT ![(Queue[queue_id[self]].lock.id)] = nextOwner]
                                        /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id[self]].lock.id)] = Tail(lockWaiters[(Queue[queue_id[self]].lock.id)])]
                                        /\ taskState' = [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                                                           ![self] = [state |-> Ready]]
                                        /\ runningTask' = NoTask
                                        /\ lastAction' = <<"ReleaseLock", (Queue[queue_id[self]].lock.id), self>>
                        /\ pc' = [pc EXCEPT ![self] = "qclose_return"]
                        /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                        conditionWaiters, conditionFlag, 
                                        queueItems, queueClosed, joinWaiters, 
                                        workersCompleted, itemsProduced, 
                                        itemsConsumed, stack, latch_id, 
                                        queue_id_, item_to_put, item_put_done, 
                                        queue_id_q, item_got, queue_id >>

qclose_return(self) == /\ pc[self] = "qclose_return"
                       /\ pc' = [pc EXCEPT ![self] = Head(stack[self]).pc]
                       /\ queue_id' = [queue_id EXCEPT ![self] = Head(stack[self]).queue_id]
                       /\ stack' = [stack EXCEPT ![self] = Tail(stack[self])]
                       /\ UNCHANGED << runningTask, taskState, latchCount, 
                                       lock, lockWaiters, eventFired, 
                                       eventWaiters, conditionWaiters, 
                                       conditionFlag, queueItems, queueClosed, 
                                       joinWaiters, workersCompleted, 
                                       itemsProduced, itemsConsumed, 
                                       lastAction, latch_id, queue_id_, 
                                       item_to_put, item_put_done, queue_id_q, 
                                       item_got >>

queue_close(self) == qclose_acquire(self) \/ qclose_do_close(self)
                        \/ qclose_release(self) \/ qclose_return(self)

sched == /\ pc[99] = "sched"
         /\ runningTask = NoTask /\ \E t \in Tasks : IsSchedulable(t)
         /\ \E t \in {t \in Tasks : IsSchedulable(t)}:
              /\ runningTask' = t
              /\ taskState' = [taskState EXCEPT ![t] = [state |-> Running]]
              /\ lastAction' = <<"Scheduler", "pick", t>>
         /\ pc' = [pc EXCEPT ![99] = "sched"]
         /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                         eventWaiters, conditionWaiters, conditionFlag, 
                         queueItems, queueClosed, joinWaiters, 
                         workersCompleted, itemsProduced, itemsConsumed, stack, 
                         latch_id, queue_id_, item_to_put, item_put_done, 
                         queue_id_q, item_got, queue_id >>

Scheduler == sched

wake == /\ pc[97] = "wake"
        /\ \E t \in Tasks : IsSleeping(t)
        /\ \E t \in {u \in Tasks : IsSleeping(u)}:
             /\ taskState' = [taskState EXCEPT ![t] = [state |-> Ready]]
             /\ lastAction' = <<"ExternalWake", t>>
        /\ pc' = [pc EXCEPT ![97] = "wake"]
        /\ UNCHANGED << runningTask, latchCount, lock, lockWaiters, eventFired, 
                        eventWaiters, conditionWaiters, conditionFlag, 
                        queueItems, queueClosed, joinWaiters, workersCompleted, 
                        itemsProduced, itemsConsumed, stack, latch_id, 
                        queue_id_, item_to_put, item_put_done, queue_id_q, 
                        item_got, queue_id >>

ExternalWake == wake

main_spawn1(self) == /\ pc[self] = "main_spawn1"
                     /\ runningTask = self
                     /\ taskState' = [taskState EXCEPT ![1]    = [state |-> Ready],
                                                        ![self] = [state |-> Ready]]
                     /\ runningTask' = NoTask
                     /\ lastAction' = <<"Spawn", 1, self>>
                     /\ pc' = [pc EXCEPT ![self] = "main_spawn2"]
                     /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                     eventWaiters, conditionWaiters, 
                                     conditionFlag, queueItems, queueClosed, 
                                     joinWaiters, workersCompleted, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

main_spawn2(self) == /\ pc[self] = "main_spawn2"
                     /\ runningTask = self
                     /\ taskState' = [taskState EXCEPT ![2]    = [state |-> Ready],
                                                        ![self] = [state |-> Ready]]
                     /\ runningTask' = NoTask
                     /\ lastAction' = <<"Spawn", 2, self>>
                     /\ pc' = [pc EXCEPT ![self] = "main_spawn3"]
                     /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                     eventWaiters, conditionWaiters, 
                                     conditionFlag, queueItems, queueClosed, 
                                     joinWaiters, workersCompleted, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

main_spawn3(self) == /\ pc[self] = "main_spawn3"
                     /\ runningTask = self
                     /\ taskState' = [taskState EXCEPT ![3]    = [state |-> Ready],
                                                        ![self] = [state |-> Ready]]
                     /\ runningTask' = NoTask
                     /\ lastAction' = <<"Spawn", 3, self>>
                     /\ pc' = [pc EXCEPT ![self] = "main_spawn4"]
                     /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                     eventWaiters, conditionWaiters, 
                                     conditionFlag, queueItems, queueClosed, 
                                     joinWaiters, workersCompleted, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

main_spawn4(self) == /\ pc[self] = "main_spawn4"
                     /\ runningTask = self
                     /\ taskState' = [taskState EXCEPT ![4]    = [state |-> Ready],
                                                        ![self] = [state |-> Ready]]
                     /\ runningTask' = NoTask
                     /\ lastAction' = <<"Spawn", 4, self>>
                     /\ pc' = [pc EXCEPT ![self] = "main_join1"]
                     /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                     eventWaiters, conditionWaiters, 
                                     conditionFlag, queueItems, queueClosed, 
                                     joinWaiters, workersCompleted, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

main_join1(self) == /\ pc[self] = "main_join1"
                    /\ runningTask = self
                    /\ IF IsDone(1)
                          THEN /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"Join", "Immediate", 1, self>>
                               /\ UNCHANGED joinWaiters
                          ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingJoin]]
                               /\ joinWaiters' = [joinWaiters EXCEPT ![1] = joinWaiters[1] \union {self}]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"Join", "Waiting", 1, self>>
                    /\ pc' = [pc EXCEPT ![self] = "main_join2"]
                    /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                    eventWaiters, conditionWaiters, 
                                    conditionFlag, queueItems, queueClosed, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, stack, latch_id, queue_id_, 
                                    item_to_put, item_put_done, queue_id_q, 
                                    item_got, queue_id >>

main_join2(self) == /\ pc[self] = "main_join2"
                    /\ runningTask = self
                    /\ IF IsDone(2)
                          THEN /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"Join", "Immediate", 2, self>>
                               /\ UNCHANGED joinWaiters
                          ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingJoin]]
                               /\ joinWaiters' = [joinWaiters EXCEPT ![2] = joinWaiters[2] \union {self}]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"Join", "Waiting", 2, self>>
                    /\ pc' = [pc EXCEPT ![self] = "main_sleep"]
                    /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                    eventWaiters, conditionWaiters, 
                                    conditionFlag, queueItems, queueClosed, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, stack, latch_id, queue_id_, 
                                    item_to_put, item_put_done, queue_id_q, 
                                    item_got, queue_id >>

main_sleep(self) == /\ pc[self] = "main_sleep"
                    /\ runningTask = self
                    /\ taskState' = [taskState EXCEPT ![self] = [state |-> Sleeping]]
                    /\ runningTask' = NoTask
                    /\ lastAction' = <<"Sleep", self>>
                    /\ pc' = [pc EXCEPT ![self] = "main_wait"]
                    /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                    eventWaiters, conditionWaiters, 
                                    conditionFlag, queueItems, queueClosed, 
                                    joinWaiters, workersCompleted, 
                                    itemsProduced, itemsConsumed, stack, 
                                    latch_id, queue_id_, item_to_put, 
                                    item_put_done, queue_id_q, item_got, 
                                    queue_id >>

main_wait(self) == /\ pc[self] = "main_wait"
                   /\ runningTask = self
                   /\ taskState' = [taskState EXCEPT ![self] = [state |-> IF eventFired[0] THEN Ready ELSE WaitingEvent]]
                   /\ eventWaiters' = [eventWaiters EXCEPT ![0] = IF eventFired[0] THEN eventWaiters[0] ELSE eventWaiters[0] \union {self}]
                   /\ runningTask' = NoTask
                   /\ lastAction' = <<"EventWait", 0, self>>
                   /\ pc' = [pc EXCEPT ![self] = "main_spawn5"]
                   /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                   conditionWaiters, conditionFlag, queueItems, 
                                   queueClosed, joinWaiters, workersCompleted, 
                                   itemsProduced, itemsConsumed, stack, 
                                   latch_id, queue_id_, item_to_put, 
                                   item_put_done, queue_id_q, item_got, 
                                   queue_id >>

main_spawn5(self) == /\ pc[self] = "main_spawn5"
                     /\ runningTask = self
                     /\ taskState' = [taskState EXCEPT ![5]    = [state |-> Ready],
                                                        ![self] = [state |-> Ready]]
                     /\ runningTask' = NoTask
                     /\ lastAction' = <<"Spawn", 5, self>>
                     /\ pc' = [pc EXCEPT ![self] = "main_spawn6"]
                     /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                     eventWaiters, conditionWaiters, 
                                     conditionFlag, queueItems, queueClosed, 
                                     joinWaiters, workersCompleted, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

main_spawn6(self) == /\ pc[self] = "main_spawn6"
                     /\ runningTask = self
                     /\ taskState' = [taskState EXCEPT ![6]    = [state |-> Ready],
                                                        ![self] = [state |-> Ready]]
                     /\ runningTask' = NoTask
                     /\ lastAction' = <<"Spawn", 6, self>>
                     /\ pc' = [pc EXCEPT ![self] = "main_join5"]
                     /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                     eventWaiters, conditionWaiters, 
                                     conditionFlag, queueItems, queueClosed, 
                                     joinWaiters, workersCompleted, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

main_join5(self) == /\ pc[self] = "main_join5"
                    /\ runningTask = self
                    /\ IF IsDone(5)
                          THEN /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"Join", "Immediate", 5, self>>
                               /\ UNCHANGED joinWaiters
                          ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingJoin]]
                               /\ joinWaiters' = [joinWaiters EXCEPT ![5] = joinWaiters[5] \union {self}]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"Join", "Waiting", 5, self>>
                    /\ pc' = [pc EXCEPT ![self] = "main_join6"]
                    /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                    eventWaiters, conditionWaiters, 
                                    conditionFlag, queueItems, queueClosed, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, stack, latch_id, queue_id_, 
                                    item_to_put, item_put_done, queue_id_q, 
                                    item_got, queue_id >>

main_join6(self) == /\ pc[self] = "main_join6"
                    /\ runningTask = self
                    /\ IF IsDone(6)
                          THEN /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"Join", "Immediate", 6, self>>
                               /\ UNCHANGED joinWaiters
                          ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingJoin]]
                               /\ joinWaiters' = [joinWaiters EXCEPT ![6] = joinWaiters[6] \union {self}]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"Join", "Waiting", 6, self>>
                    /\ pc' = [pc EXCEPT ![self] = "main_done"]
                    /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                    eventWaiters, conditionWaiters, 
                                    conditionFlag, queueItems, queueClosed, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, stack, latch_id, queue_id_, 
                                    item_to_put, item_put_done, queue_id_q, 
                                    item_got, queue_id >>

main_done(self) == /\ pc[self] = "main_done"
                   /\ runningTask = self
                   /\ taskState' =              [t \in Tasks |->
                                       CASE t = self                -> [state |-> Done]
                                           [] t \in joinWaiters[self] -> [state |-> Ready]
                                           [] OTHER                   -> taskState[t]
                                   ]
                   /\ joinWaiters' = [joinWaiters EXCEPT ![self] = {}]
                   /\ runningTask' = NoTask
                   /\ lastAction' = <<"Complete", self>>
                   /\ pc' = [pc EXCEPT ![self] = "Done"]
                   /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                   eventWaiters, conditionWaiters, 
                                   conditionFlag, queueItems, queueClosed, 
                                   workersCompleted, itemsProduced, 
                                   itemsConsumed, stack, latch_id, queue_id_, 
                                   item_to_put, item_put_done, queue_id_q, 
                                   item_got, queue_id >>

Main(self) == main_spawn1(self) \/ main_spawn2(self) \/ main_spawn3(self)
                 \/ main_spawn4(self) \/ main_join1(self)
                 \/ main_join2(self) \/ main_sleep(self) \/ main_wait(self)
                 \/ main_spawn5(self) \/ main_spawn6(self)
                 \/ main_join5(self) \/ main_join6(self) \/ main_done(self)

worker_sleep(self) == /\ pc[self] = "worker_sleep"
                      /\ runningTask = self
                      /\ taskState' = [taskState EXCEPT ![self] = [state |-> Sleeping]]
                      /\ runningTask' = NoTask
                      /\ lastAction' = <<"Sleep", self>>
                      /\ pc' = [pc EXCEPT ![self] = "worker_countdown"]
                      /\ UNCHANGED << latchCount, lock, lockWaiters, 
                                      eventFired, eventWaiters, 
                                      conditionWaiters, conditionFlag, 
                                      queueItems, queueClosed, joinWaiters, 
                                      workersCompleted, itemsProduced, 
                                      itemsConsumed, stack, latch_id, 
                                      queue_id_, item_to_put, item_put_done, 
                                      queue_id_q, item_got, queue_id >>

worker_countdown(self) == /\ pc[self] = "worker_countdown"
                          /\ runningTask = self
                          /\ /\ latch_id' = [latch_id EXCEPT ![self] = 0]
                             /\ stack' = [stack EXCEPT ![self] = << [ procedure |->  "latch_countdown",
                                                                      pc        |->  "worker_done",
                                                                      latch_id  |->  latch_id[self] ] >>
                                                                  \o stack[self]]
                          /\ pc' = [pc EXCEPT ![self] = "lcd_acquire"]
                          /\ UNCHANGED << runningTask, taskState, latchCount, 
                                          lock, lockWaiters, eventFired, 
                                          eventWaiters, conditionWaiters, 
                                          conditionFlag, queueItems, 
                                          queueClosed, joinWaiters, 
                                          workersCompleted, itemsProduced, 
                                          itemsConsumed, lastAction, queue_id_, 
                                          item_to_put, item_put_done, 
                                          queue_id_q, item_got, queue_id >>

worker_done(self) == /\ pc[self] = "worker_done"
                     /\ runningTask = self
                     /\ workersCompleted' = workersCompleted + 1
                     /\ taskState' =              [t \in Tasks |->
                                         CASE t = self                -> [state |-> Done]
                                             [] t \in joinWaiters[self] -> [state |-> Ready]
                                             [] OTHER                   -> taskState[t]
                                     ]
                     /\ joinWaiters' = [joinWaiters EXCEPT ![self] = {}]
                     /\ runningTask' = NoTask
                     /\ lastAction' = <<"Complete", self>>
                     /\ pc' = [pc EXCEPT ![self] = "Done"]
                     /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                     eventWaiters, conditionWaiters, 
                                     conditionFlag, queueItems, queueClosed, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

Worker(self) == worker_sleep(self) \/ worker_countdown(self)
                   \/ worker_done(self)

cw_acquire(self) == /\ pc[self] = "cw_acquire"
                    /\ runningTask = self
                    /\ IF lock[(Condition[0].lock.id)] = NoTask
                          THEN /\ lock' = [lock EXCEPT ![(Condition[0].lock.id)] = self]
                               /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"AcquireLock", "Immediate", (Condition[0].lock.id), self>>
                               /\ UNCHANGED lockWaiters
                          ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingLock]]
                               /\ lockWaiters' = [lockWaiters EXCEPT ![(Condition[0].lock.id)] = Append(lockWaiters[(Condition[0].lock.id)], self)]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"AcquireLock", "Waiting", (Condition[0].lock.id), self>>
                               /\ lock' = lock
                    /\ pc' = [pc EXCEPT ![self] = "cw_check"]
                    /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                    conditionWaiters, conditionFlag, 
                                    queueItems, queueClosed, joinWaiters, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, stack, latch_id, queue_id_, 
                                    item_to_put, item_put_done, queue_id_q, 
                                    item_got, queue_id >>

cw_check(self) == /\ pc[self] = "cw_check"
                  /\ IF ~conditionFlag[0]
                        THEN /\ runningTask = self
                             /\ Assert(lock[Condition[0].lock.id] = self, 
                                       "Failure of assertion at line 325, column 5 of macro called at line 622, column 9.")
                             /\ LET hasWaiters == lockWaiters[Condition[0].lock.id] # << >> IN
                                  LET nextOwner == IF lockWaiters[Condition[0].lock.id] # << >>
                                                   THEN Head(lockWaiters[Condition[0].lock.id])
                                                   ELSE NoTask IN
                                    /\ conditionWaiters' = [conditionWaiters EXCEPT ![0] = conditionWaiters[0] \union {self}]
                                    /\ lock' = [lock EXCEPT ![Condition[0].lock.id] = nextOwner]
                                    /\ lockWaiters' = [lockWaiters EXCEPT ![Condition[0].lock.id] = IF hasWaiters
                                                                                                       THEN Tail(lockWaiters[Condition[0].lock.id])
                                                                                                       ELSE << >>]
                                    /\ taskState' = IF hasWaiters
                                                       THEN [taskState EXCEPT ![self] = [state |-> WaitingCondition],
                                                                               ![nextOwner] = [state |-> Ready]]
                                                       ELSE [taskState EXCEPT ![self] = [state |-> WaitingCondition]]
                                    /\ runningTask' = NoTask
                                    /\ lastAction' = <<"ConditionWait", 0, self>>
                             /\ pc' = [pc EXCEPT ![self] = "cw_loop"]
                        ELSE /\ pc' = [pc EXCEPT ![self] = "cw_release"]
                             /\ UNCHANGED << runningTask, taskState, lock, 
                                             lockWaiters, conditionWaiters, 
                                             lastAction >>
                  /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                  conditionFlag, queueItems, queueClosed, 
                                  joinWaiters, workersCompleted, itemsProduced, 
                                  itemsConsumed, stack, latch_id, queue_id_, 
                                  item_to_put, item_put_done, queue_id_q, 
                                  item_got, queue_id >>

cw_loop(self) == /\ pc[self] = "cw_loop"
                 /\ runningTask = self
                 /\ pc' = [pc EXCEPT ![self] = "cw_check"]
                 /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                 lockWaiters, eventFired, eventWaiters, 
                                 conditionWaiters, conditionFlag, queueItems, 
                                 queueClosed, joinWaiters, workersCompleted, 
                                 itemsProduced, itemsConsumed, lastAction, 
                                 stack, latch_id, queue_id_, item_to_put, 
                                 item_put_done, queue_id_q, item_got, queue_id >>

cw_release(self) == /\ pc[self] = "cw_release"
                    /\ runningTask = self
                    /\ Assert(lock[(Condition[0].lock.id)] = self, 
                              "Failure of assertion at line 270, column 1 of macro called at line 629, column 5.")
                    /\ IF lockWaiters[(Condition[0].lock.id)] = << >>
                          THEN /\ lock' = [lock EXCEPT ![(Condition[0].lock.id)] = NoTask]
                               /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"ReleaseLock", (Condition[0].lock.id), self>>
                               /\ UNCHANGED lockWaiters
                          ELSE /\ LET nextOwner == Head(lockWaiters[(Condition[0].lock.id)]) IN
                                    /\ lock' = [lock EXCEPT ![(Condition[0].lock.id)] = nextOwner]
                                    /\ lockWaiters' = [lockWaiters EXCEPT ![(Condition[0].lock.id)] = Tail(lockWaiters[(Condition[0].lock.id)])]
                                    /\ taskState' = [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                                                       ![self] = [state |-> Ready]]
                                    /\ runningTask' = NoTask
                                    /\ lastAction' = <<"ReleaseLock", (Condition[0].lock.id), self>>
                    /\ pc' = [pc EXCEPT ![self] = "cw_done"]
                    /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                    conditionWaiters, conditionFlag, 
                                    queueItems, queueClosed, joinWaiters, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, stack, latch_id, queue_id_, 
                                    item_to_put, item_put_done, queue_id_q, 
                                    item_got, queue_id >>

cw_done(self) == /\ pc[self] = "cw_done"
                 /\ runningTask = self
                 /\ taskState' =              [t \in Tasks |->
                                     CASE t = self                -> [state |-> Done]
                                         [] t \in joinWaiters[self] -> [state |-> Ready]
                                         [] OTHER                   -> taskState[t]
                                 ]
                 /\ joinWaiters' = [joinWaiters EXCEPT ![self] = {}]
                 /\ runningTask' = NoTask
                 /\ lastAction' = <<"Complete", self>>
                 /\ pc' = [pc EXCEPT ![self] = "Done"]
                 /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                 eventWaiters, conditionWaiters, conditionFlag, 
                                 queueItems, queueClosed, workersCompleted, 
                                 itemsProduced, itemsConsumed, stack, latch_id, 
                                 queue_id_, item_to_put, item_put_done, 
                                 queue_id_q, item_got, queue_id >>

ConditionWaiter(self) == cw_acquire(self) \/ cw_check(self)
                            \/ cw_loop(self) \/ cw_release(self)
                            \/ cw_done(self)

cn_sleep(self) == /\ pc[self] = "cn_sleep"
                  /\ runningTask = self
                  /\ taskState' = [taskState EXCEPT ![self] = [state |-> Sleeping]]
                  /\ runningTask' = NoTask
                  /\ lastAction' = <<"Sleep", self>>
                  /\ pc' = [pc EXCEPT ![self] = "cn_acquire"]
                  /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                  eventWaiters, conditionWaiters, 
                                  conditionFlag, queueItems, queueClosed, 
                                  joinWaiters, workersCompleted, itemsProduced, 
                                  itemsConsumed, stack, latch_id, queue_id_, 
                                  item_to_put, item_put_done, queue_id_q, 
                                  item_got, queue_id >>

cn_acquire(self) == /\ pc[self] = "cn_acquire"
                    /\ runningTask = self
                    /\ IF lock[(Condition[0].lock.id)] = NoTask
                          THEN /\ lock' = [lock EXCEPT ![(Condition[0].lock.id)] = self]
                               /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"AcquireLock", "Immediate", (Condition[0].lock.id), self>>
                               /\ UNCHANGED lockWaiters
                          ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingLock]]
                               /\ lockWaiters' = [lockWaiters EXCEPT ![(Condition[0].lock.id)] = Append(lockWaiters[(Condition[0].lock.id)], self)]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"AcquireLock", "Waiting", (Condition[0].lock.id), self>>
                               /\ lock' = lock
                    /\ pc' = [pc EXCEPT ![self] = "cn_set_and_notify"]
                    /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                    conditionWaiters, conditionFlag, 
                                    queueItems, queueClosed, joinWaiters, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, stack, latch_id, queue_id_, 
                                    item_to_put, item_put_done, queue_id_q, 
                                    item_got, queue_id >>

cn_set_and_notify(self) == /\ pc[self] = "cn_set_and_notify"
                           /\ runningTask = self
                           /\ conditionFlag' = [conditionFlag EXCEPT ![0] = TRUE]
                           /\ Assert(lock[Condition[0].lock.id] = self, 
                                     "Failure of assertion at line 352, column 5 of macro called at line 650, column 5.")
                           /\ LET hasWaiters == conditionWaiters[0] # {} IN
                                LET waiter ==  IF conditionWaiters[0] # {}
                                              THEN CHOOSE t \in conditionWaiters[0] : TRUE
                                              ELSE NoTask IN
                                  /\ conditionWaiters' = [conditionWaiters EXCEPT ![0] = IF hasWaiters
                                                                                          THEN conditionWaiters[0] \ {waiter}
                                                                                          ELSE conditionWaiters[0]]
                                  /\ lockWaiters' = [lockWaiters EXCEPT ![Condition[0].lock.id] = IF hasWaiters
                                                                                                     THEN Append(lockWaiters[Condition[0].lock.id], waiter)
                                                                                                     ELSE lockWaiters[Condition[0].lock.id]]
                                  /\ taskState' = IF hasWaiters
                                                     THEN [taskState EXCEPT ![waiter] = [state |-> WaitingLock],
                                                                             ![self] = [state |-> Ready]]
                                                     ELSE [taskState EXCEPT ![self] = [state |-> Ready]]
                                  /\ runningTask' = NoTask
                                  /\ lastAction' = <<"ConditionNotify", 0, self>>
                           /\ pc' = [pc EXCEPT ![self] = "cn_release"]
                           /\ UNCHANGED << latchCount, lock, eventFired, 
                                           eventWaiters, queueItems, 
                                           queueClosed, joinWaiters, 
                                           workersCompleted, itemsProduced, 
                                           itemsConsumed, stack, latch_id, 
                                           queue_id_, item_to_put, 
                                           item_put_done, queue_id_q, item_got, 
                                           queue_id >>

cn_release(self) == /\ pc[self] = "cn_release"
                    /\ runningTask = self
                    /\ Assert(lock[(Condition[0].lock.id)] = self, 
                              "Failure of assertion at line 270, column 1 of macro called at line 654, column 5.")
                    /\ IF lockWaiters[(Condition[0].lock.id)] = << >>
                          THEN /\ lock' = [lock EXCEPT ![(Condition[0].lock.id)] = NoTask]
                               /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                               /\ runningTask' = NoTask
                               /\ lastAction' = <<"ReleaseLock", (Condition[0].lock.id), self>>
                               /\ UNCHANGED lockWaiters
                          ELSE /\ LET nextOwner == Head(lockWaiters[(Condition[0].lock.id)]) IN
                                    /\ lock' = [lock EXCEPT ![(Condition[0].lock.id)] = nextOwner]
                                    /\ lockWaiters' = [lockWaiters EXCEPT ![(Condition[0].lock.id)] = Tail(lockWaiters[(Condition[0].lock.id)])]
                                    /\ taskState' = [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                                                       ![self] = [state |-> Ready]]
                                    /\ runningTask' = NoTask
                                    /\ lastAction' = <<"ReleaseLock", (Condition[0].lock.id), self>>
                    /\ pc' = [pc EXCEPT ![self] = "cn_done"]
                    /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                    conditionWaiters, conditionFlag, 
                                    queueItems, queueClosed, joinWaiters, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, stack, latch_id, queue_id_, 
                                    item_to_put, item_put_done, queue_id_q, 
                                    item_got, queue_id >>

cn_done(self) == /\ pc[self] = "cn_done"
                 /\ runningTask = self
                 /\ taskState' =              [t \in Tasks |->
                                     CASE t = self                -> [state |-> Done]
                                         [] t \in joinWaiters[self] -> [state |-> Ready]
                                         [] OTHER                   -> taskState[t]
                                 ]
                 /\ joinWaiters' = [joinWaiters EXCEPT ![self] = {}]
                 /\ runningTask' = NoTask
                 /\ lastAction' = <<"Complete", self>>
                 /\ pc' = [pc EXCEPT ![self] = "Done"]
                 /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                 eventWaiters, conditionWaiters, conditionFlag, 
                                 queueItems, queueClosed, workersCompleted, 
                                 itemsProduced, itemsConsumed, stack, latch_id, 
                                 queue_id_, item_to_put, item_put_done, 
                                 queue_id_q, item_got, queue_id >>

ConditionNotifier(self) == cn_sleep(self) \/ cn_acquire(self)
                              \/ cn_set_and_notify(self)
                              \/ cn_release(self) \/ cn_done(self)

prod_put1(self) == /\ pc[self] = "prod_put1"
                   /\ runningTask = self
                   /\ itemsProduced' = itemsProduced + 1
                   /\ /\ item_to_put' = [item_to_put EXCEPT ![self] = "item1"]
                      /\ queue_id_' = [queue_id_ EXCEPT ![self] = 0]
                      /\ stack' = [stack EXCEPT ![self] = << [ procedure |->  "queue_put",
                                                               pc        |->  "prod_put2",
                                                               item_put_done |->  item_put_done[self],
                                                               queue_id_ |->  queue_id_[self],
                                                               item_to_put |->  item_to_put[self] ] >>
                                                           \o stack[self]]
                   /\ item_put_done' = [item_put_done EXCEPT ![self] = FALSE]
                   /\ pc' = [pc EXCEPT ![self] = "qput_acquire"]
                   /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                   lockWaiters, eventFired, eventWaiters, 
                                   conditionWaiters, conditionFlag, queueItems, 
                                   queueClosed, joinWaiters, workersCompleted, 
                                   itemsConsumed, lastAction, latch_id, 
                                   queue_id_q, item_got, queue_id >>

prod_put2(self) == /\ pc[self] = "prod_put2"
                   /\ runningTask = self
                   /\ itemsProduced' = itemsProduced + 1
                   /\ /\ item_to_put' = [item_to_put EXCEPT ![self] = "item2"]
                      /\ queue_id_' = [queue_id_ EXCEPT ![self] = 0]
                      /\ stack' = [stack EXCEPT ![self] = << [ procedure |->  "queue_put",
                                                               pc        |->  "prod_close",
                                                               item_put_done |->  item_put_done[self],
                                                               queue_id_ |->  queue_id_[self],
                                                               item_to_put |->  item_to_put[self] ] >>
                                                           \o stack[self]]
                   /\ item_put_done' = [item_put_done EXCEPT ![self] = FALSE]
                   /\ pc' = [pc EXCEPT ![self] = "qput_acquire"]
                   /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                   lockWaiters, eventFired, eventWaiters, 
                                   conditionWaiters, conditionFlag, queueItems, 
                                   queueClosed, joinWaiters, workersCompleted, 
                                   itemsConsumed, lastAction, latch_id, 
                                   queue_id_q, item_got, queue_id >>

prod_close(self) == /\ pc[self] = "prod_close"
                    /\ runningTask = self
                    /\ /\ queue_id' = [queue_id EXCEPT ![self] = 0]
                       /\ stack' = [stack EXCEPT ![self] = << [ procedure |->  "queue_close",
                                                                pc        |->  "prod_done",
                                                                queue_id  |->  queue_id[self] ] >>
                                                            \o stack[self]]
                    /\ pc' = [pc EXCEPT ![self] = "qclose_acquire"]
                    /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                    lockWaiters, eventFired, eventWaiters, 
                                    conditionWaiters, conditionFlag, 
                                    queueItems, queueClosed, joinWaiters, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, lastAction, latch_id, 
                                    queue_id_, item_to_put, item_put_done, 
                                    queue_id_q, item_got >>

prod_done(self) == /\ pc[self] = "prod_done"
                   /\ runningTask = self
                   /\ taskState' =              [t \in Tasks |->
                                       CASE t = self                -> [state |-> Done]
                                           [] t \in joinWaiters[self] -> [state |-> Ready]
                                           [] OTHER                   -> taskState[t]
                                   ]
                   /\ joinWaiters' = [joinWaiters EXCEPT ![self] = {}]
                   /\ runningTask' = NoTask
                   /\ lastAction' = <<"Complete", self>>
                   /\ pc' = [pc EXCEPT ![self] = "Done"]
                   /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                   eventWaiters, conditionWaiters, 
                                   conditionFlag, queueItems, queueClosed, 
                                   workersCompleted, itemsProduced, 
                                   itemsConsumed, stack, latch_id, queue_id_, 
                                   item_to_put, item_put_done, queue_id_q, 
                                   item_got, queue_id >>

Producer(self) == prod_put1(self) \/ prod_put2(self) \/ prod_close(self)
                     \/ prod_done(self)

cons_get1(self) == /\ pc[self] = "cons_get1"
                   /\ runningTask = self
                   /\ /\ queue_id_q' = [queue_id_q EXCEPT ![self] = 0]
                      /\ stack' = [stack EXCEPT ![self] = << [ procedure |->  "queue_get",
                                                               pc        |->  "cons_get2",
                                                               item_got  |->  item_got[self],
                                                               queue_id_q |->  queue_id_q[self] ] >>
                                                           \o stack[self]]
                   /\ item_got' = [item_got EXCEPT ![self] = NoTask]
                   /\ pc' = [pc EXCEPT ![self] = "qget_acquire"]
                   /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                   lockWaiters, eventFired, eventWaiters, 
                                   conditionWaiters, conditionFlag, queueItems, 
                                   queueClosed, joinWaiters, workersCompleted, 
                                   itemsProduced, itemsConsumed, lastAction, 
                                   latch_id, queue_id_, item_to_put, 
                                   item_put_done, queue_id >>

cons_get2(self) == /\ pc[self] = "cons_get2"
                   /\ runningTask = self
                   /\ itemsConsumed' = itemsConsumed + 1
                   /\ /\ queue_id_q' = [queue_id_q EXCEPT ![self] = 0]
                      /\ stack' = [stack EXCEPT ![self] = << [ procedure |->  "queue_get",
                                                               pc        |->  "cons_done",
                                                               item_got  |->  item_got[self],
                                                               queue_id_q |->  queue_id_q[self] ] >>
                                                           \o stack[self]]
                   /\ item_got' = [item_got EXCEPT ![self] = NoTask]
                   /\ pc' = [pc EXCEPT ![self] = "qget_acquire"]
                   /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                   lockWaiters, eventFired, eventWaiters, 
                                   conditionWaiters, conditionFlag, queueItems, 
                                   queueClosed, joinWaiters, workersCompleted, 
                                   itemsProduced, lastAction, latch_id, 
                                   queue_id_, item_to_put, item_put_done, 
                                   queue_id >>

cons_done(self) == /\ pc[self] = "cons_done"
                   /\ runningTask = self
                   /\ itemsConsumed' = itemsConsumed + 1
                   /\ taskState' =              [t \in Tasks |->
                                       CASE t = self                -> [state |-> Done]
                                           [] t \in joinWaiters[self] -> [state |-> Ready]
                                           [] OTHER                   -> taskState[t]
                                   ]
                   /\ joinWaiters' = [joinWaiters EXCEPT ![self] = {}]
                   /\ runningTask' = NoTask
                   /\ lastAction' = <<"Complete", self>>
                   /\ pc' = [pc EXCEPT ![self] = "Done"]
                   /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                   eventWaiters, conditionWaiters, 
                                   conditionFlag, queueItems, queueClosed, 
                                   workersCompleted, itemsProduced, stack, 
                                   latch_id, queue_id_, item_to_put, 
                                   item_put_done, queue_id_q, item_got, 
                                   queue_id >>

Consumer(self) == cons_get1(self) \/ cons_get2(self) \/ cons_done(self)

Next == Scheduler \/ ExternalWake
           \/ (\E self \in ProcSet:  \/ latch_countdown(self) \/ queue_put(self)
                                     \/ queue_get(self) \/ queue_close(self))
           \/ (\E self \in {0}: Main(self))
           \/ (\E self \in {1, 2}: Worker(self))
           \/ (\E self \in {3}: ConditionWaiter(self))
           \/ (\E self \in {4}: ConditionNotifier(self))
           \/ (\E self \in {5}: Producer(self))
           \/ (\E self \in {6}: Consumer(self))

Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(Scheduler)
        /\ WF_vars(ExternalWake)
        /\ \A self \in {0} : WF_vars(Main(self))
        /\ \A self \in {1, 2} : WF_vars(Worker(self)) /\ WF_vars(latch_countdown(self))
        /\ \A self \in {3} : WF_vars(ConditionWaiter(self))
        /\ \A self \in {4} : WF_vars(ConditionNotifier(self))
        /\ \A self \in {5} : /\ WF_vars(Producer(self))
                             /\ WF_vars(queue_put(self))
                             /\ WF_vars(queue_close(self))
        /\ \A self \in {6} : WF_vars(Consumer(self)) /\ WF_vars(queue_get(self))

\* END TRANSLATION 

======================
