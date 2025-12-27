------------------------ MODULE DummyTaskExample ------------------------
(*
 * PURPOSE: Formal verification of Flowno's AsyncQueue implementation
 *
 * This spec models the behavior of two concurrent tasks using a bounded AsyncQueue,
 * verifying that the queue operations (put/get/close) work correctly under all
 * possible interleavings in a cooperative single-threaded event loop.
 *
 * WHY THIS EXAMPLE:
 * - Tests bounded queue blocking behavior (put blocks when full, get blocks when empty)
 * - Tests direct-to-waiter optimization (put directly wakes blocked getter)
 * - Tests queue closure (close wakes all waiters with error)
 * - Verifies atomicity of wake+deliver operations
 * - Ensures only one task runs at a time (single-threaded constraint)
 * - Maps to EventLoop.py command processing architecture
 *
 * Python equivalent being modeled:
 *   q = AsyncQueue(maxsize=2)
 *
 *   async def dummy_task(_id: int):
 *       print(f"task id: {_id}")
 *       await q.put(f"hello from {_id}")
 *       recv = await q.get()
 *       print(f"task {_id} received: {recv}")
 *
 *   async def main():
 *       task1 = await spawn(dummy_task(1))
 *       task2 = await spawn(dummy_task(2))
 *       await task1.join()
 *       await task2.join()
 *       await q.close()
 *
 * VERIFICATION GOALS:
 * - Both tasks should receive messages (cross-task communication works)
 * - Messages may cross (task 1 might receive task 2's message)
 * - Queue invariants hold (bounded, waiters consistent)
 * - No deadlocks (both tasks eventually complete)
 * - Close properly wakes all blocked tasks with errors
 *
 * ARCHITECTURE:
 * This uses Approach A (EventLoop Handler) from the JoinExample exploration.
 * Tasks yield commands via macros, a Handler process makes all decisions about
 * blocking/immediate execution, matching the Python EventLoop.py implementation.
 *)
EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS NoTask, NoCmd, MaxQueueDepth

Tasks == {0, 1, 2}  \* 0=Main, 1=DummyTask1, 2=DummyTask2

(* --algorithm DummyTaskExample {
    variables
        \* === Core event loop state ===

        \* CRITICAL: Only one task runs at a time
        running = NoTask,

        \* Pending command from last yield (only one command pending at a time)
        \* Commands are processed synchronously: task yields -> handler processes -> task yields
        pendingCommand = NoCmd,

        \* Task states (matching EventLoop.tla predicates)
        taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"],

        \* Join tracking (for task.join() operations)
        joinWaiters = [t \in Tasks |-> {}],

        \* === Queue state (single queue, ID 0) ===

        \* Queue contents (FIFO order)
        queueContents = <<>>,

        \* Queue configuration
        queueMaxSize = MaxQueueDepth,
        queueClosed = FALSE,

        \* Blocked tasks waiting on queue operations
        getWaiters = {},    \* Tasks blocked on queue.get()
        putWaiters = {},    \* Tasks blocked on queue.put()

        \* Pending values for blocked putters (task -> value)
        \* When a task blocks on put (queue full), we save the value here
        \* so the handler can deliver it atomically when space opens
        pendingPut = [t \in Tasks |-> NoCmd],

        \* === Dummy task application state ===

        \* Values received by each dummy task (for verification)
        \* Used to check that both tasks receive messages
        dummyRecv = [t \in {1, 2} |-> -1];

    define {
        \* === State predicates (matching EventLoop.tla) ===

        IsNonexistent(t) == taskState[t] = "Nonexistent"
        IsReady(t) == taskState[t] = "Ready"
        IsReadyResuming(t) == taskState[t] = "ReadyResuming"
        IsRunning(t) == taskState[t] = "Running"
        IsWaitingGet(t) == taskState[t] = "WaitingGet"
        IsWaitingPut(t) == taskState[t] = "WaitingPut"
        IsJoining(t) == taskState[t] = "Joining"
        IsDone(t) == taskState[t] = "Done"
        IsError(t) == taskState[t] = "Error"

        IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)

        \* === Invariants ===

        \* CRITICAL: Only one task can be Running at a time
        AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1

        \* Running variable is consistent with taskState
        RunningConsistent ==
            /\ (running = NoTask <=> ~\E t \in Tasks : IsRunning(t))
            /\ (running # NoTask => IsRunning(running))

        \* Queue bounded by maxsize
        QueueBounded == Len(queueContents) <= queueMaxSize

        \* If queue has space, no tasks should be blocked on put
        PutWaitersConsistent ==
            (Len(queueContents) < queueMaxSize) => putWaiters = {}

        \* If queue has items, no tasks should be blocked on get
        GetWaitersConsistent ==
            (Len(queueContents) > 0) => getWaiters = {}

        \* Waiter states are consistent
        WaiterStateConsistent ==
            /\ \A t \in getWaiters : IsWaitingGet(t)
            /\ \A t \in putWaiters : IsWaitingPut(t)

        \* Pending puts are consistent with waiter state
        PendingPutConsistent ==
            \A t \in Tasks :
                (IsWaitingPut(t) => pendingPut[t] # NoCmd) /\
                (~IsWaitingPut(t) => pendingPut[t] = NoCmd)

        \* Closed queue has no waiters (they were all woken with error)
        ClosedQueueNoWaiters ==
            queueClosed => (getWaiters = {} /\ putWaiters = {})

        \* Join waiters are consistent
        JoinWaitersConsistent ==
            \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)

        \* === Value correlation invariants ===

        \* TEST INVARIANT: Each task should only receive the value it put
        \* This SHOULD be violated - messages can cross between tasks
        \* Task 1 puts 1, Task 2 puts 2, but they might receive each other's values
        TaskGetsOwnValue ==
            \A t \in {1, 2} : (dummyRecv[t] # -1) => (dummyRecv[t] = t)

        \* === Liveness properties ===

        \* Both dummy tasks should eventually receive a message
        EventuallyBothReceive == <>(dummyRecv[1] # -1 /\ dummyRecv[2] # -1)

        \* All tasks should eventually complete
        EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2))
    }

    \* === Macros for task operations ===
    \* These provide a clean, "mindless" mapping from Python await points to PlusCal

    macro yield_spawn(newTask) {
        assert pendingCommand = NoCmd;
        assert running = self;
        assert taskState[self] = "Running";
        pendingCommand := [cmd |-> "Spawn", task |-> self, newTask |-> newTask];
        running := NoTask;
    }

    macro yield_join(target) {
        assert pendingCommand = NoCmd;
        assert running = self;
        assert taskState[self] = "Running";
        pendingCommand := [cmd |-> "Join", task |-> self, target |-> target];
        running := NoTask;
    }

    macro yield_put(value) {
        assert pendingCommand = NoCmd;
        assert running = self;
        assert taskState[self] = "Running";
        pendingCommand := [cmd |-> "Put", task |-> self, value |-> value];
        running := NoTask;
    }

    macro yield_get() {
        assert pendingCommand = NoCmd;
        assert running = self;
        assert taskState[self] = "Running";
        pendingCommand := [cmd |-> "Get", task |-> self];
        running := NoTask;
    }

    macro yield_close() {
        assert pendingCommand = NoCmd;
        assert running = self;
        assert taskState[self] = "Running";
        pendingCommand := [cmd |-> "Close", task |-> self];
        running := NoTask;
    }

    macro yield_complete() {
        assert pendingCommand = NoCmd;
        assert running = self;
        assert taskState[self] = "Running";
        pendingCommand := [cmd |-> "Complete", task |-> self];
        running := NoTask;
    }

    \* === Background processes ===

    \* Scheduler: picks Ready/ReadyResuming tasks and makes them Running
    \* CRITICAL: Must wait for pending commands to be processed first
    fair process (Scheduler = 99)
    {
      sched:
        while (TRUE) {
            await pendingCommand = NoCmd /\ running = NoTask /\ \E t \in Tasks : IsSchedulable(t);
            with (t \in {t \in Tasks : IsSchedulable(t)}) {
                \* Assert: no task should already be Running
                assert ~\E t2 \in Tasks : taskState[t2] = "Running";
                running := t;
                taskState[t] := "Running";
            }
        }
    }

    \* EventLoopHandler: processes commands from tasks
    \* This is the heart of the event loop - all queue logic, spawning, joining, etc.
    fair process (EventLoopHandler = 98)
    {
      handle:
        while (TRUE) {
            await pendingCommand # NoCmd;
            \* Assert: the task that yielded the command released running
            assert running = NoTask;

            \* === Process the command ===

            if (pendingCommand.cmd = "Spawn") {
                \* Spawn: create new task and make both spawner and spawned Ready
                taskState := [t \in Tasks |->
                    IF t = pendingCommand.newTask THEN "Ready"
                    ELSE IF t = pendingCommand.task THEN "Ready"
                    ELSE taskState[t]];
            }

            else if (pendingCommand.cmd = "Join") {
                \* Join: check if target is done, either continue immediately or block
                if (IsDone(pendingCommand.target)) {
                    \* Target already done - continue immediately
                    taskState[pendingCommand.task] := "Ready";
                } else {
                    \* Target not done - block until it completes
                    taskState[pendingCommand.task] := "Joining";
                    joinWaiters[pendingCommand.target] :=
                        joinWaiters[pendingCommand.target] \union {pendingCommand.task};
                };
            }

            else if (pendingCommand.cmd = "Put") {
                \* Put: try to put value into queue
                \* Three cases: closed (error), full (block), has space (immediate)

                if (queueClosed) {
                    \* Queue closed - error
                    taskState[pendingCommand.task] := "Error";
                }
                else if (Len(queueContents) >= queueMaxSize) {
                    \* Queue full - block until space available
                    taskState[pendingCommand.task] := "WaitingPut";
                    putWaiters := putWaiters \union {pendingCommand.task};
                    pendingPut[pendingCommand.task] := pendingCommand.value;
                }
                else {
                    \* Queue has space - put immediately
                    \* Optimization: if getter is waiting, deliver directly to them

                    if (getWaiters # {}) {
                        \* Direct-to-waiter: atomically wake getter with value
                        with (waiter \in getWaiters) {
                            getWaiters := getWaiters \ {waiter};
                            dummyRecv[waiter] := pendingCommand.value;
                            taskState := [t \in Tasks |->
                                IF t = waiter THEN "ReadyResuming"
                                ELSE IF t = pendingCommand.task THEN "Ready"
                                ELSE taskState[t]];
                        };
                    } else {
                        \* No waiting getter - add to queue
                        queueContents := Append(queueContents, pendingCommand.value);
                        taskState[pendingCommand.task] := "Ready";
                    };
                };
            }

            else if (pendingCommand.cmd = "Get") {
                \* Get: try to get value from queue
                \* Three cases: closed+empty (error), has items (immediate), empty (block)

                if (queueClosed /\ Len(queueContents) = 0) {
                    \* Closed and empty - error
                    taskState[pendingCommand.task] := "Error";
                }
                else if (Len(queueContents) > 0) {
                    \* Queue has items - get immediately
                    \* Optimization: if putter is waiting, take their value and wake them

                    dummyRecv[pendingCommand.task] := Head(queueContents);

                    if (putWaiters # {}) {
                        \* Wake a blocked putter: take head, append putter's value
                        with (putter \in putWaiters) {
                            putWaiters := putWaiters \ {putter};
                            queueContents := Append(Tail(queueContents), pendingPut[putter]);
                            pendingPut[putter] := NoCmd;
                            taskState := [t \in Tasks |->
                                IF t = putter THEN "ReadyResuming"
                                ELSE IF t = pendingCommand.task THEN "Ready"
                                ELSE taskState[t]];
                        };
                    } else {
                        \* No waiting putter - just consume from queue
                        queueContents := Tail(queueContents);
                        taskState[pendingCommand.task] := "Ready";
                    };
                }
                else {
                    \* Queue empty - block until item available
                    taskState[pendingCommand.task] := "WaitingGet";
                    getWaiters := getWaiters \union {pendingCommand.task};
                };
            }

            else if (pendingCommand.cmd = "Close") {
                \* Close: close queue and wake all waiters with error
                queueClosed := TRUE;
                taskState := [t \in Tasks |->
                    IF t \in getWaiters \union putWaiters THEN "Error"
                    ELSE IF t = pendingCommand.task THEN "Ready"
                    ELSE taskState[t]];
                \* Clear all waiters
                getWaiters := {};
                putWaiters := {};
                \* Clear pending puts (waiters got error)
                pendingPut := [t \in Tasks |->
                    IF taskState[t] = "Error" THEN NoCmd
                    ELSE pendingPut[t]];
            }

            else if (pendingCommand.cmd = "Complete") {
                \* Complete: mark task done and wake all joiners
                taskState := [t \in Tasks |->
                    IF t = pendingCommand.task THEN "Done"
                    ELSE IF t \in joinWaiters[pendingCommand.task] THEN "ReadyResuming"
                    ELSE taskState[t]];
                joinWaiters[pendingCommand.task] := {};
            };

            \* Command processed - clear pending
            pendingCommand := NoCmd;
        }
    }

    \* === Task processes ===

    \* Main task: spawns two dummy tasks, waits for them, closes queue
    fair process (Main \in {0})
    {
      main_spawn1:
        await running = self;
        yield_spawn(1);

      main_spawn2:
        await running = self;
        yield_spawn(2);

      main_join1:
        await running = self;
        yield_join(1);

      main_join2:
        await running = self;
        yield_join(2);

      main_close:
        await running = self;
        yield_close();

      main_complete:
        await running = self;
        yield_complete();
    }

    \* Dummy tasks: put own ID to queue, get a value, complete
    \* Each task puts its own ID (1 or 2) and receives a value.
    \* Values may cross: Task 1 might receive 2, Task 2 might receive 1.
    fair process (DummyTask \in {1, 2})
    {
      dummy_put:
        await running = self;
        yield_put(self);  \* Each task puts its own ID

      dummy_get:
        await running = self;
        yield_get();

      dummy_complete:
        await running = self;
        yield_complete();
    }
} *)

\* BEGIN TRANSLATION
VARIABLES running, pendingCommand, taskState, joinWaiters, queueContents, 
          queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, 
          dummyRecv, pc

(* define statement *)
IsNonexistent(t) == taskState[t] = "Nonexistent"
IsReady(t) == taskState[t] = "Ready"
IsReadyResuming(t) == taskState[t] = "ReadyResuming"
IsRunning(t) == taskState[t] = "Running"
IsWaitingGet(t) == taskState[t] = "WaitingGet"
IsWaitingPut(t) == taskState[t] = "WaitingPut"
IsJoining(t) == taskState[t] = "Joining"
IsDone(t) == taskState[t] = "Done"
IsError(t) == taskState[t] = "Error"

IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)




AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1


RunningConsistent ==
    /\ (running = NoTask <=> ~\E t \in Tasks : IsRunning(t))
    /\ (running # NoTask => IsRunning(running))


QueueBounded == Len(queueContents) <= queueMaxSize


PutWaitersConsistent ==
    (Len(queueContents) < queueMaxSize) => putWaiters = {}


GetWaitersConsistent ==
    (Len(queueContents) > 0) => getWaiters = {}


WaiterStateConsistent ==
    /\ \A t \in getWaiters : IsWaitingGet(t)
    /\ \A t \in putWaiters : IsWaitingPut(t)


PendingPutConsistent ==
    \A t \in Tasks :
        (IsWaitingPut(t) => pendingPut[t] # NoCmd) /\
        (~IsWaitingPut(t) => pendingPut[t] = NoCmd)


ClosedQueueNoWaiters ==
    queueClosed => (getWaiters = {} /\ putWaiters = {})


JoinWaitersConsistent ==
    \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)






TaskGetsOwnValue ==
    \A t \in {1, 2} : (dummyRecv[t] # -1) => (dummyRecv[t] = t)




EventuallyBothReceive == <>(dummyRecv[1] # -1 /\ dummyRecv[2] # -1)


EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2))


vars == << running, pendingCommand, taskState, joinWaiters, queueContents, 
           queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, 
           dummyRecv, pc >>

ProcSet == {99} \cup {98} \cup ({0}) \cup ({1, 2})

Init == (* Global variables *)
        /\ running = NoTask
        /\ pendingCommand = NoCmd
        /\ taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"]
        /\ joinWaiters = [t \in Tasks |-> {}]
        /\ queueContents = <<>>
        /\ queueMaxSize = MaxQueueDepth
        /\ queueClosed = FALSE
        /\ getWaiters = {}
        /\ putWaiters = {}
        /\ pendingPut = [t \in Tasks |-> NoCmd]
        /\ dummyRecv = [t \in {1, 2} |-> -1]
        /\ pc = [self \in ProcSet |-> CASE self = 99 -> "sched"
                                        [] self = 98 -> "handle"
                                        [] self \in {0} -> "main_spawn1"
                                        [] self \in {1, 2} -> "dummy_put"]

sched == /\ pc[99] = "sched"
         /\ pendingCommand = NoCmd /\ running = NoTask /\ \E t \in Tasks : IsSchedulable(t)
         /\ \E t \in {t \in Tasks : IsSchedulable(t)}:
              /\ Assert(~\E t2 \in Tasks : taskState[t2] = "Running", 
                        "Failure of assertion at line 226, column 17.")
              /\ running' = t
              /\ taskState' = [taskState EXCEPT ![t] = "Running"]
         /\ pc' = [pc EXCEPT ![99] = "sched"]
         /\ UNCHANGED << pendingCommand, joinWaiters, queueContents, 
                         queueMaxSize, queueClosed, getWaiters, putWaiters, 
                         pendingPut, dummyRecv >>

Scheduler == sched

handle == /\ pc[98] = "handle"
          /\ pendingCommand # NoCmd
          /\ Assert(running = NoTask, 
                    "Failure of assertion at line 241, column 13.")
          /\ IF pendingCommand.cmd = "Spawn"
                THEN /\ taskState' =          [t \in Tasks |->
                                     IF t = pendingCommand.newTask THEN "Ready"
                                     ELSE IF t = pendingCommand.task THEN "Ready"
                                     ELSE taskState[t]]
                     /\ UNCHANGED << joinWaiters, queueContents, queueClosed, 
                                     getWaiters, putWaiters, pendingPut, 
                                     dummyRecv >>
                ELSE /\ IF pendingCommand.cmd = "Join"
                           THEN /\ IF IsDone(pendingCommand.target)
                                      THEN /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                           /\ UNCHANGED joinWaiters
                                      ELSE /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Joining"]
                                           /\ joinWaiters' = [joinWaiters EXCEPT ![pendingCommand.target] = joinWaiters[pendingCommand.target] \union {pendingCommand.task}]
                                /\ UNCHANGED << queueContents, queueClosed, 
                                                getWaiters, putWaiters, 
                                                pendingPut, dummyRecv >>
                           ELSE /\ IF pendingCommand.cmd = "Put"
                                      THEN /\ IF queueClosed
                                                 THEN /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Error"]
                                                      /\ UNCHANGED << queueContents, 
                                                                      getWaiters, 
                                                                      putWaiters, 
                                                                      pendingPut, 
                                                                      dummyRecv >>
                                                 ELSE /\ IF Len(queueContents) >= queueMaxSize
                                                            THEN /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "WaitingPut"]
                                                                 /\ putWaiters' = (putWaiters \union {pendingCommand.task})
                                                                 /\ pendingPut' = [pendingPut EXCEPT ![pendingCommand.task] = pendingCommand.value]
                                                                 /\ UNCHANGED << queueContents, 
                                                                                 getWaiters, 
                                                                                 dummyRecv >>
                                                            ELSE /\ IF getWaiters # {}
                                                                       THEN /\ \E waiter \in getWaiters:
                                                                                 /\ getWaiters' = getWaiters \ {waiter}
                                                                                 /\ dummyRecv' = [dummyRecv EXCEPT ![waiter] = pendingCommand.value]
                                                                                 /\ taskState' =          [t \in Tasks |->
                                                                                                 IF t = waiter THEN "ReadyResuming"
                                                                                                 ELSE IF t = pendingCommand.task THEN "Ready"
                                                                                                 ELSE taskState[t]]
                                                                            /\ UNCHANGED queueContents
                                                                       ELSE /\ queueContents' = Append(queueContents, pendingCommand.value)
                                                                            /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                                                            /\ UNCHANGED << getWaiters, 
                                                                                            dummyRecv >>
                                                                 /\ UNCHANGED << putWaiters, 
                                                                                 pendingPut >>
                                           /\ UNCHANGED << joinWaiters, 
                                                           queueClosed >>
                                      ELSE /\ IF pendingCommand.cmd = "Get"
                                                 THEN /\ IF queueClosed /\ Len(queueContents) = 0
                                                            THEN /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Error"]
                                                                 /\ UNCHANGED << queueContents, 
                                                                                 getWaiters, 
                                                                                 putWaiters, 
                                                                                 pendingPut, 
                                                                                 dummyRecv >>
                                                            ELSE /\ IF Len(queueContents) > 0
                                                                       THEN /\ dummyRecv' = [dummyRecv EXCEPT ![pendingCommand.task] = Head(queueContents)]
                                                                            /\ IF putWaiters # {}
                                                                                  THEN /\ \E putter \in putWaiters:
                                                                                            /\ putWaiters' = putWaiters \ {putter}
                                                                                            /\ queueContents' = Append(Tail(queueContents), pendingPut[putter])
                                                                                            /\ pendingPut' = [pendingPut EXCEPT ![putter] = NoCmd]
                                                                                            /\ taskState' =          [t \in Tasks |->
                                                                                                            IF t = putter THEN "ReadyResuming"
                                                                                                            ELSE IF t = pendingCommand.task THEN "Ready"
                                                                                                            ELSE taskState[t]]
                                                                                  ELSE /\ queueContents' = Tail(queueContents)
                                                                                       /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                                                                       /\ UNCHANGED << putWaiters, 
                                                                                                       pendingPut >>
                                                                            /\ UNCHANGED getWaiters
                                                                       ELSE /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "WaitingGet"]
                                                                            /\ getWaiters' = (getWaiters \union {pendingCommand.task})
                                                                            /\ UNCHANGED << queueContents, 
                                                                                            putWaiters, 
                                                                                            pendingPut, 
                                                                                            dummyRecv >>
                                                      /\ UNCHANGED << joinWaiters, 
                                                                      queueClosed >>
                                                 ELSE /\ IF pendingCommand.cmd = "Close"
                                                            THEN /\ queueClosed' = TRUE
                                                                 /\ taskState' =          [t \in Tasks |->
                                                                                 IF t \in getWaiters \union putWaiters THEN "Error"
                                                                                 ELSE IF t = pendingCommand.task THEN "Ready"
                                                                                 ELSE taskState[t]]
                                                                 /\ getWaiters' = {}
                                                                 /\ putWaiters' = {}
                                                                 /\ pendingPut' =           [t \in Tasks |->
                                                                                  IF taskState'[t] = "Error" THEN NoCmd
                                                                                  ELSE pendingPut[t]]
                                                                 /\ UNCHANGED joinWaiters
                                                            ELSE /\ IF pendingCommand.cmd = "Complete"
                                                                       THEN /\ taskState' =          [t \in Tasks |->
                                                                                            IF t = pendingCommand.task THEN "Done"
                                                                                            ELSE IF t \in joinWaiters[pendingCommand.task] THEN "ReadyResuming"
                                                                                            ELSE taskState[t]]
                                                                            /\ joinWaiters' = [joinWaiters EXCEPT ![pendingCommand.task] = {}]
                                                                       ELSE /\ TRUE
                                                                            /\ UNCHANGED << taskState, 
                                                                                            joinWaiters >>
                                                                 /\ UNCHANGED << queueClosed, 
                                                                                 getWaiters, 
                                                                                 putWaiters, 
                                                                                 pendingPut >>
                                                      /\ UNCHANGED << queueContents, 
                                                                      dummyRecv >>
          /\ pendingCommand' = NoCmd
          /\ pc' = [pc EXCEPT ![98] = "handle"]
          /\ UNCHANGED << running, queueMaxSize >>

