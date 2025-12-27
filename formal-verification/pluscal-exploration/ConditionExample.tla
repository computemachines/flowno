------------------------ MODULE ConditionExample ------------------------
(*
 * PURPOSE: Formal verification of Flowno's Condition synchronization primitive
 *
 * This spec models a producer-consumer pattern using Condition variables,
 * verifying correct wait/notify semantics and lock coordination.
 *
 * Python equivalent being modeled:
 *   lock = Lock()
 *   condition = Condition(lock)
 *   buffer = []
 *
 *   async def consumer(id: int):
 *       async with lock:
 *           while len(buffer) == 0:
 *               await condition.wait()  # Atomically releases lock
 *           item = buffer.pop()
 *       # Process item
 *
 *   async def producer():
 *       async with lock:
 *           buffer.append(item)
 *           await condition.notify()  # Wake one consumer
 *
 * VERIFICATION GOALS:
 * - Condition wait atomically releases lock
 * - Only lock owner can wait/notify
 * - Notified tasks must reacquire lock
 * - Mutual exclusion maintained
 * - No deadlocks
 * - All tasks eventually complete
 *)
EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS NoTask, NoCmd, SharedLock, SharedCondition

Tasks == {0, 1, 2}  \* 0=Main, 1=Producer, 2=Consumer

