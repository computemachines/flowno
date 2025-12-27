------------------------ MODULE LockExample_Fail_ForgotTransferOwnership ------------------------
(*
 * PURPOSE: NEGATIVE TEST - Forgot to transfer ownership to next waiter
 * EXPECTED: Should violate MutualExclusion or LockOwnerConsistent
 *
 * This spec models the behavior of three concurrent tasks competing for a lock,
 * verifying that lock acquire/release operations maintain mutual exclusion
 * under all possible interleavings in a cooperative single-threaded event loop.
 *
 * WHY THIS EXAMPLE:
 * - Tests mutual exclusion (only one task in critical section at a time)
 * - Tests FIFO fairness (waiters served in order)
 * - Tests lock ownership tracking
 * - Verifies atomicity of acquire and release operations
 * - Ensures only one task runs at a time (single-threaded constraint)
 * - Maps to EventLoop.py command processing architecture
 *
 * Python equivalent being modeled:
 *   lock = Lock()
 *   shared_counter = [0]
 *
 *   async def worker(id: int):
 *       await lock.acquire()
 *       try:
 *           # Critical section
 *           shared_counter[0] += 1
 *       finally:
 *           await lock.release()
 *
 *   async def main():
 *       task1 = await spawn(worker(1))
 *       task2 = await spawn(worker(2))
 *       task3 = await spawn(worker(3))
 *       await task1.join()
 *       await task2.join()
 *       await task3.join()
 *
 * VERIFICATION GOALS:
 * - At most one task holds the lock at any time (mutual exclusion)
 * - All tasks eventually enter and exit critical section
 * - FIFO ordering is maintained
 * - Only lock owner can release the lock
 * - No deadlocks
 *
 * ARCHITECTURE:
 * This uses Approach A (EventLoop Handler) from the JoinExample exploration.
 * Tasks yield commands via macros, a Handler process makes all decisions about
 * blocking/immediate execution, matching the Python EventLoop.py implementation.
 *)
EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS NoTask, NoCmd

Tasks == {0, 1, 2, 3}  \* 0=Main, 1-3=Workers