EventLoopHandler == handle

main_spawn1(self) == /\ pc[self] = "main_spawn1"
                     /\ running = self
                     /\ Assert(pendingCommand = NoCmd, 
                               "Failure of assertion at line 168, column 9 of macro called at line 377, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 169, column 9 of macro called at line 377, column 9.")
                     /\ Assert(taskState[self] = "Running", 
                               "Failure of assertion at line 170, column 9 of macro called at line 377, column 9.")
                     /\ pendingCommand' = [cmd |-> "Spawn", task |-> self, newTask |-> 1]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_spawn2"]
                     /\ UNCHANGED << taskState, joinWaiters, queueContents, 
                                     queueMaxSize, queueClosed, getWaiters, 
                                     putWaiters, pendingPut, dummyRecv >>

main_spawn2(self) == /\ pc[self] = "main_spawn2"
                     /\ running = self
                     /\ Assert(pendingCommand = NoCmd, 
                               "Failure of assertion at line 168, column 9 of macro called at line 381, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 169, column 9 of macro called at line 381, column 9.")
                     /\ Assert(taskState[self] = "Running", 
                               "Failure of assertion at line 170, column 9 of macro called at line 381, column 9.")
                     /\ pendingCommand' = [cmd |-> "Spawn", task |-> self, newTask |-> 2]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_join1"]
                     /\ UNCHANGED << taskState, joinWaiters, queueContents, 
                                     queueMaxSize, queueClosed, getWaiters, 
                                     putWaiters, pendingPut, dummyRecv >>