(* --algorithm ConditionExample {
    variables
        \* === Core event loop state ===
        running = NoTask,
        pendingCommand = NoCmd,
        taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"],
        joinWaiters = [t \in Tasks |-> {}],

        \* === Lock state ===
        lockOwner = NoTask,
        lockWaiters = <<>>,

        \* === Condition state ===
        conditionWaiters = {},

        \* === Application state (shared buffer) ===
        buffer = 0,  \* Simple counter: 0 = empty, >0 = has items
        producerDone = FALSE,
        consumerDone = FALSE;

    define {
        \* === State predicates ===
        IsNonexistent(t) == taskState[t] = "Nonexistent"
        IsReady(t) == taskState[t] = "Ready"
        IsReadyResuming(t) == taskState[t] = "ReadyResuming"
        IsRunning(t) == taskState[t] = "Running"
        IsWaitingLock(t) == taskState[t] = "WaitingLock"
        IsWaitingCondition(t) == taskState[t] = "WaitingCondition"
        IsJoining(t) == taskState[t] = "Joining"
        IsDone(t) == taskState[t] = "Done"

        IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)

        \* === Invariants ===
        AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1

        RunningConsistent ==
            /\ (running # NoTask => IsRunning(running))
            /\ (running = NoTask /\ pendingCommand = NoCmd => ~\E t \in Tasks : IsRunning(t))

        \* Lock invariants
        LockOwnerConsistent ==
            \/ lockOwner = NoTask
            \/ (IsReady(lockOwner) \/ IsRunning(lockOwner) \/ IsReadyResuming(lockOwner) \/ IsWaitingCondition(lockOwner))

        LockWaitersConsistent ==
            \A i \in 1..Len(lockWaiters) : IsWaitingLock(lockWaiters[i])

        UnlockedNoWaiters ==
            (lockOwner = NoTask) => (lockWaiters = <<>>)

        \* Condition invariants
        ConditionWaitersConsistent ==
            \A w \in conditionWaiters : IsWaitingCondition(w)

        \* Condition waiters don't hold lock (released atomically)
        ConditionWaitersNoLock ==
            \A w \in conditionWaiters : lockOwner # w

        JoinWaitersConsistent ==
            \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)

        \* === Liveness properties ===
        EventuallyProducerDone == <>(producerDone)
        EventuallyConsumerDone == <>(consumerDone)
        EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2))
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

    macro yield_lock_acquire() {
        assert pendingCommand = NoCmd;
        assert running = self;
        pendingCommand := [cmd |-> "LockAcquire", task |-> self];
        running := NoTask;
    }

    macro yield_lock_release() {
        assert pendingCommand = NoCmd;
        assert running = self;
        pendingCommand := [cmd |-> "LockRelease", task |-> self];
        running := NoTask;
    }

    macro yield_condition_wait() {
        assert pendingCommand = NoCmd;
        assert running = self;
        pendingCommand := [cmd |-> "ConditionWait", task |-> self];
        running := NoTask;
    }

    macro yield_condition_notify() {
        assert pendingCommand = NoCmd;
        assert running = self;
        pendingCommand := [cmd |-> "ConditionNotify", task |-> self];
        running := NoTask;
    }

    macro yield_complete() {
        assert pendingCommand = NoCmd;
        assert running = self;
        pendingCommand := [cmd |-> "Complete", task |-> self];
        running := NoTask;
    }

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
                if (lockOwner = NoTask) {
                    lockOwner := pendingCommand.task;
                    taskState[pendingCommand.task] := "Ready";
                } else {
                    taskState[pendingCommand.task] := "WaitingLock";
                    lockWaiters := Append(lockWaiters, pendingCommand.task);
                };
            }

            else if (pendingCommand.cmd = "LockRelease") {
                assert lockOwner = pendingCommand.task;

                if (lockWaiters # <<>>) {
                    with (waiter = Head(lockWaiters)) {
                        lockWaiters := Tail(lockWaiters);
                        lockOwner := waiter;
                        taskState := [t \in Tasks |->
                            IF t = waiter THEN "ReadyResuming"
                            ELSE IF t = pendingCommand.task THEN "Ready"
                            ELSE taskState[t]];
                    };
                } else {
                    lockOwner := NoTask;
                    taskState[pendingCommand.task] := "Ready";
                };
            }

            else if (pendingCommand.cmd = "ConditionWait") {
                \* Must hold lock to call wait
                assert lockOwner = pendingCommand.task;

                \* Atomically: add to condition waiters, release lock
                conditionWaiters := conditionWaiters \union {pendingCommand.task};

                \* Release lock and wake next lock waiter if any
                if (lockWaiters # <<>>) {
                    with (waiter = Head(lockWaiters)) {
                        lockWaiters := Tail(lockWaiters);
                        lockOwner := waiter;
                        taskState := [t \in Tasks |->
                            IF t = waiter THEN "ReadyResuming"
                            ELSE IF t = pendingCommand.task THEN "WaitingCondition"
                            ELSE taskState[t]];
                    };
                } else {
                    lockOwner := NoTask;
                    taskState[pendingCommand.task] := "WaitingCondition";
                };
            }

            else if (pendingCommand.cmd = "ConditionNotify") {
                \* Must hold lock to call notify
                assert lockOwner = pendingCommand.task;

                \* Move one condition waiter to lock waiters
                if (conditionWaiters # {}) {
                    with (waiter \in conditionWaiters) {
                        conditionWaiters := conditionWaiters \ {waiter};
                        lockWaiters := Append(lockWaiters, waiter);
                        taskState := [t \in Tasks |->
                            IF t = waiter THEN "WaitingLock"
                            ELSE IF t = pendingCommand.task THEN "Ready"
                            ELSE taskState[t]];
                    };
                } else {
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
      main_spawn_producer:
        await running = self;
        yield_spawn(1);

      main_spawn_consumer:
        await running = self;
        yield_spawn(2);

      main_join_producer:
        await running = self;
        yield_join(1);

      main_join_consumer:
        await running = self;
        yield_join(2);

      main_complete:
        await running = self;
        yield_complete();
    }

    \* Producer: Acquire lock, produce item, notify, release
    fair process (Producer \in {1})
    {
      p_acquire:
        await running = self;
        yield_lock_acquire();

      p_produce:
        await running = self;
        buffer := buffer + 1;

      p_mark_done:
        await running = self;
        producerDone := TRUE;

      p_notify:
        await running = self;
        yield_condition_notify();

      p_release:
        await running = self;
        yield_lock_release();

      p_complete:
        await running = self;
        yield_complete();
    }

    \* Consumer: Acquire lock, wait if empty, consume, release
    fair process (Consumer \in {2})
    {
      c_acquire:
        await running = self;
        yield_lock_acquire();

      c_wait_while_empty:
        await running = self;
        \* Wait while buffer is empty
        if (buffer = 0) {
            yield_condition_wait();
        };

      c_consume:
        await running = self;
        \* After wait(), lock is reacquired
        assert buffer > 0;
        buffer := buffer - 1;

      c_mark_done:
        await running = self;
        consumerDone := TRUE;

      c_release:
        await running = self;
        yield_lock_release();

      c_complete:
        await running = self;
        yield_complete();
    }
} *)

