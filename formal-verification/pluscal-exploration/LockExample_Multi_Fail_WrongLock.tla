------------------------ MODULE LockExample_Multi_Fail_WrongLock ------------------------
(*
 * PURPOSE: Formal verification of Flowno's Lock synchronization primitive (Multi-Lock)
 *
 * This spec models multiple lock instances with three concurrent tasks,
 * verifying mutual exclusion and FIFO fairness across different locks.
 *
 * IMPROVEMENTS OVER LockExample:
 * - Supports multiple lock instances (not just one global lock)
 * - Ergonomic macros for common patterns (critical_section, with_lock_do)
 * - Tests both shared locks (contention) and independent locks (parallelism)
 *
 * Python equivalent being modeled:
 *   lock1 = Lock()  # Shared lock
 *   lock2 = Lock()  # Independent lock
 *
 *   async def worker1(id: int):
 *       async with lock1:
 *           # Critical section on lock1
 *           counter1[0] += 1
 *
 *   async def worker2(id: int):
 *       async with lock2:
 *           # Critical section on lock2 (can run parallel with lock1)
 *           counter2[0] += 1
 *
 * VERIFICATION GOALS:
 * - Mutual exclusion per lock (different locks don't interfere)
 * - FIFO ordering per lock
 * - Lock ownership tracking per lock
 * - No deadlocks
 *)
EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS NoTask, NoCmd, Lock1, Lock2

Tasks == {0, 1, 2, 3}  \* 0=Main, 1-2=Workers on Lock1, 3=Worker on Lock2
Locks == {Lock1, Lock2}

(* --algorithm LockExample_Multi {
    variables
        \* === Core event loop state ===
        running = NoTask,
        pendingCommand = NoCmd,
        taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"],
        joinWaiters = [t \in Tasks |-> {}],

        \* === Lock state (per-lock tracking) ===
        lockOwner = [l \in Locks |-> NoTask],
        lockWaiters = [l \in Locks |-> <<>>],

        \* === Application state for verification ===
        enteredCritical = [l \in Locks |-> {}],
        exitedCritical = [l \in Locks |-> {}],
        inCriticalSection = [l \in Locks |-> NoTask],
        sharedCounter = [l \in Locks |-> 0];

    define {
        \* === State predicates ===
        IsNonexistent(t) == taskState[t] = "Nonexistent"
        IsReady(t) == taskState[t] = "Ready"
        IsReadyResuming(t) == taskState[t] = "ReadyResuming"
        IsRunning(t) == taskState[t] = "Running"
        IsWaitingLock(t) == taskState[t] = "WaitingLock"
        IsJoining(t) == taskState[t] = "Joining"
        IsDone(t) == taskState[t] = "Done"

        IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)

        \* === Invariants ===
        AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1

        RunningConsistent ==
            /\ (running # NoTask => IsRunning(running))
            /\ (running = NoTask /\ pendingCommand = NoCmd => ~\E t \in Tasks : IsRunning(t))

        \* MUTUAL EXCLUSION: At most one task in critical section PER LOCK
        MutualExclusionPerLock ==
            \A l \in Locks : Cardinality({t \in Tasks : inCriticalSection[l] = t}) <= 1

        \* Lock ownership is consistent PER LOCK
        LockOwnerConsistent ==
            \A l \in Locks :
                \/ lockOwner[l] = NoTask
                \/ (IsReady(lockOwner[l]) \/ IsRunning(lockOwner[l]) \/ IsReadyResuming(lockOwner[l]))

        \* Lock waiters are consistent PER LOCK
        LockWaitersConsistent ==
            \A l \in Locks : \A i \in 1..Len(lockWaiters[l]) : IsWaitingLock(lockWaiters[l][i])

        \* If lock is unlocked, no waiters
        UnlockedNoWaiters ==
            \A l \in Locks : (lockOwner[l] = NoTask) => (lockWaiters[l] = <<>>)

        \* Only lock owner can be in critical section
        OnlyOwnerInCritical ==
            \A l \in Locks : (inCriticalSection[l] # NoTask) => (inCriticalSection[l] = lockOwner[l])

        JoinWaitersConsistent ==
            \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)

        \* === Liveness properties ===
        \* All workers on Lock1 should complete
        EventuallyLock1WorkersDone == <>(IsDone(1) /\ IsDone(2))

        \* Worker on Lock2 should complete
        EventuallyLock2WorkerDone == <>(IsDone(3))

        \* All tasks complete
        EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2) /\ IsDone(3))

        \* Counters reach expected values
        EventuallyCountersCorrect == <>(sharedCounter[Lock1] = 2 /\ sharedCounter[Lock2] = 1)
    }

    \* === Ergonomic Macros ===

    macro yield_spawn(newTask) {
        assert pendingCommand = NoCmd;
        assert running = self;
        pendingCommand := [cmd |-> "Spawn", task |-> self, newTask |-> newTask];
        running := NoTask;
    }

    macro yield_join(target) {
        assert pendingCommand = NoCmd;
        assert running = self;
        pendingCommand := [cmd |-> "Join", task |-> self, target |-> target];
        running := NoTask;
    }

    macro yield_lock_acquire(lock) {
        assert pendingCommand = NoCmd;
        assert running = self;
        pendingCommand := [cmd |-> "LockAcquire", task |-> self, lock |-> lock];
        running := NoTask;
    }

    macro yield_lock_release(lock) {
        assert pendingCommand = NoCmd;
        assert running = self;
        pendingCommand := [cmd |-> "LockRelease", task |-> self, lock |-> lock];
        running := NoTask;
    }

    macro yield_complete() {
        assert pendingCommand = NoCmd;
        assert running = self;
        pendingCommand := [cmd |-> "Complete", task |-> self];
        running := NoTask;
    }

    \* ERGONOMIC: Critical section wrapper (acquire -> body -> release)
    \* Note: In PlusCal, we can't pass code blocks, so this is conceptual
    \* Users should use the pattern: acquire, critical_work, release

    \* === Background processes ===

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

    fair process (EventLoopHandler = 98)
    {
      handle:
        while (TRUE) {
            await pendingCommand # NoCmd;
            assert running = NoTask;

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
                \* Acquire lock: check if available for THIS lock
                if (lockOwner[pendingCommand.lock] = NoTask) {
                    lockOwner[pendingCommand.lock] := pendingCommand.task;
                    taskState[pendingCommand.task] := "Ready";
                } else {
                    taskState[pendingCommand.task] := "WaitingLock";
                    lockWaiters[pendingCommand.lock] :=
                        Append(lockWaiters[pendingCommand.lock], pendingCommand.task);
                };
            }

            else if (pendingCommand.cmd = "LockRelease") {
                \* Release THIS lock: only owner can release
                assert lockOwner[pendingCommand.lock] = pendingCommand.task;

                if (lockWaiters[pendingCommand.lock] # <<>>) {
                    \* Wake next waiter in FIFO order, transfer ownership
                    with (waiter = Head(lockWaiters[pendingCommand.lock])) {
                        lockWaiters[pendingCommand.lock] := Tail(lockWaiters[pendingCommand.lock]);
                        lockOwner[pendingCommand.lock] := waiter;
                        taskState := [t \in Tasks |->
                            IF t = waiter THEN "ReadyResuming"
                            ELSE IF t = pendingCommand.task THEN "Ready"
                            ELSE taskState[t]];
                    };
                } else {
                    lockOwner[pendingCommand.lock] := NoTask;
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

            pendingCommand := NoCmd;
        }
    }

    \* === Task processes ===

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

    \* Workers 1-2: Compete for Lock1
    fair process (Lock1Worker \in {1, 2})
    {
      w1_acquire:
        await running = self;
        yield_lock_acquire(Lock1);

      w1_critical_enter:
        await running = self;
        enteredCritical[Lock1] := enteredCritical[Lock1] \union {self};
        inCriticalSection[Lock1] := self;

      w1_critical_work:
        await running = self;
        sharedCounter[Lock1] := sharedCounter[Lock1] + 1;

      w1_critical_exit:
        await running = self;
        exitedCritical[Lock1] := exitedCritical[Lock1] \union {self};
        inCriticalSection[Lock1] := NoTask;

      w1_release:
        await running = self;
        yield_lock_release(Lock1);

      w1_complete:
        await running = self;
        yield_complete();
    }

    \* Worker 3: Uses Lock2 (independent, can run parallel)
    fair process (Lock2Worker \in {3})
    {
      w2_acquire:
        await running = self;
        yield_lock_acquire(Lock2);

      w2_critical_enter:
        await running = self;
        enteredCritical[Lock2] := enteredCritical[Lock2] \union {self};
        inCriticalSection[Lock2] := self;

      w2_critical_work:
        await running = self;
        sharedCounter[Lock2] := sharedCounter[Lock2] + 1;

      w2_critical_exit:
        await running = self;
        exitedCritical[Lock2] := exitedCritical[Lock2] \union {self};
        inCriticalSection[Lock2] := NoTask;

      w2_release:
        await running = self;
        yield_lock_release(Lock1);  \* BUG: Should release Lock2, not Lock1

      w2_complete:
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

IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)


AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1

RunningConsistent ==
    /\ (running # NoTask => IsRunning(running))
    /\ (running = NoTask /\ pendingCommand = NoCmd => ~\E t \in Tasks : IsRunning(t))


MutualExclusionPerLock ==
    \A l \in Locks : Cardinality({t \in Tasks : inCriticalSection[l] = t}) <= 1


LockOwnerConsistent ==
    \A l \in Locks :
        \/ lockOwner[l] = NoTask
        \/ (IsReady(lockOwner[l]) \/ IsRunning(lockOwner[l]) \/ IsReadyResuming(lockOwner[l]))


LockWaitersConsistent ==
    \A l \in Locks : \A i \in 1..Len(lockWaiters[l]) : IsWaitingLock(lockWaiters[l][i])


UnlockedNoWaiters ==
    \A l \in Locks : (lockOwner[l] = NoTask) => (lockWaiters[l] = <<>>)


OnlyOwnerInCritical ==
    \A l \in Locks : (inCriticalSection[l] # NoTask) => (inCriticalSection[l] = lockOwner[l])

JoinWaitersConsistent ==
    \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)



EventuallyLock1WorkersDone == <>(IsDone(1) /\ IsDone(2))


EventuallyLock2WorkerDone == <>(IsDone(3))


EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2) /\ IsDone(3))


EventuallyCountersCorrect == <>(sharedCounter[Lock1] = 2 /\ sharedCounter[Lock2] = 1)


vars == << running, pendingCommand, taskState, joinWaiters, lockOwner, 
           lockWaiters, enteredCritical, exitedCritical, inCriticalSection, 
           sharedCounter, pc >>

ProcSet == {99} \cup {98} \cup ({0}) \cup ({1, 2}) \cup ({3})

Init == (* Global variables *)
        /\ running = NoTask
        /\ pendingCommand = NoCmd
        /\ taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"]
        /\ joinWaiters = [t \in Tasks |-> {}]
        /\ lockOwner = [l \in Locks |-> NoTask]
        /\ lockWaiters = [l \in Locks |-> <<>>]
        /\ enteredCritical = [l \in Locks |-> {}]
        /\ exitedCritical = [l \in Locks |-> {}]
        /\ inCriticalSection = [l \in Locks |-> NoTask]
        /\ sharedCounter = [l \in Locks |-> 0]
        /\ pc = [self \in ProcSet |-> CASE self = 99 -> "sched"
                                        [] self = 98 -> "handle"
                                        [] self \in {0} -> "main_spawn1"
                                        [] self \in {1, 2} -> "w1_acquire"
                                        [] self \in {3} -> "w2_acquire"]

sched == /\ pc[99] = "sched"
         /\ pendingCommand = NoCmd /\ running = NoTask /\ \E t \in Tasks : IsSchedulable(t)
         /\ \E t \in {t \in Tasks : IsSchedulable(t)}:
              /\ Assert(~\E t2 \in Tasks : taskState[t2] = "Running", 
                        "Failure of assertion at line 165, column 17.")
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
                    "Failure of assertion at line 177, column 13.")
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
                                      THEN /\ IF lockOwner[pendingCommand.lock] = NoTask
                                                 THEN /\ lockOwner' = [lockOwner EXCEPT ![pendingCommand.lock] = pendingCommand.task]
                                                      /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                                      /\ UNCHANGED lockWaiters
                                                 ELSE /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "WaitingLock"]
                                                      /\ lockWaiters' = [lockWaiters EXCEPT ![pendingCommand.lock] = Append(lockWaiters[pendingCommand.lock], pendingCommand.task)]
                                                      /\ UNCHANGED lockOwner
                                           /\ UNCHANGED joinWaiters
                                      ELSE /\ IF pendingCommand.cmd = "LockRelease"
                                                 THEN /\ Assert(lockOwner[pendingCommand.lock] = pendingCommand.task, 
                                                                "Failure of assertion at line 210, column 17.")
                                                      /\ IF lockWaiters[pendingCommand.lock] # <<>>
                                                            THEN /\ LET waiter == Head(lockWaiters[pendingCommand.lock]) IN
                                                                      /\ lockWaiters' = [lockWaiters EXCEPT ![pendingCommand.lock] = Tail(lockWaiters[pendingCommand.lock])]
                                                                      /\ lockOwner' = [lockOwner EXCEPT ![pendingCommand.lock] = waiter]
                                                                      /\ taskState' =          [t \in Tasks |->
                                                                                      IF t = waiter THEN "ReadyResuming"
                                                                                      ELSE IF t = pendingCommand.task THEN "Ready"
                                                                                      ELSE taskState[t]]
                                                            ELSE /\ lockOwner' = [lockOwner EXCEPT ![pendingCommand.lock] = NoTask]
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
                               "Failure of assertion at line 119, column 9 of macro called at line 246, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 120, column 9 of macro called at line 246, column 9.")
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
                               "Failure of assertion at line 119, column 9 of macro called at line 250, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 120, column 9 of macro called at line 250, column 9.")
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
                               "Failure of assertion at line 119, column 9 of macro called at line 254, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 120, column 9 of macro called at line 254, column 9.")
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
                              "Failure of assertion at line 126, column 9 of macro called at line 258, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 127, column 9 of macro called at line 258, column 9.")
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
                              "Failure of assertion at line 126, column 9 of macro called at line 262, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 127, column 9 of macro called at line 262, column 9.")
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
                              "Failure of assertion at line 126, column 9 of macro called at line 266, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 127, column 9 of macro called at line 266, column 9.")
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
                                 "Failure of assertion at line 147, column 9 of macro called at line 270, column 9.")
                       /\ Assert(running = self, 
                                 "Failure of assertion at line 148, column 9 of macro called at line 270, column 9.")
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