(* --algorithm LockExample {
    variables
        \* === Core event loop state ===

        \* CRITICAL: Only one task runs at a time
        running = NoTask,

        \* Pending command from last yield (only one command pending at a time)
        pendingCommand = NoCmd,

        \* Task states (matching EventLoop.tla predicates)
        taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"],

        \* Join tracking (for task.join() operations)
        joinWaiters = [t \in Tasks |-> {}],

        \* === Lock state ===

        \* Lock ownership (NoTask if unlocked, task ID if locked)
        lockOwner = NoTask,

        \* Blocked tasks waiting on lock.acquire() (FIFO queue)
        lockWaiters = <<>>,

        \* === Application state for verification ===

        \* Track which tasks entered critical section (for verification)
        enteredCritical = {},
        \* Track which tasks exited critical section (for verification)
        exitedCritical = {},
        \* Current task in critical section (NoTask if none)
        inCriticalSection = NoTask,
        \* Shared counter (simulates critical section work)
        sharedCounter = 0;

    define {
        \* === State predicates (matching EventLoop.tla) ===

        IsNonexistent(t) == taskState[t] = "Nonexistent"
        IsReady(t) == taskState[t] = "Ready"
        IsReadyResuming(t) == taskState[t] = "ReadyResuming"
        IsRunning(t) == taskState[t] = "Running"
        IsWaitingLock(t) == taskState[t] = "WaitingLock"
        IsJoining(t) == taskState[t] = "Joining"
        IsDone(t) == taskState[t] = "Done"
        IsError(t) == taskState[t] = "Error"

        IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)

        \* === Invariants ===

        \* CRITICAL: Only one task can be Running at a time
        AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1

        \* Running variable is consistent with taskState
        RunningConsistent ==
            /\ (running # NoTask => IsRunning(running))
            /\ (running = NoTask /\ pendingCommand = NoCmd => ~\E t \in Tasks : IsRunning(t))

        \* MUTUAL EXCLUSION: At most one task in critical section
        MutualExclusion == Cardinality({t \in Tasks : inCriticalSection = t}) <= 1

        \* Lock ownership is consistent
        LockOwnerConsistent ==
            \/ lockOwner = NoTask
            \/ (IsReady(lockOwner) \/ IsRunning(lockOwner) \/ IsReadyResuming(lockOwner))

        \* Lock waiters are consistent with task states
        LockWaitersConsistent ==
            \A i \in 1..Len(lockWaiters) : IsWaitingLock(lockWaiters[i])

        \* If lock is unlocked, no waiters should exist
        UnlockedNoWaiters ==
            (lockOwner = NoTask) => (lockWaiters = <<>>)

        \* Only lock owner can be in critical section
        OnlyOwnerInCritical ==
            (inCriticalSection # NoTask) => (inCriticalSection = lockOwner)

        \* Join waiters are consistent
        JoinWaitersConsistent ==
            \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)

        \* === Liveness properties ===

        \* All workers should eventually enter critical section
        EventuallyAllEnter == <>(enteredCritical = {1, 2, 3})

        \* All workers should eventually exit critical section
        EventuallyAllExit == <>(exitedCritical = {1, 2, 3})

        \* All tasks should eventually complete
        EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2) /\ IsDone(3))

        \* Counter should reach 3 (all workers incremented)
        EventuallyCounterReaches3 == <>(sharedCounter = 3)
    }

    \* === Macros for task operations ===

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

    macro yield_lock_acquire() {
        assert pendingCommand = NoCmd;
        assert running = self;
        assert taskState[self] = "Running";
        pendingCommand := [cmd |-> "LockAcquire", task |-> self];
        running := NoTask;
    }

    macro yield_lock_release() {
        assert pendingCommand = NoCmd;
        assert running = self;
        assert taskState[self] = "Running";
        pendingCommand := [cmd |-> "LockRelease", task |-> self];
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
    fair process (Scheduler = 99)
    {
      sched:
        while (TRUE) {
            await pendingCommand = NoCmd /\ running = NoTask /\ \E t \in Tasks : IsSchedulable(t);
            with (t \in {t \in Tasks : IsSchedulable(t)}) {
                assert ~\E t2 \in Tasks : taskState[t2] = "Running";
                running := t;
                taskState[t] := "Running";
            }
        }
    }

    \* EventLoopHandler: processes commands from tasks
    fair process (EventLoopHandler = 98)
    {
      handle:
        while (TRUE) {
            await pendingCommand # NoCmd;
            assert running = NoTask;

            \* === Process the command ===

            if (pendingCommand.cmd = "Spawn") {
                taskState := [t \in Tasks |->
                    IF t = pendingCommand.newTask THEN "Ready"
                    ELSE IF t = pendingCommand.task THEN "Ready"
                    ELSE taskState[t]];
            }

            else if (pendingCommand.cmd = "Join") {
                if (IsDone(pendingCommand.target)) {
                    taskState[pendingCommand.task] := "Ready";
                } else {
                    taskState[pendingCommand.task] := "Joining";
                    joinWaiters[pendingCommand.target] :=
                        joinWaiters[pendingCommand.target] \union {pendingCommand.task};
                };
            }

            else if (pendingCommand.cmd = "LockAcquire") {
                \* Acquire lock: check if available
                if (lockOwner = NoTask) {
                    \* Lock available - acquire immediately
                    lockOwner := pendingCommand.task;
                    taskState[pendingCommand.task] := "Ready";
                } else {
                    \* Lock held - block in FIFO queue
                    taskState[pendingCommand.task] := "WaitingLock";
                    lockWaiters := Append(lockWaiters, pendingCommand.task);
                };
            }

            else if (pendingCommand.cmd = "LockRelease") {
                \* Release lock: only owner can release
                assert lockOwner = pendingCommand.task;

                if (lockWaiters # <<>>) {
                    \* Wake next waiter in FIFO order
                    \* BUG: Forgot to transfer ownership!
                    with (waiter = Head(lockWaiters)) {
                        lockWaiters := Tail(lockWaiters);
                        \* lockOwner := waiter;  \* BUG: commented out!
                        taskState := [t \in Tasks |->
                            IF t = waiter THEN "ReadyResuming"
                            ELSE IF t = pendingCommand.task THEN "Ready"
                            ELSE taskState[t]];
                    };
                } else {
                    \* No waiters - unlock
                    lockOwner := NoTask;
                    taskState[pendingCommand.task] := "Ready";
                };
            }

            else if (pendingCommand.cmd = "Complete") {
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

    \* Main task: spawns three workers, waits for them
    fair process (Main \in {0})
    {
      main_spawn1:
        await running = self;
        yield_spawn(1);

      main_spawn2:
        await running = self;
        yield_spawn(2);

      main_spawn3:
        await running = self;
        yield_spawn(3);

      main_join1:
        await running = self;
        yield_join(1);

      main_join2:
        await running = self;
        yield_join(2);

      main_join3:
        await running = self;
        yield_join(3);

      main_complete:
        await running = self;
        yield_complete();
    }

    \* Worker tasks: acquire lock, enter critical section, increment counter, release lock
    fair process (Worker \in {1, 2, 3})
    {
      worker_acquire:
        await running = self;
        yield_lock_acquire();

      worker_critical_enter:
        await running = self;
        enteredCritical := enteredCritical \union {self};
        inCriticalSection := self;

      worker_critical_work:
        await running = self;
        sharedCounter := sharedCounter + 1;

      worker_critical_exit:
        await running = self;
        exitedCritical := exitedCritical \union {self};
        inCriticalSection := NoTask;

      worker_release:
        await running = self;
        yield_lock_release();

      worker_complete:
        await running = self;
        yield_complete();
    }
} *)

\* BEGIN TRANSLATION
VARIABLES running, pendingCommand, taskState, joinWaiters, lockOwner, 
          lockWaiters, enteredCritical, exitedCritical, inCriticalSection, 
          sharedCounter, pc

(* define statement *)
IsNonexistent(t) == taskState[t] = "Nonexistent"
IsReady(t) == taskState[t] = "Ready"
IsReadyResuming(t) == taskState[t] = "ReadyResuming"
IsRunning(t) == taskState[t] = "Running"
IsWaitingLock(t) == taskState[t] = "WaitingLock"
IsJoining(t) == taskState[t] = "Joining"
IsDone(t) == taskState[t] = "Done"
IsError(t) == taskState[t] = "Error"

IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)




AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1


RunningConsistent ==
    /\ (running # NoTask => IsRunning(running))
    /\ (running = NoTask /\ pendingCommand = NoCmd => ~\E t \in Tasks : IsRunning(t))


MutualExclusion == Cardinality({t \in Tasks : inCriticalSection = t}) <= 1


LockOwnerConsistent ==
    \/ lockOwner = NoTask
    \/ (IsReady(lockOwner) \/ IsRunning(lockOwner) \/ IsReadyResuming(lockOwner))


LockWaitersConsistent ==
    \A i \in 1..Len(lockWaiters) : IsWaitingLock(lockWaiters[i])


UnlockedNoWaiters ==
    (lockOwner = NoTask) => (lockWaiters = <<>>)


OnlyOwnerInCritical ==
    (inCriticalSection # NoTask) => (inCriticalSection = lockOwner)


JoinWaitersConsistent ==
    \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)




EventuallyAllEnter == <>(enteredCritical = {1, 2, 3})


EventuallyAllExit == <>(exitedCritical = {1, 2, 3})


EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2) /\ IsDone(3))