\* BEGIN TRANSLATION - This will be generated by pcal.trans
VARIABLES running, pendingCommand, taskState, joinWaiters, lockOwner, 
          lockWaiters, conditionWaiters, buffer, producerDone, consumerDone, 
          pc

(* define statement *)
IsNonexistent(t) == taskState[t] = "Nonexistent"
IsReady(t) == taskState[t] = "Ready"
IsReadyResuming(t) == taskState[t] = "ReadyResuming"
IsRunning(t) == taskState[t] = "Running"
IsWaitingLock(t) == taskState[t] = "WaitingLock"
IsWaitingCondition(t) == taskState[t] = "WaitingCondition"
IsJoining(t) == taskState[t] = "Joining"
IsDone(t) == taskState[t] = "Done"

IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)


AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1

RunningConsistent ==
    /\ (running # NoTask => IsRunning(running))
    /\ (running = NoTask /\ pendingCommand = NoCmd => ~\E t \in Tasks : IsRunning(t))


LockOwnerConsistent ==
    \/ lockOwner = NoTask
    \/ (IsReady(lockOwner) \/ IsRunning(lockOwner) \/ IsReadyResuming(lockOwner) \/ IsWaitingCondition(lockOwner))

LockWaitersConsistent ==
    \A i \in 1..Len(lockWaiters) : IsWaitingLock(lockWaiters[i])

UnlockedNoWaiters ==
    (lockOwner = NoTask) => (lockWaiters = <<>>)


ConditionWaitersConsistent ==
    \A w \in conditionWaiters : IsWaitingCondition(w)


ConditionWaitersNoLock ==
    \A w \in conditionWaiters : lockOwner # w

JoinWaitersConsistent ==
    \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)


EventuallyProducerDone == <>(producerDone)
EventuallyConsumerDone == <>(consumerDone)
EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2))


vars == << running, pendingCommand, taskState, joinWaiters, lockOwner, 
           lockWaiters, conditionWaiters, buffer, producerDone, consumerDone, 
           pc >>

ProcSet == {99} \cup {98} \cup ({0}) \cup ({1}) \cup ({2})

Init == (* Global variables *)
        /\ running = NoTask
        /\ pendingCommand = NoCmd
        /\ taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"]
        /\ joinWaiters = [t \in Tasks |-> {}]
        /\ lockOwner = NoTask
        /\ lockWaiters = <<>>
        /\ conditionWaiters = {}
        /\ buffer = 0
        /\ producerDone = FALSE
        /\ consumerDone = FALSE
        /\ pc = [self \in ProcSet |-> CASE self = 99 -> "sched"
                                        [] self = 98 -> "handle"
                                        [] self \in {0} -> "main_spawn_producer"
                                        [] self \in {1} -> "p_acquire"
                                        [] self \in {2} -> "c_acquire"]

sched == /\ pc[99] = "sched"
         /\ pendingCommand = NoCmd /\ running = NoTask /\ \E t \in Tasks : IsSchedulable(t)
         /\ \E t \in {t \in Tasks : IsSchedulable(t)}:
              /\ Assert(~\E t2 \in Tasks : taskState[t2] = "Running", 
                        "Failure of assertion at line 166, column 17.")
              /\ running' = t
              /\ taskState' = [taskState EXCEPT ![t] = "Running"]
         /\ pc' = [pc EXCEPT ![99] = "sched"]
         /\ UNCHANGED << pendingCommand, joinWaiters, lockOwner, lockWaiters, 
                         conditionWaiters, buffer, producerDone, consumerDone >>