main_join1(self) == /\ pc[self] = "main_join1"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 176, column 9 of macro called at line 385, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 177, column 9 of macro called at line 385, column 9.")
                    /\ Assert(taskState[self] = "Running", 
                              "Failure of assertion at line 178, column 9 of macro called at line 385, column 9.")
                    /\ pendingCommand' = [cmd |-> "Join", task |-> self, target |-> 1]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_join2"]
                    /\ UNCHANGED << taskState, joinWaiters, queueContents, 
                                    queueMaxSize, queueClosed, getWaiters, 
                                    putWaiters, pendingPut, dummyRecv >>

main_join2(self) == /\ pc[self] = "main_join2"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 176, column 9 of macro called at line 389, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 177, column 9 of macro called at line 389, column 9.")
                    /\ Assert(taskState[self] = "Running", 
                              "Failure of assertion at line 178, column 9 of macro called at line 389, column 9.")
                    /\ pendingCommand' = [cmd |-> "Join", task |-> self, target |-> 2]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_close"]
                    /\ UNCHANGED << taskState, joinWaiters, queueContents, 
                                    queueMaxSize, queueClosed, getWaiters, 
                                    putWaiters, pendingPut, dummyRecv >>

main_close(self) == /\ pc[self] = "main_close"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 200, column 9 of macro called at line 393, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 201, column 9 of macro called at line 393, column 9.")
                    /\ Assert(taskState[self] = "Running", 
                              "Failure of assertion at line 202, column 9 of macro called at line 393, column 9.")
                    /\ pendingCommand' = [cmd |-> "Close", task |-> self]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_complete"]
                    /\ UNCHANGED << taskState, joinWaiters, queueContents, 
                                    queueMaxSize, queueClosed, getWaiters, 
                                    putWaiters, pendingPut, dummyRecv >>

