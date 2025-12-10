-------------------------- MODULE EventLoopBasic --------------------------
(*
 * Formal model of Flowno's EventLoop.
 * 
 * This spec models the core event loop without extra constraints.
 * It will be extended with program-specific constraints for dataflow logic.
 * 
 * Design decisions:
 * - Task IDs are natural numbers 0..MaxTaskId
 * - Ready tasks are a SET (not queue) - TLA+ explores all interleavings
 * - "Running" state represents when event loop is blocked in task.send()
 * - At most ONE task can be Running at a time (single-threaded event loop)
 * - Designed for future extension to multi-event-loop scenarios
 * 
 * Maps to Python EventLoop:
 *   ready      ≈ tasks deque (as set - order doesn't affect deadlock)
 *   sleeping   ≈ sleeping heap (abstracted - just a set of blocked tasks)  
 *   joining    ≈ watching_task (task → set of waiters)
 *   finished   ≈ finished dict (task completed successfully)
 *   error      ≈ exceptions dict (task completed with error)
 *   running    ≈ the task currently in task.send() - NEW for multi-EL
 *)
EXTENDS Naturals, FiniteSets

CONSTANT MaxTaskId    \* Bounds state space: tasks are 0..MaxTaskId

(* ===== TASK STATES ===== *)
(*
 * A task can be in exactly one state:
 *   - nonexistent: Task ID not yet spawned
 *   - ready: In ready queue, waiting to be scheduled
 *   - running: Currently executing (event loop blocked in send())
 *   - sleeping: Yielded SleepCommand, waiting for timer
 *   - joining[t]: Yielded JoinCommand, waiting for task t to complete
 *   - done: Completed successfully
 *   - error: Completed with exception
 *)

Tasks == 0..MaxTaskId

(* ===== VARIABLES ===== *)

VARIABLES
    taskState,    \* Task ID -> state record
    joinWaiters   \* Task ID -> set of tasks waiting to join this one

vars == <<taskState, joinWaiters>>

(* ===== STATE PREDICATES ===== *)

\* State type tags
Nonexistent == "nonexistent"
Ready       == "ready"
Running     == "running"  
Sleeping    == "sleeping"
Joining     == "joining"
Done        == "done"
Error       == "error"

\* Check if task is in a particular state
IsNonexistent(t) == taskState[t].state = Nonexistent
IsReady(t)       == taskState[t].state = Ready
IsRunning(t)     == taskState[t].state = Running
IsSleeping(t)    == taskState[t].state = Sleeping
IsJoining(t)     == taskState[t].state = Joining
IsDone(t)        == taskState[t].state = Done
IsError(t)       == taskState[t].state = Error

\* Task exists (has been spawned)
Exists(t) == ~IsNonexistent(t)

\* Task is "alive" - not yet terminal
IsAlive(t) == Exists(t) /\ taskState[t].state \notin {Done, Error}

\* Task is blocked (not ready to run, but not terminal)
IsBlocked(t) == taskState[t].state \in {Sleeping, Joining}

\* Task is terminal (done or error)
IsTerminal(t) == taskState[t].state \in {Done, Error}

\* Get the task being joined (only valid if IsJoining)
JoinTarget(t) == taskState[t].target

(* ===== TYPE INVARIANT ===== *)

TypeOK ==
    /\ taskState \in [Tasks -> 
        [state: {Nonexistent}] \cup
        [state: {Ready}] \cup
        [state: {Running}] \cup
        [state: {Sleeping}] \cup
        [state: {Joining}, target: Tasks] \cup
        [state: {Done}] \cup
        [state: {Error}]]
    /\ joinWaiters \in [Tasks -> SUBSET Tasks]

(* ===== INITIAL STATE ===== *)

Init ==
    /\ taskState = [t \in Tasks |-> 
        IF t = 0 
        THEN [state |-> Ready]  \* Task 0 is the root task, starts ready
        ELSE [state |-> Nonexistent]]
    /\ joinWaiters = [t \in Tasks |-> {}]

(* ===== ACTIONS ===== *)

(*
 * Schedule: A ready task begins executing.
 *
 * Python: event loop pops from task queue and calls task.send()
 *
 * Some task t that is ready, and no other task is running,
 * becomes the single running task.
 *)
Schedule(t) ==
    /\ IsReady(t)
    /\ \A t2 \in Tasks : ~IsRunning(t2)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Running]]
    /\ UNCHANGED joinWaiters

(*
 * YieldReady: A running task pauses but stays schedulable.
 *
 * Python: task yields None or an immediate command.
 *
 * The running task t becomes ready again, allowing other tasks a turn.
 *)
YieldReady(t) ==
    /\ IsRunning(t)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Ready]]
    /\ UNCHANGED joinWaiters

(*
 * YieldSleep: A running task requests to sleep.
 *
 * Python: task yields SleepCommand, enters sleeping heap.
 *
 * The running task t becomes sleeping. It will eventually wake
 * (modeled by WakeFromSleep) when its timer expires.
 *)
YieldSleep(t) ==
    /\ IsRunning(t)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Sleeping]]
    /\ UNCHANGED joinWaiters

(*
 * WakeFromSleep: A sleeping task's timer expires.
 *
 * Python: event loop checks sleeping heap, moves task to ready queue.
 *
 * Some sleeping task t becomes ready. We don't model actual time,
 * so any sleeping task can wake at any moment.
 *)
WakeFromSleep(t) ==
    /\ IsSleeping(t)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Ready]]
    /\ UNCHANGED joinWaiters