Scheduler == sched

handle == /\ pc[98] = "handle"
          /\ pendingCommand # NoCmd
          /\ Assert(running = NoTask, 
                    "Failure of assertion at line 178, column 13.")
          /\ IF pendingCommand.cmd = "Spawn"
                THEN /\ taskState' =          [t \in Tasks |->
                                     IF t = pendingCommand.newTask THEN "Ready"
                                     ELSE IF t = pendingCommand.task THEN "Ready"
                                     ELSE taskState[t]]
                     /\ UNCHANGED << joinWaiters, lockOwner, lockWaiters, 
                                     conditionWaiters >>
                ELSE /\ IF pendingCommand.cmd = "Join"
                           THEN /\ IF IsDone(pendingCommand.target)
                                      THEN /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                           /\ UNCHANGED joinWaiters
                                      ELSE /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Joining"]
                                           /\ joinWaiters' = [joinWaiters EXCEPT ![pendingCommand.target] = joinWaiters[pendingCommand.target] \union {pendingCommand.task}]
                                /\ UNCHANGED << lockOwner, lockWaiters, 
                                                conditionWaiters >>
                           ELSE /\ IF pendingCommand.cmd = "LockAcquire"
                                      THEN /\ IF lockOwner = NoTask
                                                 THEN /\ lockOwner' = pendingCommand.task
                                                      /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                                      /\ UNCHANGED lockWaiters
                                                 ELSE /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "WaitingLock"]
                                                      /\ lockWaiters' = Append(lockWaiters, pendingCommand.task)
                                                      /\ UNCHANGED lockOwner
                                           /\ UNCHANGED << joinWaiters, 
                                                           conditionWaiters >>
                                      ELSE /\ IF pendingCommand.cmd = "LockRelease"
                                                 THEN /\ Assert(lockOwner = pendingCommand.task, 
                                                                "Failure of assertion at line 208, column 17.")
                                                      /\ IF lockWaiters # <<>>
                                                            THEN /\ LET waiter == Head(lockWaiters) IN
                                                                      /\ lockWaiters' = Tail(lockWaiters)
                                                                      /\ lockOwner' = waiter
                                                                      /\ taskState' =          [t \in Tasks |->
                                                                                      IF t = waiter THEN "ReadyResuming"
                                                                                      ELSE IF t = pendingCommand.task THEN "Ready"
                                                                                      ELSE taskState[t]]
                                                            ELSE /\ lockOwner' = NoTask
                                                                 /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                                                 /\ UNCHANGED lockWaiters
                                                      /\ UNCHANGED << joinWaiters, 
                                                                      conditionWaiters >>
                                                 ELSE /\ IF pendingCommand.cmd = "ConditionWait"
                                                            THEN /\ Assert(lockOwner = pendingCommand.task, 
                                                                           "Failure of assertion at line 227, column 17.")
                                                                 /\ conditionWaiters' = (conditionWaiters \union {pendingCommand.task})
                                                                 /\ IF lockWaiters # <<>>
                                                                       THEN /\ LET waiter == Head(lockWaiters) IN
                                                                                 /\ lockWaiters' = Tail(lockWaiters)
                                                                                 /\ lockOwner' = waiter
                                                                                 /\ taskState' =          [t \in Tasks |->
                                                                                                 IF t = waiter THEN "ReadyResuming"
                                                                                                 ELSE IF t = pendingCommand.task THEN "WaitingCondition"
                                                                                                 ELSE taskState[t]]
                                                                       ELSE /\ lockOwner' = NoTask
                                                                            /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "WaitingCondition"]
                                                                            /\ UNCHANGED lockWaiters
                                                                 /\ UNCHANGED joinWaiters
                                                            ELSE /\ IF pendingCommand.cmd = "ConditionNotify"
                                                                       THEN /\ Assert(lockOwner = pendingCommand.task, 
                                                                                      "Failure of assertion at line 250, column 17.")
                                                                            /\ IF conditionWaiters # {}
                                                                                  THEN /\ \E waiter \in conditionWaiters:
                                                                                            /\ conditionWaiters' = conditionWaiters \ {waiter}
                                                                                            /\ lockWaiters' = Append(lockWaiters, waiter)
                                                                                            /\ taskState' =          [t \in Tasks |->
                                                                                                            IF t = waiter THEN "WaitingLock"
                                                                                                            ELSE IF t = pendingCommand.task THEN "Ready"
                                                                                                            ELSE taskState[t]]
                                                                                  ELSE /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                                                                       /\ UNCHANGED << lockWaiters, 
                                                                                                       conditionWaiters >>
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
                                                                            /\ UNCHANGED << lockWaiters, 
                                                                                            conditionWaiters >>
                                                                 /\ UNCHANGED lockOwner
          /\ pendingCommand' = NoCmd
          /\ pc' = [pc EXCEPT ![98] = "handle"]
          /\ UNCHANGED << running, buffer, producerDone, consumerDone >>