EventuallyCounterReaches3 == <>(sharedCounter = 3)


vars == << running, pendingCommand, taskState, joinWaiters, lockOwner, 
           lockWaiters, enteredCritical, exitedCritical, inCriticalSection, 
           sharedCounter, pc >>

ProcSet == {99} \cup {98} \cup ({0}) \cup ({1, 2, 3})

Init == (* Global variables *)
        /\ running = NoTask
        /\ pendingCommand = NoCmd
        /\ taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"]
        /\ joinWaiters = [t \in Tasks |-> {}]
        /\ lockOwner = NoTask
        /\ lockWaiters = <<>>
        /\ enteredCritical = {}
        /\ exitedCritical = {}
        /\ inCriticalSection = NoTask
        /\ sharedCounter = 0
        /\ pc = [self \in ProcSet |-> CASE self = 99 -> "sched"
                                        [] self = 98 -> "handle"
                                        [] self \in {0} -> "main_spawn1"
                                        [] self \in {1, 2, 3} -> "worker_acquire"]

sched == /\ pc[99] = "sched"
         /\ pendingCommand = NoCmd /\ running = NoTask /\ \E t \in Tasks : IsSchedulable(t)
         /\ \E t \in {t \in Tasks : IsSchedulable(t)}:
              /\ Assert(~\E t2 \in Tasks : taskState[t2] = "Running", 
                        "Failure of assertion at line 205, column 17.")
              /\ running' = t
              /\ taskState' = [taskState EXCEPT ![t] = "Running"]
         /\ pc' = [pc EXCEPT ![99] = "sched"]
         /\ UNCHANGED << pendingCommand, joinWaiters, lockOwner, lockWaiters, 
                         enteredCritical, exitedCritical, inCriticalSection, 
                         sharedCounter >>