w1_acquire(self) == /\ pc[self] = "w1_acquire"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 133, column 9 of macro called at line 278, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 134, column 9 of macro called at line 278, column 9.")
                    /\ pendingCommand' = [cmd |-> "LockAcquire", task |-> self, lock |-> Lock1]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "w1_critical_enter"]
                    /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                    lockWaiters, enteredCritical, 
                                    exitedCritical, inCriticalSection, 
                                    sharedCounter >>

w1_critical_enter(self) == /\ pc[self] = "w1_critical_enter"
                           /\ running = self
                           /\ enteredCritical' = [enteredCritical EXCEPT ![Lock1] = enteredCritical[Lock1] \union {self}]
                           /\ inCriticalSection' = [inCriticalSection EXCEPT ![Lock1] = self]
                           /\ pc' = [pc EXCEPT ![self] = "w1_critical_work"]
                           /\ UNCHANGED << running, pendingCommand, taskState, 
                                           joinWaiters, lockOwner, lockWaiters, 
                                           exitedCritical, sharedCounter >>

w1_critical_work(self) == /\ pc[self] = "w1_critical_work"
                          /\ running = self
                          /\ sharedCounter' = [sharedCounter EXCEPT ![Lock1] = sharedCounter[Lock1] + 1]
                          /\ pc' = [pc EXCEPT ![self] = "w1_critical_exit"]
                          /\ UNCHANGED << running, pendingCommand, taskState, 
                                          joinWaiters, lockOwner, lockWaiters, 
                                          enteredCritical, exitedCritical, 
                                          inCriticalSection >>