EventLoopHandler == handle

main_spawn_producer(self) == /\ pc[self] = "main_spawn_producer"
                             /\ running = self
                             /\ Assert(pendingCommand = NoCmd, 
                                       "Failure of assertion at line 110, column 9 of macro called at line 285, column 9.")
                             /\ Assert(running = self, 
                                       "Failure of assertion at line 111, column 9 of macro called at line 285, column 9.")
                             /\ pendingCommand' = [cmd |-> "Spawn", task |-> self, newTask |-> 1]
                             /\ running' = NoTask
                             /\ pc' = [pc EXCEPT ![self] = "main_spawn_consumer"]
                             /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                             lockWaiters, conditionWaiters, 
                                             buffer, producerDone, 
                                             consumerDone >>

main_spawn_consumer(self) == /\ pc[self] = "main_spawn_consumer"
                             /\ running = self
                             /\ Assert(pendingCommand = NoCmd, 
                                       "Failure of assertion at line 110, column 9 of macro called at line 289, column 9.")
                             /\ Assert(running = self, 
                                       "Failure of assertion at line 111, column 9 of macro called at line 289, column 9.")
                             /\ pendingCommand' = [cmd |-> "Spawn", task |-> self, newTask |-> 2]
                             /\ running' = NoTask
                             /\ pc' = [pc EXCEPT ![self] = "main_join_producer"]
                             /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                             lockWaiters, conditionWaiters, 
                                             buffer, producerDone, 
                                             consumerDone >>

main_join_producer(self) == /\ pc[self] = "main_join_producer"
                            /\ running = self
                            /\ Assert(pendingCommand = NoCmd, 
                                      "Failure of assertion at line 117, column 9 of macro called at line 293, column 9.")
                            /\ Assert(running = self, 
                                      "Failure of assertion at line 118, column 9 of macro called at line 293, column 9.")
                            /\ pendingCommand' = [cmd |-> "Join", task |-> self, target |-> 1]
                            /\ running' = NoTask
                            /\ pc' = [pc EXCEPT ![self] = "main_join_consumer"]
                            /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                            lockWaiters, conditionWaiters, 
                                            buffer, producerDone, consumerDone >>

main_join_consumer(self) == /\ pc[self] = "main_join_consumer"
                            /\ running = self
                            /\ Assert(pendingCommand = NoCmd, 
                                      "Failure of assertion at line 117, column 9 of macro called at line 297, column 9.")
                            /\ Assert(running = self, 
                                      "Failure of assertion at line 118, column 9 of macro called at line 297, column 9.")
                            /\ pendingCommand' = [cmd |-> "Join", task |-> self, target |-> 2]
                            /\ running' = NoTask
                            /\ pc' = [pc EXCEPT ![self] = "main_complete"]
                            /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                            lockWaiters, conditionWaiters, 
                                            buffer, producerDone, consumerDone >>

