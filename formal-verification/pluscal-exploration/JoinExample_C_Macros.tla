------------------------ MODULE JoinExample_C_Macros ------------------------
(*
 * Approach C: Macros + Minimal Background Processes
 *
 * Tasks use macros that directly manipulate state. Background processes only
 * handle things tasks can't do themselves (waking sleepers).
 *
 * Python equivalent:
 *   async def task1():
 *       await sleep(1)
 *
 *   async def task2(task1_handle):
 *       await sleep(1)
 *       await task1_handle.join()
 *
 *   async def main():
 *       task1_handle = await spawn(task1())
 *       task2_handle = await spawn(task2(task1_handle))
 *       await task1_handle.join()
 *       await task2_handle.join()
 *)
EXTENDS Integers, Sequences, FiniteSets

CONSTANTS NoTask

Tasks == {0, 1, 2}  \* 0=Main, 1=Task1, 2=Task2

(* --algorithm JoinExample_C {
    variables
        \* Running task tracking - only one task runs at a time
        running = NoTask,

        \* Task states
        taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"],

        \* Join waiters: task -> set of tasks waiting for it
        joinWaiters = [t \in Tasks |-> {}];

    define {
        \* State predicates
        IsNonexistent(t) == taskState[t] = "Nonexistent"
        IsReady(t) == taskState[t] = "Ready"
        IsReadyResuming(t) == taskState[t] = "ReadyResuming"
        IsRunning(t) == taskState[t] = "Running"
        IsSleeping(t) == taskState[t] = "Sleeping"
        IsJoining(t) == taskState[t] = "Joining"
        IsDone(t) == taskState[t] = "Done"

        \* Schedulable = Ready or ReadyResuming
        IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)

        \* Invariants
        AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1

        JoinWaitersConsistent ==
            \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)

        \* Liveness: all tasks eventually complete
        EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2))
    }

    \* Macro: yield a sleep command
    macro yield_sleep() {
        taskState[self] := "Sleeping";
    }

    \* Macro: yield a join command (handles immediate vs blocking)
    macro yield_join(target) {
        if (IsDone(target)) {
            \* Immediate: target already done
            taskState[self] := "Ready";
        } else {
            \* Block: wait for target
            taskState[self] := "Joining";
            joinWaiters[target] := joinWaiters[target] \cup {self};
        }
    }

    \* Macro: yield a spawn command
    macro yield_spawn(newTask) {
        \* Set new task Ready AND spawner Ready in single assignment
        taskState := [t \in Tasks |->
            IF t = newTask THEN "Ready"
            ELSE IF t = self THEN "Ready"
            ELSE taskState[t]];
    }

    \* Macro: complete the task and wake joiners
    macro complete() {
        \* Set task Done AND wake all joiners in single assignment
        taskState := [t \in Tasks |->
            IF t = self THEN "Done"
            ELSE IF t \in joinWaiters[self] THEN "ReadyResuming"
            ELSE taskState[t]];
        joinWaiters[self] := {};
    }

    \* Scheduler: picks a ready task and makes it Running
    fair process (Scheduler = 99)
    {
      sched:
        while (TRUE) {
            await running = NoTask /\ \E t \in Tasks : IsSchedulable(t);
            with (t \in {t \in Tasks : IsSchedulable(t)}) {
                running := t;
                taskState[t] := "Running";
            }
        }
    }

    \* Waker: wakes sleeping tasks (models timer expiry)
    fair process (Waker = 98)
    {
      wake:
        while (TRUE) {
            await \E t \in Tasks : IsSleeping(t);
            with (t \in {t \in Tasks : IsSleeping(t)}) {
                taskState[t] := "ReadyResuming";
            }
        }
    }

    \* Main task
    fair process (Main \in {0})
    {
      main_spawn1:
        await running = self;
        yield_spawn(1);
        running := NoTask;

      main_spawn2:
        await running = self;
        yield_spawn(2);
        running := NoTask;

      main_join1:
        await running = self;
        yield_join(1);
        running := NoTask;

      main_join1_done:
        await running = self;
        \* Continue to join2
        yield_join(2);
        running := NoTask;

      main_join2_done:
        await running = self;
        complete();
        running := NoTask;
    }

    \* Task1: just sleeps then completes
    fair process (Task1 \in {1})
    {
      t1_sleep:
        await running = self;
        yield_sleep();
        running := NoTask;

      t1_wake:
        await running = self;
        complete();
        running := NoTask;
    }

    \* Task2: sleeps, then joins Task1, then completes
    fair process (Task2 \in {2})
    {
      t2_sleep:
        await running = self;
        yield_sleep();
        running := NoTask;

      t2_join:
        await running = self;
        yield_join(1);
        running := NoTask;

      t2_done:
        await running = self;
        complete();
        running := NoTask;
    }
} *)

