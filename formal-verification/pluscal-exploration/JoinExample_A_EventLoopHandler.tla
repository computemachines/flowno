-------------------- MODULE JoinExample_A_EventLoopHandler --------------------
(*
 * Approach A: Event Loop Handler Process
 *
 * Tasks yield Command records to a shared queue. A separate EventLoopHandler
 * process dequeues and processes them, just like Python's event loop.
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

(* --algorithm JoinExample_A {
    variables
        \* Running task tracking - only one task runs at a time
        running = NoTask,

        \* Task states
        taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"],

        \* Join waiters: task -> set of tasks waiting for it
        joinWaiters = [t \in Tasks |-> {}],

        \* Command queue: sequence of command records
        \* Commands: [task |-> t, cmd |-> "Sleep"|"Join"|"Complete"|"Spawn", ...]
        commandQueue = <<>>;

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

        QueueSizeSmall == Len(commandQueue) <= 1

        \* Test invariant: Task2 cannot resume before Task1
        \* This SHOULD be violated if Task2 can wake before Task1
        Task2CannotResumeBeforeTask1 ==
            (pc[2] = "t2_join" \/ pc[2] = "t2_join_done") => ~IsSleeping(1)
    }

    macro yield_spawn(newTask) {
        commandQueue := Append(commandQueue, [task |-> self, cmd |-> "Spawn", newTask |-> newTask]);
        running := NoTask;
    }

    macro yield_sleep() {
        commandQueue := Append(commandQueue, [task |-> self, cmd |-> "Sleep"]);
        running := NoTask;
    }

    macro yield_join(target) {
        commandQueue := Append(commandQueue, [task |-> self, cmd |-> "Join", target |-> target]);
        running := NoTask;
    }

    macro yield_complete() {
        commandQueue := Append(commandQueue, [task |-> self, cmd |-> "Complete"]);
        running := NoTask;
    }

    \* Scheduler: picks a ready task and makes it Running
    fair process (Scheduler = 99)
    {
      sched:
        while (TRUE) {
            await running = NoTask /\ \E t \in Tasks : IsSchedulable(t)
                  /\ \A t2 \in Tasks : ~IsRunning(t2);
            with (t3 \in {t4 \in Tasks : IsSchedulable(t4)}) {
                running := t3;
                taskState[t3] := "Running";
            }
        }
    }

    \* Event Loop Handler: processes commands from the queue
    fair process (EventLoopHandler = 98)
    variable cmd = NoCmd;
    {
      handle:
        while (TRUE) {
            await commandQueue # <<>>;
            cmd := Head(commandQueue);
            commandQueue := Tail(commandQueue);

            if (cmd.cmd = "Sleep") {
                taskState[cmd.task] := "Sleeping";
            }
            else if (cmd.cmd = "Join") {
                if (IsDone(cmd.target)) {
                    \* Target already done - immediate
                    taskState[cmd.task] := "ReadyResuming";
                } else {
                    \* Target not done - block
                    taskState[cmd.task] := "Joining";
                    joinWaiters[cmd.target] := joinWaiters[cmd.target] \cup {cmd.task};
                }
            }
            else if (cmd.cmd = "Complete") {
                \* Set task Done AND wake all joiners in single assignment
                taskState := [t \in Tasks |->
                    IF t = cmd.task THEN "Done"
                    ELSE IF t \in joinWaiters[cmd.task] THEN "ReadyResuming"
                    ELSE taskState[t]];
                joinWaiters[cmd.task] := {};
            }
            else if (cmd.cmd = "Spawn") {
                \* Set new task Ready AND spawner ReadyResuming in single assignment
                taskState := [t \in Tasks |->
                    IF t = cmd.newTask THEN "Ready"
                    ELSE IF t = cmd.task THEN "ReadyResuming"
                    ELSE taskState[t]];
            }
        }
    }

    \* Waker: wakes sleeping tasks (models timer expiry)
    fair process (Waker = 97)
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

      main_spawn2:
        await running = self;
        yield_spawn(2);

      main_join1:
        await running = self;
        yield_join(1);

      main_join1_done:
        await running = self;
        \* Continue to join2

      main_join2:
        yield_join(2);

      main_join2_done:
        await running = self;
        \* Complete
        yield_complete();
    }

    \* Task1: just sleeps then completes
    fair process (Task1 \in {1})
    {
      t1_sleep:
        await running = self;
        yield_sleep();

      t1_wake:
        await running = self;
        yield_complete();
    }

    \* Task2: sleeps, then optionally joins Task1, then completes
    fair process (Task2 \in {2})
    {
      t2_sleep:
        await running = self;
        yield_sleep();

      t2_decide:
        await running = self;
        either {
            \* Branch 1: Perform the join
            yield_join(1);
          t2_join_done:
            await running = self;
            yield_complete();
        }
        or {
            \* Branch 2: Skip the join and finish immediately
            yield_complete();
        }
    }
} *)