Scheduler == sched

handle == /\ pc[98] = "handle"
          /\ pendingCommand # NoCmd
          /\ Assert(running = NoTask, 
                    "Failure of assertion at line 218, column 13.")
          /\ IF pendingCommand.cmd = "Spawn"
                THEN /\ taskState' =          [t \in Tasks |->
                                     IF t = pendingCommand.newTask THEN "Ready"
                                     ELSE IF t = pendingCommand.task THEN "Ready"
                                     ELSE taskState[t]]
                     /\ UNCHANGED << joinWaiters, lockOwner, lockWaiters >>
                ELSE /\ IF pendingCommand.cmd = "Join"
                           THEN /\ IF IsDone(pendingCommand.target)
                                      THEN /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                           /\ UNCHANGED joinWaiters
                                      ELSE /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Joining"]
                                           /\ joinWaiters' = [joinWaiters EXCEPT ![pendingCommand.target] = joinWaiters[pendingCommand.target] \union {pendingCommand.task}]
                                /\ UNCHANGED << lockOwner, lockWaiters >>
                           ELSE /\ IF pendingCommand.cmd = "LockAcquire"
                                      THEN /\ IF lockOwner = NoTask
                                                 THEN /\ lockOwner' = pendingCommand.task
                                                      /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                                      /\ UNCHANGED lockWaiters
                                                 ELSE /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "WaitingLock"]
                                                      /\ lockWaiters' = Append(lockWaiters, pendingCommand.task)
                                                      /\ UNCHANGED lockOwner
                                           /\ UNCHANGED joinWaiters
                                      ELSE /\ IF pendingCommand.cmd = "LockRelease"
                                                 THEN /\ Assert(lockOwner = pendingCommand.task, 
                                                                "Failure of assertion at line 254, column 17.")
                                                      /\ IF lockWaiters # <<>>
                                                            THEN /\ LET waiter == Head(lockWaiters) IN
                                                                      /\ lockWaiters' = Tail(lockWaiters)
                                                                      /\ taskState' =          [t \in Tasks |->
                                                                                      IF t = waiter THEN "ReadyResuming"
                                                                                      ELSE IF t = pendingCommand.task THEN "Ready"
                                                                                      ELSE taskState[t]]
                                                                 /\ UNCHANGED lockOwner
                                                            ELSE /\ lockOwner' = NoTask
                                                                 /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                                                 /\ UNCHANGED lockWaiters
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
                                                      /\ UNCHANGED << lockOwner, 
                                                                      lockWaiters >>
          /\ pendingCommand' = NoCmd
          /\ pc' = [pc EXCEPT ![98] = "handle"]
          /\ UNCHANGED << running, enteredCritical, exitedCritical, 
                          inCriticalSection, sharedCounter >>

EventLoopHandler == handle

main_spawn1(self) == /\ pc[self] = "main_spawn1"
                     /\ running = self
                     /\ Assert(pendingCommand = NoCmd, 
                               "Failure of assertion at line 157, column 9 of macro called at line 294, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 158, column 9 of macro called at line 294, column 9.")
                     /\ Assert(taskState[self] = "Running", 
                               "Failure of assertion at line 159, column 9 of macro called at line 294, column 9.")
                     /\ pendingCommand' = [cmd |-> "Spawn", task |-> self, newTask |-> 1]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_spawn2"]
                     /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                     lockWaiters, enteredCritical, 
                                     exitedCritical, inCriticalSection, 
                                     sharedCounter >>