\* BEGIN TRANSLATION
VARIABLES running, taskState, joinWaiters, pc

(* define statement *)
IsNonexistent(t) == taskState[t] = "Nonexistent"
IsReady(t) == taskState[t] = "Ready"
IsReadyResuming(t) == taskState[t] = "ReadyResuming"
IsRunning(t) == taskState[t] = "Running"
IsSleeping(t) == taskState[t] = "Sleeping"
IsJoining(t) == taskState[t] = "Joining"
IsDone(t) == taskState[t] = "Done"


IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)


AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1

JoinWaitersConsistent ==
    \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)


EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2))


vars == << running, taskState, joinWaiters, pc >>

ProcSet == {99} \cup {98} \cup ({0}) \cup ({1}) \cup ({2})

Init == (* Global variables *)
        /\ running = NoTask
        /\ taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"]
        /\ joinWaiters = [t \in Tasks |-> {}]
        /\ pc = [self \in ProcSet |-> CASE self = 99 -> "sched"
                                        [] self = 98 -> "wake"
                                        [] self \in {0} -> "main_spawn1"
                                        [] self \in {1} -> "t1_sleep"
                                        [] self \in {2} -> "t2_sleep"]

sched == /\ pc[99] = "sched"
         /\ running = NoTask /\ \E t \in Tasks : IsSchedulable(t)
         /\ \E t \in {t \in Tasks : IsSchedulable(t)}:
              /\ running' = t
              /\ taskState' = [taskState EXCEPT ![t] = "Running"]
         /\ pc' = [pc EXCEPT ![99] = "sched"]
         /\ UNCHANGED joinWaiters

Scheduler == sched

wake == /\ pc[98] = "wake"
        /\ \E t \in Tasks : IsSleeping(t)
        /\ \E t \in {t \in Tasks : IsSleeping(t)}:
             taskState' = [taskState EXCEPT ![t] = "ReadyResuming"]
        /\ pc' = [pc EXCEPT ![98] = "wake"]
        /\ UNCHANGED << running, joinWaiters >>

Waker == wake

main_spawn1(self) == /\ pc[self] = "main_spawn1"
                     /\ running = self
                     /\ taskState' =          [t \in Tasks |->
                                     IF t = 1 THEN "Ready"
                                     ELSE IF t = self THEN "Ready"
                                     ELSE taskState[t]]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_spawn2"]
                     /\ UNCHANGED joinWaiters

main_spawn2(self) == /\ pc[self] = "main_spawn2"
                     /\ running = self
                     /\ taskState' =          [t \in Tasks |->
                                     IF t = 2 THEN "Ready"
                                     ELSE IF t = self THEN "Ready"
                                     ELSE taskState[t]]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_join1"]
                     /\ UNCHANGED joinWaiters

main_join1(self) == /\ pc[self] = "main_join1"
                    /\ running = self
                    /\ IF IsDone(1)
                          THEN /\ taskState' = [taskState EXCEPT ![self] = "Ready"]
                               /\ UNCHANGED joinWaiters
                          ELSE /\ taskState' = [taskState EXCEPT ![self] = "Joining"]
                               /\ joinWaiters' = [joinWaiters EXCEPT ![1] = joinWaiters[1] \cup {self}]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_join1_done"]

