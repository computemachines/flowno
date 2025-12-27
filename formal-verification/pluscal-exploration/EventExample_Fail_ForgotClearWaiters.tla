------------------------ MODULE EventExample_Fail_ForgotClearWaiters ------------------------
(*
 * PURPOSE: NEGATIVE TEST - Forgot to clear waiters after EventSet
 * EXPECTED: Should violate SetEventNoWaiters invariant
 *
 * This spec models the behavior of two concurrent tasks using an Event,
 * verifying that event wait/set operations work correctly under all
 * possible interleavings in a cooperative single-threaded event loop.
 *
 * WHY THIS EXAMPLE:
 * - Tests one-shot event semantics (once set, stays set)
 * - Tests broadcast wake semantics (set wakes all waiters)
 * - Tests fast path (wait when already set returns immediately)
 * - Verifies atomicity of wake-all operations
 * - Ensures only one task runs at a time (single-threaded constraint)
 * - Maps to EventLoop.py command processing architecture
 *
 * Python equivalent being modeled:
 *   event = Event()
 *
 *   async def waiter_task():
 *       print("Waiter: waiting for event")
 *       await event.wait()
 *       print("Waiter: event received!")
 *
 *   async def setter_task():
 *       print("Setter: setting event")
 *       await event.set()
 *       print("Setter: event set")
 *
 *   async def main():
 *       task1 = await spawn(waiter_task())
 *       task2 = await spawn(setter_task())
 *       await task1.join()
 *       await task2.join()
 *
 * VERIFICATION GOALS:
 * - Waiter should eventually be woken after event is set
 * - Event remains set after first set() call
 * - No waiters remain after event is set
 * - All tasks eventually complete
 * - Single-threaded execution maintained
 *
 * ARCHITECTURE:
 * This uses Approach A (EventLoop Handler) from the JoinExample exploration.
 * Tasks yield commands via macros, a Handler process makes all decisions about
 * blocking/immediate execution, matching the Python EventLoop.py implementation.
 *)
EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS NoTask, NoCmd

Tasks == {0, 1, 2}  \* 0=Main, 1=Waiter, 2=Setter