\* BEGIN TRANSLATION
VARIABLES running, taskState, joinWaiters, commandQueue, pc

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

QueueSizeSmall == Len(commandQueue) <= 1



Task2CannotResumeBeforeTask1 ==
    (pc[2] = "t2_join" \/ pc[2] = "t2_join_done") => ~IsSleeping(1)

VARIABLE cmd

vars == << running, taskState, joinWaiters, commandQueue, pc, cmd >>

ProcSet == {99} \cup {98} \cup {97} \cup ({0}) \cup ({1}) \cup ({2})

Init == (* Global variables *)
        /\ running = NoTask
        /\ taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"]
        /\ joinWaiters = [t \in Tasks |-> {}]
        /\ commandQueue = <<>>
        (* Process EventLoopHandler *)
        /\ cmd = NoCmd
        /\ pc = [self \in ProcSet |-> CASE self = 99 -> "sched"
                                        [] self = 98 -> "handle"
                                        [] self = 97 -> "wake"
                                        [] self \in {0} -> "main_spawn1"
                                        [] self \in {1} -> "t1_sleep"
                                        [] self \in {2} -> "t2_sleep"]

sched == /\ pc[99] = "sched"
         /\ running = NoTask /\ \E t \in Tasks : IsSchedulable(t)
            /\ \A t2 \in Tasks : ~IsRunning(t2)
         /\ \E t3 \in {t4 \in Tasks : IsSchedulable(t4)}:
              /\ running' = t3
              /\ taskState' = [taskState EXCEPT ![t3] = "Running"]
         /\ pc' = [pc EXCEPT ![99] = "sched"]
         /\ UNCHANGED << joinWaiters, commandQueue, cmd >>

Scheduler == sched

handle == /\ pc[98] = "handle"
          /\ commandQueue # <<>>
          /\ cmd' = Head(commandQueue)
          /\ commandQueue' = Tail(commandQueue)
          /\ IF cmd'.cmd = "Sleep"
                THEN /\ taskState' = [taskState EXCEPT ![cmd'.task] = "Sleeping"]
                     /\ UNCHANGED joinWaiters
                ELSE /\ IF cmd'.cmd = "Join"
                           THEN /\ IF IsDone(cmd'.target)
                                      THEN /\ taskState' = [taskState EXCEPT ![cmd'.task] = "ReadyResuming"]
                                           /\ UNCHANGED joinWaiters
                                      ELSE /\ taskState' = [taskState EXCEPT ![cmd'.task] = "Joining"]
                                           /\ joinWaiters' = [joinWaiters EXCEPT ![cmd'.target] = joinWaiters[cmd'.target] \cup {cmd'.task}]
                           ELSE /\ IF cmd'.cmd = "Complete"
                                      THEN /\ taskState' =          [t \in Tasks |->
                                                           IF t = cmd'.task THEN "Done"
                                                           ELSE IF t \in joinWaiters[cmd'.task] THEN "ReadyResuming"
                                                           ELSE taskState[t]]
                                           /\ joinWaiters' = [joinWaiters EXCEPT ![cmd'.task] = {}]
                                      ELSE /\ IF cmd'.cmd = "Spawn"
                                                 THEN /\ taskState' =          [t \in Tasks |->
                                                                      IF t = cmd'.newTask THEN "Ready"
                                                                      ELSE IF t = cmd'.task THEN "ReadyResuming"
                                                                      ELSE taskState[t]]
                                                 ELSE /\ TRUE
                                                      /\ UNCHANGED taskState
                                           /\ UNCHANGED joinWaiters
          /\ pc' = [pc EXCEPT ![98] = "handle"]
          /\ UNCHANGED running

EventLoopHandler == handle