w1_critical_exit(self) == /\ pc[self] = "w1_critical_exit"
                          /\ running = self
                          /\ exitedCritical' = [exitedCritical EXCEPT ![Lock1] = exitedCritical[Lock1] \union {self}]
                          /\ inCriticalSection' = [inCriticalSection EXCEPT ![Lock1] = NoTask]
                          /\ pc' = [pc EXCEPT ![self] = "w1_release"]
                          /\ UNCHANGED << running, pendingCommand, taskState, 
                                          joinWaiters, lockOwner, lockWaiters, 
                                          enteredCritical, sharedCounter >>

w1_release(self) == /\ pc[self] = "w1_release"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 140, column 9 of macro called at line 296, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 141, column 9 of macro called at line 296, column 9.")
                    /\ pendingCommand' = [cmd |-> "LockRelease", task |-> self, lock |-> Lock1]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "w1_complete"]
                    /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                    lockWaiters, enteredCritical, 
                                    exitedCritical, inCriticalSection, 
                                    sharedCounter >>

w1_complete(self) == /\ pc[self] = "w1_complete"
                     /\ running = self
                     /\ Assert(pendingCommand = NoCmd, 
                               "Failure of assertion at line 147, column 9 of macro called at line 300, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 148, column 9 of macro called at line 300, column 9.")
                     /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "Done"]
                     /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                     lockWaiters, enteredCritical, 
                                     exitedCritical, inCriticalSection, 
                                     sharedCounter >>

