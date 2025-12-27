-------------------- MODULE JoinExample_B_SchedulerDoesAll --------------------
(*
 * Approach B: Scheduler Handles Everything
 *
 * Scheduler does both scheduling AND command processing. Tasks just set
 * "pending command" state and release running. The scheduler handles the rest.
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

CONSTANTS NoTask, NoCmd

Tasks == {0, 1, 2}  \* 0=Main, 1=Task1, 2=Task2

(* --algorithm JoinExample_B {
    variables
        \* Running task tracking - only one task runs at a time
        running = NoTask,

        \* Task states
        taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"],

        \* Join waiters: task -> set of tasks waiting for it
        joinWaiters = [t \in Tasks |-> {}],

        \* Pending command per task (set by task, processed by scheduler)
        pendingCmd = [t \in Tasks |-> NoCmd];

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

        PendingCmdCountSmall == Cardinality({t \in Tasks : pendingCmd[t] # NoCmd}) <= 1
    }

    \* Scheduler: handles scheduling, command processing, and waking
    fair process (Scheduler \in {99})
    variable cmd = NoCmd;
    {
      sched:
        while (TRUE) {
            either {
                \* Schedule a ready task
                await running = NoTask /\ \E t \in Tasks : IsSchedulable(t)
                      /\ \A t2 \in Tasks : ~IsRunning(t2);
                with (t \in {t \in Tasks : IsSchedulable(t)}) {
                    running := t;
                    taskState[t] := "Running";
                }
            }
            or {
                \* Process a pending command
                await \E t \in Tasks : pendingCmd[t] # NoCmd;
                with (t \in {t \in Tasks : pendingCmd[t] # NoCmd}) {
                    cmd := pendingCmd[t];
                    pendingCmd[t] := NoCmd;

                    if (cmd.cmd = "Sleep") {
                        taskState[t] := "Sleeping";
                    }
                    else if (cmd.cmd = "Join") {
                        if (IsDone(cmd.target)) {
                            taskState[t] := "ReadyResuming";
                        } else {
                            taskState[t] := "Joining";
                            joinWaiters[cmd.target] := joinWaiters[cmd.target] \cup {t};
                        }
                    }
                    else if (cmd.cmd = "Complete") {
                        \* Set task Done AND wake all joiners in single assignment
                        taskState := [task \in Tasks |->
                            IF task = t THEN "Done"
                            ELSE IF task \in joinWaiters[t] THEN "ReadyResuming"
                            ELSE taskState[task]];
                        joinWaiters[t] := {};
                    }
                    else if (cmd.cmd = "Spawn") {
                        \* Set new task Ready AND spawner ReadyResuming in single assignment
                        taskState := [task \in Tasks |->
                            IF task = cmd.newTask THEN "Ready"
                            ELSE IF task = t THEN "ReadyResuming"
                            ELSE taskState[task]];
                    }
                }
            }
            or {
                \* Wake sleeping tasks (timer expiry)
                await \E t \in Tasks : IsSleeping(t);
                with (t \in {t \in Tasks : IsSleeping(t)}) {
                    taskState[t] := "ReadyResuming";
                }
            }
        }
    }

    \* Main task
    fair process (Main \in {0})
    {
      main_spawn1:
        await running = self;
        pendingCmd[self] := [cmd |-> "Spawn", newTask |-> 1];
        running := NoTask;

      main_spawn2:
        await running = self;
        pendingCmd[self] := [cmd |-> "Spawn", newTask |-> 2];
        running := NoTask;

      main_join1:
        await running = self;
        pendingCmd[self] := [cmd |-> "Join", target |-> 1];
        running := NoTask;

      main_join1_done:
        await running = self;
        \* Continue to join2

      main_join2:
        pendingCmd[self] := [cmd |-> "Join", target |-> 2];
        running := NoTask;

      main_join2_done:
        await running = self;
        pendingCmd[self] := [cmd |-> "Complete"];
        running := NoTask;
    }

    \* Task1: just sleeps then completes
    fair process (Task1 \in {1})
    {
      t1_sleep:
        await running = self;
        pendingCmd[self] := [cmd |-> "Sleep"];
        running := NoTask;

      t1_wake:
        await running = self;
        pendingCmd[self] := [cmd |-> "Complete"];
        running := NoTask;
    }

    \* Task2: sleeps, then joins Task1, then completes
    fair process (Task2 \in {2})
    {
      t2_sleep:
        await running = self;
        pendingCmd[self] := [cmd |-> "Sleep"];
        running := NoTask;

      t2_join:
        await running = self;
        pendingCmd[self] := [cmd |-> "Join", target |-> 1];
        running := NoTask;

      t2_join_done:
        await running = self;
        pendingCmd[self] := [cmd |-> "Complete"];
        running := NoTask;
    }
} *)

\* BEGIN TRANSLATION
VARIABLES running, taskState, joinWaiters, pendingCmd, pc

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

PendingCmdCountSmall == Cardinality({t \in Tasks : pendingCmd[t] # NoCmd}) <= 1

VARIABLE cmd

vars == << running, taskState, joinWaiters, pendingCmd, pc, cmd >>

ProcSet == ({99}) \cup ({0}) \cup ({1}) \cup ({2})

Init == (* Global variables *)
        /\ running = NoTask
        /\ taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"]
        /\ joinWaiters = [t \in Tasks |-> {}]
        /\ pendingCmd = [t \in Tasks |-> NoCmd]
        (* Process Scheduler *)
        /\ cmd = [self \in {99} |-> NoCmd]
        /\ pc = [self \in ProcSet |-> CASE self \in {99} -> "sched"
                                        [] self \in {0} -> "main_spawn1"
                                        [] self \in {1} -> "t1_sleep"
                                        [] self \in {2} -> "t2_sleep"]

sched(self) == /\ pc[self] = "sched"
               /\ \/ /\ running = NoTask /\ \E t \in Tasks : IsSchedulable(t)
                        /\ \A t2 \in Tasks : ~IsRunning(t2)
                     /\ \E t \in {t \in Tasks : IsSchedulable(t)}:
                          /\ running' = t
                          /\ taskState' = [taskState EXCEPT ![t] = "Running"]
                     /\ UNCHANGED <<joinWaiters, pendingCmd, cmd>>
                  \/ /\ \E t \in Tasks : pendingCmd[t] # NoCmd
                     /\ \E t \in {t \in Tasks : pendingCmd[t] # NoCmd}:
                          /\ cmd' = [cmd EXCEPT ![self] = pendingCmd[t]]
                          /\ pendingCmd' = [pendingCmd EXCEPT ![t] = NoCmd]
                          /\ IF cmd'[self].cmd = "Sleep"
                                THEN /\ taskState' = [taskState EXCEPT ![t] = "Sleeping"]
                                     /\ UNCHANGED joinWaiters
                                ELSE /\ IF cmd'[self].cmd = "Join"
                                           THEN /\ IF IsDone(cmd'[self].target)
                                                      THEN /\ taskState' = [taskState EXCEPT ![t] = "ReadyResuming"]
                                                           /\ UNCHANGED joinWaiters
                                                      ELSE /\ taskState' = [taskState EXCEPT ![t] = "Joining"]
                                                           /\ joinWaiters' = [joinWaiters EXCEPT ![cmd'[self].target] = joinWaiters[cmd'[self].target] \cup {t}]
                                           ELSE /\ IF cmd'[self].cmd = "Complete"
                                                      THEN /\ taskState' =          [task \in Tasks |->
                                                                           IF task = t THEN "Done"
                                                                           ELSE IF task \in joinWaiters[t] THEN "ReadyResuming"
                                                                           ELSE taskState[task]]
                                                           /\ joinWaiters' = [joinWaiters EXCEPT ![t] = {}]
                                                      ELSE /\ IF cmd'[self].cmd = "Spawn"
                                                                 THEN /\ taskState' =          [task \in Tasks |->
                                                                                      IF task = cmd'[self].newTask THEN "Ready"
                                                                                      ELSE IF task = t THEN "ReadyResuming"
                                                                                      ELSE taskState[task]]
                                                                 ELSE /\ TRUE
                                                                      /\ UNCHANGED taskState
                                                           /\ UNCHANGED joinWaiters
                     /\ UNCHANGED running
                  \/ /\ \E t \in Tasks : IsSleeping(t)
                     /\ \E t \in {t \in Tasks : IsSleeping(t)}:
                          taskState' = [taskState EXCEPT ![t] = "ReadyResuming"]
                     /\ UNCHANGED <<running, joinWaiters, pendingCmd, cmd>>
               /\ pc' = [pc EXCEPT ![self] = "sched"]

Scheduler(self) == sched(self)

main_spawn1(self) == /\ pc[self] = "main_spawn1"
                     /\ running = self
                     /\ pendingCmd' = [pendingCmd EXCEPT ![self] = [cmd |-> "Spawn", newTask |-> 1]]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_spawn2"]
                     /\ UNCHANGED << taskState, joinWaiters, cmd >>

main_spawn2(self) == /\ pc[self] = "main_spawn2"
                     /\ running = self
                     /\ pendingCmd' = [pendingCmd EXCEPT ![self] = [cmd |-> "Spawn", newTask |-> 2]]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_join1"]
                     /\ UNCHANGED << taskState, joinWaiters, cmd >>

main_join1(self) == /\ pc[self] = "main_join1"
                    /\ running = self
                    /\ pendingCmd' = [pendingCmd EXCEPT ![self] = [cmd |-> "Join", target |-> 1]]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_join1_done"]
                    /\ UNCHANGED << taskState, joinWaiters, cmd >>

main_join1_done(self) == /\ pc[self] = "main_join1_done"
                         /\ running = self
                         /\ pc' = [pc EXCEPT ![self] = "main_join2"]
                         /\ UNCHANGED << running, taskState, joinWaiters, 
                                         pendingCmd, cmd >>

main_join2(self) == /\ pc[self] = "main_join2"
                    /\ pendingCmd' = [pendingCmd EXCEPT ![self] = [cmd |-> "Join", target |-> 2]]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_join2_done"]
                    /\ UNCHANGED << taskState, joinWaiters, cmd >>

main_join2_done(self) == /\ pc[self] = "main_join2_done"
                         /\ running = self
                         /\ pendingCmd' = [pendingCmd EXCEPT ![self] = [cmd |-> "Complete"]]
                         /\ running' = NoTask
                         /\ pc' = [pc EXCEPT ![self] = "Done"]
                         /\ UNCHANGED << taskState, joinWaiters, cmd >>

Main(self) == main_spawn1(self) \/ main_spawn2(self) \/ main_join1(self)
                 \/ main_join1_done(self) \/ main_join2(self)
                 \/ main_join2_done(self)

t1_sleep(self) == /\ pc[self] = "t1_sleep"
                  /\ running = self
                  /\ pendingCmd' = [pendingCmd EXCEPT ![self] = [cmd |-> "Sleep"]]
                  /\ running' = NoTask
                  /\ pc' = [pc EXCEPT ![self] = "t1_wake"]
                  /\ UNCHANGED << taskState, joinWaiters, cmd >>

t1_wake(self) == /\ pc[self] = "t1_wake"
                 /\ running = self
                 /\ pendingCmd' = [pendingCmd EXCEPT ![self] = [cmd |-> "Complete"]]
                 /\ running' = NoTask
                 /\ pc' = [pc EXCEPT ![self] = "Done"]
                 /\ UNCHANGED << taskState, joinWaiters, cmd >>

Task1(self) == t1_sleep(self) \/ t1_wake(self)

t2_sleep(self) == /\ pc[self] = "t2_sleep"
                  /\ running = self
                  /\ pendingCmd' = [pendingCmd EXCEPT ![self] = [cmd |-> "Sleep"]]
                  /\ running' = NoTask
                  /\ pc' = [pc EXCEPT ![self] = "t2_join"]
                  /\ UNCHANGED << taskState, joinWaiters, cmd >>

t2_join(self) == /\ pc[self] = "t2_join"
                 /\ running = self
                 /\ pendingCmd' = [pendingCmd EXCEPT ![self] = [cmd |-> "Join", target |-> 1]]
                 /\ running' = NoTask
                 /\ pc' = [pc EXCEPT ![self] = "t2_join_done"]
                 /\ UNCHANGED << taskState, joinWaiters, cmd >>

t2_join_done(self) == /\ pc[self] = "t2_join_done"
                      /\ running = self
                      /\ pendingCmd' = [pendingCmd EXCEPT ![self] = [cmd |-> "Complete"]]
                      /\ running' = NoTask
                      /\ pc' = [pc EXCEPT ![self] = "Done"]
                      /\ UNCHANGED << taskState, joinWaiters, cmd >>

Task2(self) == t2_sleep(self) \/ t2_join(self) \/ t2_join_done(self)

Next == (\E self \in {99}: Scheduler(self))
           \/ (\E self \in {0}: Main(self))
           \/ (\E self \in {1}: Task1(self))
           \/ (\E self \in {2}: Task2(self))

Spec == /\ Init /\ [][Next]_vars
        /\ \A self \in {99} : WF_vars(Scheduler(self))
        /\ \A self \in {0} : WF_vars(Main(self))
        /\ \A self \in {1} : WF_vars(Task1(self))
        /\ \A self \in {2} : WF_vars(Task2(self))

\* END TRANSLATION

=============================================================================