main_complete(self) == /\ pc[self] = "main_complete"
                       /\ running = self
                       /\ Assert(pendingCommand = NoCmd, 
                                 "Failure of assertion at line 152, column 9 of macro called at line 301, column 9.")
                       /\ Assert(running = self, 
                                 "Failure of assertion at line 153, column 9 of macro called at line 301, column 9.")
                       /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                       /\ running' = NoTask
                       /\ pc' = [pc EXCEPT ![self] = "Done"]
                       /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                       lockWaiters, conditionWaiters, buffer, 
                                       producerDone, consumerDone >>

Main(self) == main_spawn_producer(self) \/ main_spawn_consumer(self)
                 \/ main_join_producer(self) \/ main_join_consumer(self)
                 \/ main_complete(self)

p_acquire(self) == /\ pc[self] = "p_acquire"
                   /\ running = self
                   /\ Assert(pendingCommand = NoCmd, 
                             "Failure of assertion at line 124, column 9 of macro called at line 309, column 9.")
                   /\ Assert(running = self, 
                             "Failure of assertion at line 125, column 9 of macro called at line 309, column 9.")
                   /\ pendingCommand' = [cmd |-> "LockAcquire", task |-> self]
                   /\ running' = NoTask
                   /\ pc' = [pc EXCEPT ![self] = "p_produce"]
                   /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                   lockWaiters, conditionWaiters, buffer, 
                                   producerDone, consumerDone >>

p_produce(self) == /\ pc[self] = "p_produce"
                   /\ running = self
                   /\ buffer' = buffer + 1
                   /\ pc' = [pc EXCEPT ![self] = "p_mark_done"]
                   /\ UNCHANGED << running, pendingCommand, taskState, 
                                   joinWaiters, lockOwner, lockWaiters, 
                                   conditionWaiters, producerDone, 
                                   consumerDone >>

p_mark_done(self) == /\ pc[self] = "p_mark_done"
                     /\ running = self
                     /\ producerDone' = TRUE
                     /\ pc' = [pc EXCEPT ![self] = "p_notify"]
                     /\ UNCHANGED << running, pendingCommand, taskState, 
                                     joinWaiters, lockOwner, lockWaiters, 
                                     conditionWaiters, buffer, consumerDone >>

p_notify(self) == /\ pc[self] = "p_notify"
                  /\ running = self
                  /\ Assert(pendingCommand = NoCmd, 
                            "Failure of assertion at line 145, column 9 of macro called at line 321, column 9.")
                  /\ Assert(running = self, 
                            "Failure of assertion at line 146, column 9 of macro called at line 321, column 9.")
                  /\ pendingCommand' = [cmd |-> "ConditionNotify", task |-> self]
                  /\ running' = NoTask
                  /\ pc' = [pc EXCEPT ![self] = "p_release"]
                  /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                  lockWaiters, conditionWaiters, buffer, 
                                  producerDone, consumerDone >>

p_release(self) == /\ pc[self] = "p_release"
                   /\ running = self
                   /\ Assert(pendingCommand = NoCmd, 
                             "Failure of assertion at line 131, column 9 of macro called at line 325, column 9.")
                   /\ Assert(running = self, 
                             "Failure of assertion at line 132, column 9 of macro called at line 325, column 9.")
                   /\ pendingCommand' = [cmd |-> "LockRelease", task |-> self]
                   /\ running' = NoTask
                   /\ pc' = [pc EXCEPT ![self] = "p_complete"]
                   /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                   lockWaiters, conditionWaiters, buffer, 
                                   producerDone, consumerDone >>

p_complete(self) == /\ pc[self] = "p_complete"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 152, column 9 of macro called at line 329, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 153, column 9 of macro called at line 329, column 9.")
                    /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "Done"]
                    /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                    lockWaiters, conditionWaiters, buffer, 
                                    producerDone, consumerDone >>

Producer(self) == p_acquire(self) \/ p_produce(self) \/ p_mark_done(self)
                     \/ p_notify(self) \/ p_release(self)
                     \/ p_complete(self)