(*
 * YieldJoin: A running task waits for another task to finish.
 *
 * Python: task yields JoinCommand(target), enters watching_task.
 *
 * The running task t wants to wait for some other existing, non-finished
 * task called target. Task t' becomes joining-on-target, and t' is recorded
 * as waiting on target (so target's completion can wake it).
 *)
YieldJoin(t, target) ==
    /\ IsRunning(t)
    /\ t # target
    /\ Exists(target)
    /\ ~IsTerminal(target)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Joining, target |-> target]]
    /\ joinWaiters' = [joinWaiters EXCEPT ![target] = @ \cup {t}]

(*
 * JoinComplete: A waiting task resumes because its target finished.
 *
 * Python: target completes, watchers moved to ready queue.
 *
 * Some task t that is joining-on-target, where target is now done or errored,
 * becomes ready. Task t' is no longer waiting on target.
 *)
JoinComplete(t, target) ==
    /\ IsJoining(t)
    /\ JoinTarget(t) = target
    /\ IsTerminal(target)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Ready]]
    /\ joinWaiters' = [joinWaiters EXCEPT ![target] = @ \ {t}]

(*
 * JoinAlreadyDone: A running task joins a task that already finished.
 *
 * Python: JoinCommand when target already in finished/exceptions dict.
 *
 * The running task t tries to join some already-finished target.
 * Since target is done, t' immediately becomes ready (with the result).
 * No waiting relationship is created.
 *)
JoinAlreadyDone(t, target) ==
    /\ IsRunning(t)
    /\ t # target
    /\ IsTerminal(target)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Ready]]
    /\ UNCHANGED joinWaiters

(*
 * Spawn: A running task creates a new task.
 *
 * Python: task yields SpawnCommand, new task enters ready queue.
 *
 * The running task t spawns a fresh task (one that doesn't exist yet).
 * Both t' and newTask' become ready - the spawner continues with a
 * handle to the new task, and the new task is schedulable.
 *)
Spawn(t, newTask) ==
    /\ IsRunning(t)
    /\ IsNonexistent(newTask)
    /\ newTask # t
    /\ taskState' = [taskState EXCEPT 
        ![t] = [state |-> Ready],
        ![newTask] = [state |-> Ready]]
    /\ UNCHANGED joinWaiters

(*
 * Complete: A running task finishes successfully.
 *
 * Python: task.send() raises StopIteration.
 *
 * The running task t has no more work to do. Task t' is done.
 * Any tasks waiting to join t will wake up via JoinComplete.
 *)
Complete(t) ==
    /\ IsRunning(t)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Done]]
    /\ UNCHANGED joinWaiters

(*
 * Fail: A running task raises an exception.
 *
 * Python: task.send() raises an exception (not StopIteration).
 *
 * The running task t encountered an error. Task t' is in error state.
 * Any tasks waiting to join t will wake up via JoinComplete and
 * receive the exception.
 *)
Fail(t) ==
    /\ IsRunning(t)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Error]]
    /\ UNCHANGED joinWaiters

(* ===== NEXT STATE RELATION ===== *)

Next ==
    \/ \E t \in Tasks : Schedule(t)
    \/ \E t \in Tasks : YieldReady(t)
    \/ \E t \in Tasks : YieldSleep(t)
    \/ \E t \in Tasks : WakeFromSleep(t)
    \/ \E t \in Tasks : Complete(t)
    \/ \E t \in Tasks : Fail(t)
    \/ \E t, target \in Tasks : YieldJoin(t, target)
    \/ \E t, target \in Tasks : JoinComplete(t, target)
    \/ \E t, target \in Tasks : JoinAlreadyDone(t, target)
    \/ \E t, newTask \in Tasks : Spawn(t, newTask)

Spec == Init /\ [][Next]_vars

(* ===== SAFETY PROPERTIES ===== *)

(*
 * AtMostOneRunning: At most one task can be running at a time.
 * This models single-threaded execution within one event loop.
 *)
AtMostOneRunning ==
    Cardinality({t \in Tasks : IsRunning(t)}) <= 1

(*
 * NoDeadlock: If any task is alive, progress is possible.
 * 
 * A deadlock occurs when:
 *   - At least one task exists and is alive (not done/error)
 *   - No action can fire (no progress possible)
 * 
 * Progress IS possible if:
 *   - Some task is ready (can be scheduled)
 *   - Some task is running (can yield/complete/fail)
 *   - Some task is sleeping (can wake)
 *   - Some task is joining AND its target is terminal (JoinComplete can fire)
 *)
CanMakeProgress ==
    \/ \E t \in Tasks : IsReady(t)
    \/ \E t \in Tasks : IsRunning(t)
    \/ \E t \in Tasks : IsSleeping(t)
    \/ \E t \in Tasks : IsJoining(t) /\ IsTerminal(JoinTarget(t))

NoDeadlock ==
    LET aliveTasks == {t \in Tasks : IsAlive(t)}
    IN aliveTasks # {} => CanMakeProgress

(*
 * JoinWaitersConsistent: If t is waiting to join target, t should be 
 * in target's joinWaiters set.
 *)
JoinWaitersConsistent ==
    \A t \in Tasks :
        IsJoining(t) => t \in joinWaiters[JoinTarget(t)]

(*
 * NoZombieWaiters: No task should be in joinWaiters if it's not actually
 * in the Joining state.
 *)
NoZombieWaiters ==
    \A target \in Tasks : \A t \in joinWaiters[target] :
        IsJoining(t) /\ JoinTarget(t) = target

==========================================================================