main_spawn2(self) == /\ pc[self] = "main_spawn2"
                     /\ running = self
                     /\ Assert(pendingCommand = NoCmd, 
                               "Failure of assertion at line 157, column 9 of macro called at line 298, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 158, column 9 of macro called at line 298, column 9.")
                     /\ Assert(taskState[self] = "Running", 
                               "Failure of assertion at line 159, column 9 of macro called at line 298, column 9.")
                     /\ pendingCommand' = [cmd |-> "Spawn", task |-> self, newTask |-> 2]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_spawn3"]
                     /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                     lockWaiters, enteredCritical, 
                                     exitedCritical, inCriticalSection, 
                                     sharedCounter >>

main_spawn3(self) == /\ pc[self] = "main_spawn3"
                     /\ running = self
                     /\ Assert(pendingCommand = NoCmd, 
                               "Failure of assertion at line 157, column 9 of macro called at line 302, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 158, column 9 of macro called at line 302, column 9.")
                     /\ Assert(taskState[self] = "Running", 
                               "Failure of assertion at line 159, column 9 of macro called at line 302, column 9.")
                     /\ pendingCommand' = [cmd |-> "Spawn", task |-> self, newTask |-> 3]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_join1"]
                     /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                     lockWaiters, enteredCritical, 
                                     exitedCritical, inCriticalSection, 
                                     sharedCounter >>

main_join1(self) == /\ pc[self] = "main_join1"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 165, column 9 of macro called at line 306, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 166, column 9 of macro called at line 306, column 9.")
                    /\ Assert(taskState[self] = "Running", 
                              "Failure of assertion at line 167, column 9 of macro called at line 306, column 9.")
                    /\ pendingCommand' = [cmd |-> "Join", task |-> self, target |-> 1]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_join2"]
                    /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                    lockWaiters, enteredCritical, 
                                    exitedCritical, inCriticalSection, 
                                    sharedCounter >>

main_join2(self) == /\ pc[self] = "main_join2"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 165, column 9 of macro called at line 310, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 166, column 9 of macro called at line 310, column 9.")
                    /\ Assert(taskState[self] = "Running", 
                              "Failure of assertion at line 167, column 9 of macro called at line 310, column 9.")
                    /\ pendingCommand' = [cmd |-> "Join", task |-> self, target |-> 2]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_join3"]
                    /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                    lockWaiters, enteredCritical, 
                                    exitedCritical, inCriticalSection, 
                                    sharedCounter >>

main_join3(self) == /\ pc[self] = "main_join3"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 165, column 9 of macro called at line 314, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 166, column 9 of macro called at line 314, column 9.")
                    /\ Assert(taskState[self] = "Running", 
                              "Failure of assertion at line 167, column 9 of macro called at line 314, column 9.")
                    /\ pendingCommand' = [cmd |-> "Join", task |-> self, target |-> 3]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_complete"]
                    /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                    lockWaiters, enteredCritical, 
                                    exitedCritical, inCriticalSection, 
                                    sharedCounter >>

main_complete(self) == /\ pc[self] = "main_complete"
                       /\ running = self
                       /\ Assert(pendingCommand = NoCmd, 
                                 "Failure of assertion at line 189, column 9 of macro called at line 318, column 9.")
                       /\ Assert(running = self, 
                                 "Failure of assertion at line 190, column 9 of macro called at line 318, column 9.")
                       /\ Assert(taskState[self] = "Running", 
                                 "Failure of assertion at line 191, column 9 of macro called at line 318, column 9.")
                       /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                       /\ running' = NoTask
                       /\ pc' = [pc EXCEPT ![self] = "Done"]
                       /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                       lockWaiters, enteredCritical, 
                                       exitedCritical, inCriticalSection, 
                                       sharedCounter >>

Main(self) == main_spawn1(self) \/ main_spawn2(self) \/ main_spawn3(self)
                 \/ main_join1(self) \/ main_join2(self)
                 \/ main_join3(self) \/ main_complete(self)