main_join1_done(self) == /\ pc[self] = "main_join1_done"
                         /\ running = self
                         /\ IF IsDone(2)
                               THEN /\ taskState' = [taskState EXCEPT ![self] = "Ready"]
                                    /\ UNCHANGED joinWaiters
                               ELSE /\ taskState' = [taskState EXCEPT ![self] = "Joining"]
                                    /\ joinWaiters' = [joinWaiters EXCEPT ![2] = joinWaiters[2] \cup {self}]
                         /\ running' = NoTask
                         /\ pc' = [pc EXCEPT ![self] = "main_join2_done"]

main_join2_done(self) == /\ pc[self] = "main_join2_done"
                         /\ running = self
                         /\ taskState' =          [t \in Tasks |->
                                         IF t = self THEN "Done"
                                         ELSE IF t \in joinWaiters[self] THEN "ReadyResuming"
                                         ELSE taskState[t]]
                         /\ joinWaiters' = [joinWaiters EXCEPT ![self] = {}]
                         /\ running' = NoTask
                         /\ pc' = [pc EXCEPT ![self] = "Done"]

Main(self) == main_spawn1(self) \/ main_spawn2(self) \/ main_join1(self)
                 \/ main_join1_done(self) \/ main_join2_done(self)

t1_sleep(self) == /\ pc[self] = "t1_sleep"
                  /\ running = self
                  /\ taskState' = [taskState EXCEPT ![self] = "Sleeping"]
                  /\ running' = NoTask
                  /\ pc' = [pc EXCEPT ![self] = "t1_wake"]
                  /\ UNCHANGED joinWaiters

t1_wake(self) == /\ pc[self] = "t1_wake"
                 /\ running = self
                 /\ taskState' =          [t \in Tasks |->
                                 IF t = self THEN "Done"
                                 ELSE IF t \in joinWaiters[self] THEN "ReadyResuming"
                                 ELSE taskState[t]]
                 /\ joinWaiters' = [joinWaiters EXCEPT ![self] = {}]
                 /\ running' = NoTask
                 /\ pc' = [pc EXCEPT ![self] = "Done"]

Task1(self) == t1_sleep(self) \/ t1_wake(self)

t2_sleep(self) == /\ pc[self] = "t2_sleep"
                  /\ running = self
                  /\ taskState' = [taskState EXCEPT ![self] = "Sleeping"]
                  /\ running' = NoTask
                  /\ pc' = [pc EXCEPT ![self] = "t2_join"]
                  /\ UNCHANGED joinWaiters

t2_join(self) == /\ pc[self] = "t2_join"
                 /\ running = self
                 /\ IF IsDone(1)
                       THEN /\ taskState' = [taskState EXCEPT ![self] = "Ready"]
                            /\ UNCHANGED joinWaiters
                       ELSE /\ taskState' = [taskState EXCEPT ![self] = "Joining"]
                            /\ joinWaiters' = [joinWaiters EXCEPT ![1] = joinWaiters[1] \cup {self}]
                 /\ running' = NoTask
                 /\ pc' = [pc EXCEPT ![self] = "t2_done"]

t2_done(self) == /\ pc[self] = "t2_done"
                 /\ running = self
                 /\ taskState' =          [t \in Tasks |->
                                 IF t = self THEN "Done"
                                 ELSE IF t \in joinWaiters[self] THEN "ReadyResuming"
                                 ELSE taskState[t]]
                 /\ joinWaiters' = [joinWaiters EXCEPT ![self] = {}]
                 /\ running' = NoTask
                 /\ pc' = [pc EXCEPT ![self] = "Done"]

Task2(self) == t2_sleep(self) \/ t2_join(self) \/ t2_done(self)

Next == Scheduler \/ Waker
           \/ (\E self \in {0}: Main(self))
           \/ (\E self \in {1}: Task1(self))
           \/ (\E self \in {2}: Task2(self))

Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(Scheduler)
        /\ WF_vars(Waker)
        /\ \A self \in {0} : WF_vars(Main(self))
        /\ \A self \in {1} : WF_vars(Task1(self))
        /\ \A self \in {2} : WF_vars(Task2(self))

\* END TRANSLATION

=============================================================================