(* --algorithm EventExample {
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

        \* === Event state ===

        \* Event set flag (one-shot, stays set once set)
        eventSet = FALSE,

        \* Tasks blocked waiting on event.wait()
        eventWaiters = {},

        \* === Application state for verification ===

        \* Track that waiter received the event
        waiterReceived = FALSE,
        \* Track that setter completed its work
        setterCompleted = FALSE;

    define {
        \* === State predicates (matching EventLoop.tla) ===

        IsNonexistent(t) == taskState[t] = "Nonexistent"
        IsReady(t) == taskState[t] = "Ready"
        IsReadyResuming(t) == taskState[t] = "ReadyResuming"
        IsRunning(t) == taskState[t] = "Running"
        IsWaitingEvent(t) == taskState[t] = "WaitingEvent"
        IsJoining(t) == taskState[t] = "Joining"
        IsDone(t) == taskState[t] = "Done"
        IsError(t) == taskState[t] = "Error"

        IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)

        \* === Invariants ===

        \* CRITICAL: Only one task can be Running at a time
        AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1

        \* Running variable is consistent with taskState
        \* Note: When a task yields (running = NoTask, pendingCommand # NoCmd),
        \* its taskState is still "Running" until the handler processes the command
        RunningConsistent ==
            /\ (running # NoTask => IsRunning(running))
            /\ (running = NoTask /\ pendingCommand = NoCmd => ~\E t \in Tasks : IsRunning(t))

        \* Event waiters are consistent with task states
        EventWaitersConsistent ==
            \A w \in eventWaiters : IsWaitingEvent(w)

        \* Once event is set, no waiters should remain (all woken)
        SetEventNoWaiters ==
            eventSet => eventWaiters = {}

        \* Join waiters are consistent
        JoinWaitersConsistent ==
            \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)

        \* Event is one-shot: once set, stays set
        EventOnceSet ==
            eventSet => []eventSet

        \* === Liveness properties ===

        \* Waiter should eventually receive the event
        EventuallyWaiterReceives == <>(waiterReceived)

        \* Setter should eventually complete
        EventuallySetterCompletes == <>(setterCompleted)

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

    macro yield_event_wait() {
        assert pendingCommand = NoCmd;
        assert running = self;
        assert taskState[self] = "Running";
        pendingCommand := [cmd |-> "EventWait", task |-> self];
        running := NoTask;
    }

    macro yield_event_set() {
        assert pendingCommand = NoCmd;
        assert running = self;
        assert taskState[self] = "Running";
        pendingCommand := [cmd |-> "EventSet", task |-> self];
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
    \* This is the heart of the event loop - all event logic, spawning, joining, etc.
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

            else if (pendingCommand.cmd = "EventWait") {
                \* EventWait: wait for event to be set
                if (eventSet) {
                    \* Fast path: event already set - immediate resume
                    taskState[pendingCommand.task] := "Ready";
                } else {
                    \* Event not set - block until set
                    taskState[pendingCommand.task] := "WaitingEvent";
                    eventWaiters := eventWaiters \union {pendingCommand.task};
                };
            }

            else if (pendingCommand.cmd = "EventSet") {
                \* EventSet: set event and wake all waiting tasks atomically
                eventSet := TRUE;
                taskState := [t \in Tasks |->
                    IF t \in eventWaiters THEN "ReadyResuming"
                    ELSE IF t = pendingCommand.task THEN "Ready"
                    ELSE taskState[t]];
                \* BUG: Forgot to clear waiters!
                \* eventWaiters := {};
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

    \* Main task: spawns waiter and setter, waits for them
    fair process (Main \in {0})
    {
      main_spawn_waiter:
        await running = self;
        yield_spawn(1);

      main_spawn_setter:
        await running = self;
        yield_spawn(2);

      main_join_waiter:
        await running = self;
        yield_join(1);

      main_join_setter:
        await running = self;
        yield_join(2);

      main_complete:
        await running = self;
        yield_complete();
    }

    \* Waiter task: waits on event, marks received
    fair process (Waiter \in {1})
    {
      waiter_wait:
        await running = self;
        yield_event_wait();

      waiter_received:
        await running = self;
        waiterReceived := TRUE;

      waiter_complete:
        await running = self;
        yield_complete();
    }

    \* Setter task: sets event, marks completed
    fair process (Setter \in {2})
    {
      setter_set:
        await running = self;
        yield_event_set();

      setter_completed:
        await running = self;
        setterCompleted := TRUE;

      setter_complete:
        await running = self;
        yield_complete();
    }
} *)

\* BEGIN TRANSLATION
VARIABLES running, pendingCommand, taskState, joinWaiters, eventSet, 
          eventWaiters, waiterReceived, setterCompleted, pc

(* define statement *)
IsNonexistent(t) == taskState[t] = "Nonexistent"
IsReady(t) == taskState[t] = "Ready"
IsReadyResuming(t) == taskState[t] = "ReadyResuming"
IsRunning(t) == taskState[t] = "Running"
IsWaitingEvent(t) == taskState[t] = "WaitingEvent"
IsJoining(t) == taskState[t] = "Joining"
IsDone(t) == taskState[t] = "Done"
IsError(t) == taskState[t] = "Error"

IsSchedulable(t) == IsReady(t) \/ IsReadyResuming(t)




AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1




RunningConsistent ==
    /\ (running # NoTask => IsRunning(running))
    /\ (running = NoTask /\ pendingCommand = NoCmd => ~\E t \in Tasks : IsRunning(t))


EventWaitersConsistent ==
    \A w \in eventWaiters : IsWaitingEvent(w)


SetEventNoWaiters ==
    eventSet => eventWaiters = {}


JoinWaitersConsistent ==
    \A t \in Tasks : \A w \in joinWaiters[t] : IsJoining(w)


EventOnceSet ==
    eventSet => []eventSet




EventuallyWaiterReceives == <>(waiterReceived)


EventuallySetterCompletes == <>(setterCompleted)


EventuallyAllDone == <>(IsDone(0) /\ IsDone(1) /\ IsDone(2))


vars == << running, pendingCommand, taskState, joinWaiters, eventSet, 
           eventWaiters, waiterReceived, setterCompleted, pc >>

ProcSet == {99} \cup {98} \cup ({0}) \cup ({1}) \cup ({2})

Init == (* Global variables *)
        /\ running = NoTask
        /\ pendingCommand = NoCmd
        /\ taskState = [t \in Tasks |-> IF t = 0 THEN "Ready" ELSE "Nonexistent"]
        /\ joinWaiters = [t \in Tasks |-> {}]
        /\ eventSet = FALSE
        /\ eventWaiters = {}
        /\ waiterReceived = FALSE
        /\ setterCompleted = FALSE
        /\ pc = [self \in ProcSet |-> CASE self = 99 -> "sched"
                                        [] self = 98 -> "handle"
                                        [] self \in {0} -> "main_spawn_waiter"
                                        [] self \in {1} -> "waiter_wait"
                                        [] self \in {2} -> "setter_set"]

sched == /\ pc[99] = "sched"
         /\ pendingCommand = NoCmd /\ running = NoTask /\ \E t \in Tasks : IsSchedulable(t)
         /\ \E t \in {t \in Tasks : IsSchedulable(t)}:
              /\ Assert(~\E t2 \in Tasks : taskState[t2] = "Running", 
                        "Failure of assertion at line 195, column 17.")
              /\ running' = t
              /\ taskState' = [taskState EXCEPT ![t] = "Running"]
         /\ pc' = [pc EXCEPT ![99] = "sched"]
         /\ UNCHANGED << pendingCommand, joinWaiters, eventSet, eventWaiters, 
                         waiterReceived, setterCompleted >>

Scheduler == sched

handle == /\ pc[98] = "handle"
          /\ pendingCommand # NoCmd
          /\ Assert(running = NoTask, 
                    "Failure of assertion at line 210, column 13.")
          /\ IF pendingCommand.cmd = "Spawn"
                THEN /\ taskState' =          [t \in Tasks |->
                                     IF t = pendingCommand.newTask THEN "Ready"
                                     ELSE IF t = pendingCommand.task THEN "Ready"
                                     ELSE taskState[t]]
                     /\ UNCHANGED << joinWaiters, eventSet, eventWaiters >>
                ELSE /\ IF pendingCommand.cmd = "Join"
                           THEN /\ IF IsDone(pendingCommand.target)
                                      THEN /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                           /\ UNCHANGED joinWaiters
                                      ELSE /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Joining"]
                                           /\ joinWaiters' = [joinWaiters EXCEPT ![pendingCommand.target] = joinWaiters[pendingCommand.target] \union {pendingCommand.task}]
                                /\ UNCHANGED << eventSet, eventWaiters >>
                           ELSE /\ IF pendingCommand.cmd = "EventWait"
                                      THEN /\ IF eventSet
                                                 THEN /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "Ready"]
                                                      /\ UNCHANGED eventWaiters
                                                 ELSE /\ taskState' = [taskState EXCEPT ![pendingCommand.task] = "WaitingEvent"]
                                                      /\ eventWaiters' = (eventWaiters \union {pendingCommand.task})
                                           /\ UNCHANGED << joinWaiters, 
                                                           eventSet >>
                                      ELSE /\ IF pendingCommand.cmd = "EventSet"
                                                 THEN /\ eventSet' = TRUE
                                                      /\ taskState' =          [t \in Tasks |->
                                                                      IF t \in eventWaiters THEN "ReadyResuming"
                                                                      ELSE IF t = pendingCommand.task THEN "Ready"
                                                                      ELSE taskState[t]]
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
                                                      /\ UNCHANGED eventSet
                                           /\ UNCHANGED eventWaiters
          /\ pendingCommand' = NoCmd
          /\ pc' = [pc EXCEPT ![98] = "handle"]
          /\ UNCHANGED << running, waiterReceived, setterCompleted >>

EventLoopHandler == handle

main_spawn_waiter(self) == /\ pc[self] = "main_spawn_waiter"
                           /\ running = self
                           /\ Assert(pendingCommand = NoCmd, 
                                     "Failure of assertion at line 145, column 9 of macro called at line 279, column 9.")
                           /\ Assert(running = self, 
                                     "Failure of assertion at line 146, column 9 of macro called at line 279, column 9.")
                           /\ Assert(taskState[self] = "Running", 
                                     "Failure of assertion at line 147, column 9 of macro called at line 279, column 9.")
                           /\ pendingCommand' = [cmd |-> "Spawn", task |-> self, newTask |-> 1]
                           /\ running' = NoTask
                           /\ pc' = [pc EXCEPT ![self] = "main_spawn_setter"]
                           /\ UNCHANGED << taskState, joinWaiters, eventSet, 
                                           eventWaiters, waiterReceived, 
                                           setterCompleted >>

main_spawn_setter(self) == /\ pc[self] = "main_spawn_setter"
                           /\ running = self
                           /\ Assert(pendingCommand = NoCmd, 
                                     "Failure of assertion at line 145, column 9 of macro called at line 283, column 9.")
                           /\ Assert(running = self, 
                                     "Failure of assertion at line 146, column 9 of macro called at line 283, column 9.")
                           /\ Assert(taskState[self] = "Running", 
                                     "Failure of assertion at line 147, column 9 of macro called at line 283, column 9.")
                           /\ pendingCommand' = [cmd |-> "Spawn", task |-> self, newTask |-> 2]
                           /\ running' = NoTask
                           /\ pc' = [pc EXCEPT ![self] = "main_join_waiter"]
                           /\ UNCHANGED << taskState, joinWaiters, eventSet, 
                                           eventWaiters, waiterReceived, 
                                           setterCompleted >>

main_join_waiter(self) == /\ pc[self] = "main_join_waiter"
                          /\ running = self
                          /\ Assert(pendingCommand = NoCmd, 
                                    "Failure of assertion at line 153, column 9 of macro called at line 287, column 9.")
                          /\ Assert(running = self, 
                                    "Failure of assertion at line 154, column 9 of macro called at line 287, column 9.")
                          /\ Assert(taskState[self] = "Running", 
                                    "Failure of assertion at line 155, column 9 of macro called at line 287, column 9.")
                          /\ pendingCommand' = [cmd |-> "Join", task |-> self, target |-> 1]
                          /\ running' = NoTask
                          /\ pc' = [pc EXCEPT ![self] = "main_join_setter"]
                          /\ UNCHANGED << taskState, joinWaiters, eventSet, 
                                          eventWaiters, waiterReceived, 
                                          setterCompleted >>

main_join_setter(self) == /\ pc[self] = "main_join_setter"
                          /\ running = self
                          /\ Assert(pendingCommand = NoCmd, 
                                    "Failure of assertion at line 153, column 9 of macro called at line 291, column 9.")
                          /\ Assert(running = self, 
                                    "Failure of assertion at line 154, column 9 of macro called at line 291, column 9.")
                          /\ Assert(taskState[self] = "Running", 
                                    "Failure of assertion at line 155, column 9 of macro called at line 291, column 9.")
                          /\ pendingCommand' = [cmd |-> "Join", task |-> self, target |-> 2]
                          /\ running' = NoTask
                          /\ pc' = [pc EXCEPT ![self] = "main_complete"]
                          /\ UNCHANGED << taskState, joinWaiters, eventSet, 
                                          eventWaiters, waiterReceived, 
                                          setterCompleted >>

main_complete(self) == /\ pc[self] = "main_complete"
                       /\ running = self
                       /\ Assert(pendingCommand = NoCmd, 
                                 "Failure of assertion at line 177, column 9 of macro called at line 295, column 9.")
                       /\ Assert(running = self, 
                                 "Failure of assertion at line 178, column 9 of macro called at line 295, column 9.")
                       /\ Assert(taskState[self] = "Running", 
                                 "Failure of assertion at line 179, column 9 of macro called at line 295, column 9.")
                       /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                       /\ running' = NoTask
                       /\ pc' = [pc EXCEPT ![self] = "Done"]
                       /\ UNCHANGED << taskState, joinWaiters, eventSet, 
                                       eventWaiters, waiterReceived, 
                                       setterCompleted >>

Main(self) == main_spawn_waiter(self) \/ main_spawn_setter(self)
                 \/ main_join_waiter(self) \/ main_join_setter(self)
                 \/ main_complete(self)

waiter_wait(self) == /\ pc[self] = "waiter_wait"
                     /\ running = self
                     /\ Assert(pendingCommand = NoCmd, 
                               "Failure of assertion at line 161, column 9 of macro called at line 303, column 9.")
                     /\ Assert(running = self, 
                               "Failure of assertion at line 162, column 9 of macro called at line 303, column 9.")
                     /\ Assert(taskState[self] = "Running", 
                               "Failure of assertion at line 163, column 9 of macro called at line 303, column 9.")
                     /\ pendingCommand' = [cmd |-> "EventWait", task |-> self]
                     /\ running' = NoTask
                     /\ pc' = [pc EXCEPT ![self] = "waiter_received"]
                     /\ UNCHANGED << taskState, joinWaiters, eventSet, 
                                     eventWaiters, waiterReceived, 
                                     setterCompleted >>

waiter_received(self) == /\ pc[self] = "waiter_received"
                         /\ running = self
                         /\ waiterReceived' = TRUE
                         /\ pc' = [pc EXCEPT ![self] = "waiter_complete"]
                         /\ UNCHANGED << running, pendingCommand, taskState, 
                                         joinWaiters, eventSet, eventWaiters, 
                                         setterCompleted >>

waiter_complete(self) == /\ pc[self] = "waiter_complete"
                         /\ running = self
                         /\ Assert(pendingCommand = NoCmd, 
                                   "Failure of assertion at line 177, column 9 of macro called at line 311, column 9.")
                         /\ Assert(running = self, 
                                   "Failure of assertion at line 178, column 9 of macro called at line 311, column 9.")
                         /\ Assert(taskState[self] = "Running", 
                                   "Failure of assertion at line 179, column 9 of macro called at line 311, column 9.")
                         /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                         /\ running' = NoTask
                         /\ pc' = [pc EXCEPT ![self] = "Done"]
                         /\ UNCHANGED << taskState, joinWaiters, eventSet, 
                                         eventWaiters, waiterReceived, 
                                         setterCompleted >>

Waiter(self) == waiter_wait(self) \/ waiter_received(self)
                   \/ waiter_complete(self)

setter_set(self) == /\ pc[self] = "setter_set"
                    /\ running = self
                    /\ Assert(pendingCommand = NoCmd, 
                              "Failure of assertion at line 169, column 9 of macro called at line 319, column 9.")
                    /\ Assert(running = self, 
                              "Failure of assertion at line 170, column 9 of macro called at line 319, column 9.")
                    /\ Assert(taskState[self] = "Running", 
                              "Failure of assertion at line 171, column 9 of macro called at line 319, column 9.")
                    /\ pendingCommand' = [cmd |-> "EventSet", task |-> self]
                    /\ running' = NoTask
                    /\ pc' = [pc EXCEPT ![self] = "setter_completed"]
                    /\ UNCHANGED << taskState, joinWaiters, eventSet, 
                                    eventWaiters, waiterReceived, 
                                    setterCompleted >>

setter_completed(self) == /\ pc[self] = "setter_completed"
                          /\ running = self
                          /\ setterCompleted' = TRUE
                          /\ pc' = [pc EXCEPT ![self] = "setter_complete"]
                          /\ UNCHANGED << running, pendingCommand, taskState, 
                                          joinWaiters, eventSet, eventWaiters, 
                                          waiterReceived >>

setter_complete(self) == /\ pc[self] = "setter_complete"
                         /\ running = self
                         /\ Assert(pendingCommand = NoCmd, 
                                   "Failure of assertion at line 177, column 9 of macro called at line 327, column 9.")
                         /\ Assert(running = self, 
                                   "Failure of assertion at line 178, column 9 of macro called at line 327, column 9.")
                         /\ Assert(taskState[self] = "Running", 
                                   "Failure of assertion at line 179, column 9 of macro called at line 327, column 9.")
                         /\ pendingCommand' = [cmd |-> "Complete", task |-> self]
                         /\ running' = NoTask
                         /\ pc' = [pc EXCEPT ![self] = "Done"]
                         /\ UNCHANGED << taskState, joinWaiters, eventSet, 
                                         eventWaiters, waiterReceived, 
                                         setterCompleted >>

Setter(self) == setter_set(self) \/ setter_completed(self)
                   \/ setter_complete(self)

Next == Scheduler \/ EventLoopHandler
           \/ (\E self \in {0}: Main(self))
           \/ (\E self \in {1}: Waiter(self))
           \/ (\E self \in {2}: Setter(self))

Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(Scheduler)
        /\ WF_vars(EventLoopHandler)
        /\ \A self \in {0} : WF_vars(Main(self))
        /\ \A self \in {1} : WF_vars(Waiter(self))
        /\ \A self \in {2} : WF_vars(Setter(self))

\* END TRANSLATION

=============================================================================