worker_acquire(self) == /\ pc[self] = "worker_acquire"
                        /\ running = self
                        /\ Assert(pendingCommand = NoCmd, 
                                  "Failure of assertion at line 173, column 9 of macro called at line 326, column 9.")
                        /\ Assert(running = self, 
                                  "Failure of assertion at line 174, column 9 of macro called at line 326, column 9.")
                        /\ Assert(taskState[self] = "Running", 
                                  "Failure of assertion at line 175, column 9 of macro called at line 326, column 9.")
                        /\ pendingCommand' = [cmd |-> "LockAcquire", task |-> self]
                        /\ running' = NoTask
                        /\ pc' = [pc EXCEPT ![self] = "worker_critical_enter"]
                        /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                        lockWaiters, enteredCritical, 
                                        exitedCritical, inCriticalSection, 
                                        sharedCounter >>

worker_critical_enter(self) == /\ pc[self] = "worker_critical_enter"
                               /\ running = self
                               /\ enteredCritical' = (enteredCritical \union {self})
                               /\ inCriticalSection' = self
                               /\ pc' = [pc EXCEPT ![self] = "worker_critical_work"]
                               /\ UNCHANGED << running, pendingCommand, 
                                               taskState, joinWaiters, 
                                               lockOwner, lockWaiters, 
                                               exitedCritical, sharedCounter >>

worker_critical_work(self) == /\ pc[self] = "worker_critical_work"
                              /\ running = self
                              /\ sharedCounter' = sharedCounter + 1
                              /\ pc' = [pc EXCEPT ![self] = "worker_critical_exit"]
                              /\ UNCHANGED << running, pendingCommand, 
                                              taskState, joinWaiters, 
                                              lockOwner, lockWaiters, 
                                              enteredCritical, exitedCritical, 
                                              inCriticalSection >>

worker_critical_exit(self) == /\ pc[self] = "worker_critical_exit"
                              /\ running = self
                              /\ exitedCritical' = (exitedCritical \union {self})
                              /\ inCriticalSection' = NoTask
                              /\ pc' = [pc EXCEPT ![self] = "worker_release"]
                              /\ UNCHANGED << running, pendingCommand, 
                                              taskState, joinWaiters, 
                                              lockOwner, lockWaiters, 
                                              enteredCritical, sharedCounter >>

worker_release(self) == /\ pc[self] = "worker_release"
                        /\ running = self
                        /\ Assert(pendingCommand = NoCmd, 
                                  "Failure of assertion at line 181, column 9 of macro called at line 344, column 9.")
                        /\ Assert(running = self, 
                                  "Failure of assertion at line 182, column 9 of macro called at line 344, column 9.")
                        /\ Assert(taskState[self] = "Running", 
                                  "Failure of assertion at line 183, column 9 of macro called at line 344, column 9.")
                        /\ pendingCommand' = [cmd |-> "LockRelease", task |-> self]
                        /\ running' = NoTask
                        /\ pc' = [pc EXCEPT ![self] = "worker_complete"]
                        /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                        lockWaiters, enteredCritical, 
                                        exitedCritical, inCriticalSection, 
                                        sharedCounter >>

worker_complete(self) == /\ pc[self] = "worker_complete"
                         /\ running = self
                         /\ Assert(pendingCommand = NoCmd, 
                                   "Failure of assertion at line 189, column 9 of macro called at line 348, column 9.")
                         /\ Assert(running = self, 
                                   "Failure of assertion at line 190, column 9 of macro called at line 348, column 9.")
                         /\ Assert(taskState[self] = "Running", 
                                   "Failure of assertion at line 191, column 9 of macro called at line 348, column 9.")
                         /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                         /\ running' = NoTask
                         /\ pc' = [pc EXCEPT ![self] = "Done"]
                         /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                         lockWaiters, enteredCritical, 
                                         exitedCritical, inCriticalSection, 
                                         sharedCounter >>

Worker(self) == worker_acquire(self) \/ worker_critical_enter(self)
                   \/ worker_critical_work(self)
                   \/ worker_critical_exit(self) \/ worker_release(self)
                   \/ worker_complete(self)

Next == Scheduler \/ EventLoopHandler
           \/ (\E self \in {0}: Main(self))
           \/ (\E self \in {1, 2, 3}: Worker(self))

Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(Scheduler)
        /\ WF_vars(EventLoopHandler)
        /\ \A self \in {0} : WF_vars(Main(self))
        /\ \A self \in {1, 2, 3} : WF_vars(Worker(self))

\* END TRANSLATION

=============================================================================