wake == /\ pc[97] = "wake"
        /\ \E t \in Tasks : IsSleeping(t)
        /\ \E t \in {t \in Tasks : IsSleeping(t)}:
             taskState' = [taskState EXCEPT ![t] = "ReadyResuming"]
        /\ pc' = [pc EXCEPT ![97] = "wake"]
        /\ UNCHANGED << running, joinWaiters, commandQueue, cmd >>

Waker == wake

main_spawn1(self) == /\ pc[self] = "main_spawn1"
                     /\ running = self
                     /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Spawn", newTask |-> 1])
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_spawn2"]
                     /\ UNCHANGED << taskState, joinWaiters, cmd >>

main_spawn2(self) == /\ pc[self] = "main_spawn2"
                     /\ running = self
                     /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Spawn", newTask |-> 2])
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "main_join1"]
                     /\ UNCHANGED << taskState, joinWaiters, cmd >>

main_join1(self) == /\ pc[self] = "main_join1"
                    /\ running = self
                    /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Join", target |-> 1])
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_join1_done"]
                    /\ UNCHANGED << taskState, joinWaiters, cmd >>

main_join1_done(self) == /\ pc[self] = "main_join1_done"
                         /\ running = self
                         /\ pc' = [pc EXCEPT ![self] = "main_join2"]
                         /\ UNCHANGED << running, taskState, joinWaiters, 
                                         commandQueue, cmd >>

main_join2(self) == /\ pc[self] = "main_join2"
                    /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Join", target |-> 2])
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "main_join2_done"]
                    /\ UNCHANGED << taskState, joinWaiters, cmd >>

main_join2_done(self) == /\ pc[self] = "main_join2_done"
                         /\ running = self
                         /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Complete"])
                         /\ running' = NoTask
                         /\ pc' = [pc EXCEPT ![self] = "Done"]
                         /\ UNCHANGED << taskState, joinWaiters, cmd >>

Main(self) == main_spawn1(self) \/ main_spawn2(self) \/ main_join1(self)
                 \/ main_join1_done(self) \/ main_join2(self)
                 \/ main_join2_done(self)

t1_sleep(self) == /\ pc[self] = "t1_sleep"
                  /\ running = self
                  /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Sleep"])
                  /\ running' = NoTask
                  /\ pc' = [pc EXCEPT ![self] = "t1_wake"]
                  /\ UNCHANGED << taskState, joinWaiters, cmd >>

t1_wake(self) == /\ pc[self] = "t1_wake"
                 /\ running = self
                 /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Complete"])
                 /\ running' = NoTask
                 /\ pc' = [pc EXCEPT ![self] = "Done"]
                 /\ UNCHANGED << taskState, joinWaiters, cmd >>

Task1(self) == t1_sleep(self) \/ t1_wake(self)

t2_sleep(self) == /\ pc[self] = "t2_sleep"
                  /\ running = self
                  /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Sleep"])
                  /\ running' = NoTask
                  /\ pc' = [pc EXCEPT ![self] = "t2_decide"]
                  /\ UNCHANGED << taskState, joinWaiters, cmd >>

t2_decide(self) == /\ pc[self] = "t2_decide"
                   /\ running = self
                   /\ \/ /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Join", target |-> 1])
                         /\ running' = NoTask
                         /\ pc' = [pc EXCEPT ![self] = "t2_join_done"]
                      \/ /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Complete"])
                         /\ running' = NoTask
                         /\ pc' = [pc EXCEPT ![self] = "Done"]
                   /\ UNCHANGED << taskState, joinWaiters, cmd >>

t2_join_done(self) == /\ pc[self] = "t2_join_done"
                      /\ running = self
                      /\ commandQueue' = Append(commandQueue, [task |-> self, cmd |-> "Complete"])
                      /\ running' = NoTask
                      /\ pc' = [pc EXCEPT ![self] = "Done"]
                      /\ UNCHANGED << taskState, joinWaiters, cmd >>

Task2(self) == t2_sleep(self) \/ t2_decide(self) \/ t2_join_done(self)

Next == Scheduler \/ EventLoopHandler \/ Waker
           \/ (\E self \in {0}: Main(self))
           \/ (\E self \in {1}: Task1(self))
           \/ (\E self \in {2}: Task2(self))

Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(Scheduler)
        /\ WF_vars(EventLoopHandler)
        /\ WF_vars(Waker)
        /\ \A self \in {0} : WF_vars(Main(self))
        /\ \A self \in {1} : WF_vars(Task1(self))
        /\ \A self \in {2} : WF_vars(Task2(self))

\* END TRANSLATION

=============================================================================