Lock1Worker(self) == w1_acquire(self) \/ w1_critical_enter(self)
                        \/ w1_critical_work(self) \/ w1_critical_exit(self)
                        \/ w1_release(self) \/ w1_complete(self)

w2_acquire(self) == /\ pc[self] = "w2_acquire"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 133, column 9 of macro called at line 308, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 134, column 9 of macro called at line 308, column 9.")
                    /\ pendingCommand' = [cmd |-> "LockAcquire", task |-> self, lock |-> Lock2]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "w2_critical_enter"]
                    /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                    lockWaiters, enteredCritical, 
                                    exitedCritical, inCriticalSection, 
                                    sharedCounter >>

w2_critical_enter(self) == /\ pc[self] = "w2_critical_enter"
                           /\ running = self
                           /\ enteredCritical' = [enteredCritical EXCEPT ![Lock2] = enteredCritical[Lock2] \union {self}]
                           /\ inCriticalSection' = [inCriticalSection EXCEPT ![Lock2] = self]
                           /\ pc' = [pc EXCEPT ![self] = "w2_critical_work"]
                           /\ UNCHANGED << running, pendingCommand, taskState, 
                                           joinWaiters, lockOwner, lockWaiters, 
                                           exitedCritical, sharedCounter >>

w2_critical_work(self) == /\ pc[self] = "w2_critical_work"
                          /\ running = self
                          /\ sharedCounter' = [sharedCounter EXCEPT ![Lock2] = sharedCounter[Lock2] + 1]
                          /\ pc' = [pc EXCEPT ![self] = "w2_critical_exit"]
                          /\ UNCHANGED << running, pendingCommand, taskState, 
                                          joinWaiters, lockOwner, lockWaiters, 
                                          enteredCritical, exitedCritical, 
                                          inCriticalSection >>