c_acquire(self) == /\ pc[self] = "c_acquire"
                   /\ running = self
                   /\ Assert(pendingCommand = NoCmd, 
                             "Failure of assertion at line 124, column 9 of macro called at line 337, column 9.")
                   /\ Assert(running = self, 
                             "Failure of assertion at line 125, column 9 of macro called at line 337, column 9.")
                   /\ pendingCommand' = [cmd |-> "LockAcquire", task |-> self]
                   /\ running' = NoTask
                   /\ pc' = [pc EXCEPT ![self] = "c_wait_while_empty"]
                   /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                   lockWaiters, conditionWaiters, buffer, 
                                   producerDone, consumerDone >>

c_wait_while_empty(self) == /\ pc[self] = "c_wait_while_empty"
                            /\ running = self
                            /\ IF buffer = 0
                                  THEN /\ Assert(pendingCommand = NoCmd, 
                                                 "Failure of assertion at line 138, column 9 of macro called at line 343, column 13.")
                                       /\ Assert(running = self, 
                                                 "Failure of assertion at line 139, column 9 of macro called at line 343, column 13.")
                                       /\ pendingCommand' = [cmd |-> "ConditionWait", task |-> self]
                                       /\ running' = NoTask
                                  ELSE /\ TRUE
                                       /\ UNCHANGED << running, pendingCommand >>
                            /\ pc' = [pc EXCEPT ![self] = "c_consume"]
                            /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                            lockWaiters, conditionWaiters, 
                                            buffer, producerDone, consumerDone >>

c_consume(self) == /\ pc[self] = "c_consume"
                   /\ running = self
                   /\ Assert(buffer > 0, 
                             "Failure of assertion at line 349, column 9.")
                   /\ buffer' = buffer - 1
                   /\ pc' = [pc EXCEPT ![self] = "c_mark_done"]
                   /\ UNCHANGED << running, pendingCommand, taskState, 
                                   joinWaiters, lockOwner, lockWaiters, 
                                   conditionWaiters, producerDone, 
                                   consumerDone >>

c_mark_done(self) == /\ pc[self] = "c_mark_done"
                     /\ running = self
                     /\ consumerDone' = TRUE
                     /\ pc' = [pc EXCEPT ![self] = "c_release"]
                     /\ UNCHANGED << running, pendingCommand, taskState, 
                                     joinWaiters, lockOwner, lockWaiters, 
                                     conditionWaiters, buffer, producerDone >>

c_release(self) == /\ pc[self] = "c_release"
                   /\ running = self
                   /\ Assert(pendingCommand = NoCmd, 
                             "Failure of assertion at line 131, column 9 of macro called at line 358, column 9.")
                   /\ Assert(running = self, 
                             "Failure of assertion at line 132, column 9 of macro called at line 358, column 9.")
                   /\ pendingCommand' = [cmd |-> "LockRelease", task |-> self]
                   /\ running' = NoTask
                   /\ pc' = [pc EXCEPT ![self] = "c_complete"]
                   /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                   lockWaiters, conditionWaiters, buffer, 
                                   producerDone, consumerDone >>

c_complete(self) == /\ pc[self] = "c_complete"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 152, column 9 of macro called at line 362, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 153, column 9 of macro called at line 362, column 9.")
                    /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "Done"]
                    /\ UNCHANGED << taskState, joinWaiters, lockOwner, 
                                    lockWaiters, conditionWaiters, buffer, 
                                    producerDone, consumerDone >>

Consumer(self) == c_acquire(self) \/ c_wait_while_empty(self)
                     \/ c_consume(self) \/ c_mark_done(self)
                     \/ c_release(self) \/ c_complete(self)

Next == Scheduler \/ EventLoopHandler
           \/ (\E self \in {0}: Main(self))
           \/ (\E self \in {1}: Producer(self))
           \/ (\E self \in {2}: Consumer(self))

Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(Scheduler)
        /\ WF_vars(EventLoopHandler)
        /\ \A self \in {0} : WF_vars(Main(self))
        /\ \A self \in {1} : WF_vars(Producer(self))
        /\ \A self \in {2} : WF_vars(Consumer(self))

\* END TRANSLATION

=============================================================================