main_complete(self) == /\ pc[self] = "main_complete"
                       /\ running = self
                       /\ Assert(pendingCommand = NoCmd, 
                                 "Failure of assertion at line 208, column 9 of macro called at line 397, column 9.")
                       /\ Assert(running = self, 
                                 "Failure of assertion at line 209, column 9 of macro called at line 397, column 9.")
                       /\ Assert(taskState[self] = "Running", 
                                 "Failure of assertion at line 210, column 9 of macro called at line 397, column 9.")
                       /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                       /\ running' = NoTask
                       /\ pc' = [pc EXCEPT ![self] = "Done"]
                       /\ UNCHANGED << taskState, joinWaiters, queueContents, 
                                       queueMaxSize, queueClosed, getWaiters, 
                                       putWaiters, pendingPut, dummyRecv >>

Main(self) == main_spawn1(self) \/ main_spawn2(self) \/ main_join1(self)
                 \/ main_join2(self) \/ main_close(self)
                 \/ main_complete(self)

dummy_put(self) == /\ pc[self] = "dummy_put"
                   /\ running = self
                   /\ Assert(pendingCommand = NoCmd, 
                             "Failure of assertion at line 184, column 9 of macro called at line 407, column 9.")
                   /\ Assert(running = self, 
                             "Failure of assertion at line 185, column 9 of macro called at line 407, column 9.")
                   /\ Assert(taskState[self] = "Running", 
                             "Failure of assertion at line 186, column 9 of macro called at line 407, column 9.")
                   /\ pendingCommand' = [cmd |-> "Put", task |-> self, value |-> self]
                   /\ running' = NoTask
                   /\ pc' = [pc EXCEPT ![self] = "dummy_get"]
                   /\ UNCHANGED << taskState, joinWaiters, queueContents, 
                                   queueMaxSize, queueClosed, getWaiters, 
                                   putWaiters, pendingPut, dummyRecv >>