w2_critical_exit(self) == /\ pc[self] = "w2_critical_exit"
                          /\ running = self
                          /\ exitedCritical' = [exitedCritical EXCEPT ![Lock2] = exitedCritical[Lock2] \union {self}]
                          /\ inCriticalSection' = [inCriticalSection EXCEPT ![Lock2] = NoTask]
                          /\ pc' = [pc EXCEPT ![self] = "w2_release"]
                          /\ UNCHANGED << running, pendingCommand, taskState, 
                                          joinWaiters, lockOwner, lockWaiters, 
                                          enteredCritical, sharedCounter >>

w2_release(self) == /\ pc[self] = "w2_release"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 140, column 9 of macro called at line 326, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 141, column 9 of macro called at line 326, column 9.")
                    /\ pendingCommand' = [cmd |-> "LockRelease", task |-> self, lock |-> Lock1]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "w2_complete"]
                    /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                    lockWaiters, enteredCritical, 
                                    exitedCritical, inCriticalSection, 
                                    sharedCounter >>

w2_complete(self) == /\ pc[self] = "w2_complete"
                     /\ running = self
                     /\ Assert(pendingCommand = NoCmd, 
                               "Failure of assertion at line 147, column 9 of macro called at line 330, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 148, column 9 of macro called at line 330, column 9.")
                     /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "Done"]
                     /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                     lockWaiters, enteredCritical, 
                                     exitedCritical, inCriticalSection, 
                                     sharedCounter >>

Lock2Worker(self) == w2_acquire(self) \/ w2_critical_enter(self)
                        \/ w2_critical_work(self) \/ w2_critical_exit(self)
                        \/ w2_release(self) \/ w2_complete(self)

Next == Scheduler \/ EventLoopHandler
           \/ (\E self \in {0}: Main(self))
           \/ (\E self \in {1, 2}: Lock1Worker(self))
           \/ (\E self \in {3}: Lock2Worker(self))

Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(Scheduler)
        /\ WF_vars(EventLoopHandler)
        /\ \A self \in {0} : WF_vars(Main(self))
        /\ \A self \in {1, 2} : WF_vars(Lock1Worker(self))
        /\ \A self \in {3} : WF_vars(Lock2Worker(self))

\* END TRANSLATION

=============================================================================