dummy_get(self) == /\ pc[self] = "dummy_get"
                   /\ running = self
                   /\ Assert(pendingCommand = NoCmd, 
                             "Failure of assertion at line 192, column 9 of macro called at line 411, column 9.")
                   /\ Assert(running = self, 
                             "Failure of assertion at line 193, column 9 of macro called at line 411, column 9.")
                   /\ Assert(taskState[self] = "Running", 
                             "Failure of assertion at line 194, column 9 of macro called at line 411, column 9.")
                   /\ pendingCommand' = [cmd |-> "Get", task |-> self]
                   /\ running' = NoTask
                   /\ pc' = [pc EXCEPT ![self] = "dummy_complete"]
                   /\ UNCHANGED << taskState, joinWaiters, queueContents, 
                                   queueMaxSize, queueClosed, getWaiters, 
                                   putWaiters, pendingPut, dummyRecv >>

dummy_complete(self) == /\ pc[self] = "dummy_complete"
                        /\ running = self
                        /\ Assert(pendingCommand = NoCmd, 
                                  "Failure of assertion at line 208, column 9 of macro called at line 415, column 9.")
                        /\ Assert(running = self, 
                                  "Failure of assertion at line 209, column 9 of macro called at line 415, column 9.")
                        /\ Assert(taskState[self] = "Running", 
                                  "Failure of assertion at line 210, column 9 of macro called at line 415, column 9.")
                        /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                        /\ running' = NoTask
                        /\ pc' = [pc EXCEPT ![self] = "Done"]
                        /\ UNCHANGED << taskState, joinWaiters, queueContents, 
                                        queueMaxSize, queueClosed, getWaiters, 
                                        putWaiters, pendingPut, dummyRecv >>

DummyTask(self) == dummy_put(self) \/ dummy_get(self)
                      \/ dummy_complete(self)

Next == Scheduler \/ EventLoopHandler
           \/ (\E self \in {0}: Main(self))
           \/ (\E self \in {1, 2}: DummyTask(self))

Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(Scheduler)
        /\ WF_vars(EventLoopHandler)
        /\ \A self \in {0} : WF_vars(Main(self))
        /\ \A self \in {1, 2} : WF_vars(DummyTask(self))

\* END TRANSLATION

=============================================================================
