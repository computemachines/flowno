------------------------ MODULE EventLoopBasic --------------------------
(*
 * PlusCal version of EventLoop - each task is a process.
 *
 * Key insight: PlusCal's pc (program counter) per process automatically
 * tracks task states. The task code looks like actual async Python!
 *)
EXTENDS Naturals, TLC

CONSTANT MaxTaskId

(* --algorithm EventLoop {
    variables
        \* Which task IDs have been spawned
        spawned = {0},
        \* Which tasks are sleeping (blocked on timer)
        sleeping = {},
        \* Which tasks finished (used for join)
        finished = {},
        \* Which tasks errored
        errored = {};

    \* Helper to check if any task is at a given label
    define {
        \* Task states are inferred from pc values:
        \* pc[t] = "taskBody" -> task is ready/running
        \* pc[t] = "waitWake" -> task is sleeping
        \* pc[t] = "waitJoin" -> task is joining
        \* pc[t] = "Done" -> task finished

        IsNonexistent(t) == t \notin spawned
        IsAlive(t) == t \in spawned /\ pc[t] # "Done"
        IsTerminal(t) == t \in finished \/ t \in errored
    }

    \* Each task is a PlusCal process - they run cooperatively
    fair process (Task \in 0..MaxTaskId)
    {
        waitSpawn:
            \* All tasks except root (0) wait to be spawned
            if (self # 0) {
                await self \in spawned;
            };

        taskBody:
            \* Task executes - makes a choice of what to do
            while (TRUE) {
                either {
                    \* YIELD - just give up control and continue
                    yield: skip;
                }
                or {
                    \* SLEEP - block on timer
                    goSleep:
                        sleeping := sleeping \cup {self};
                    waitWake:
                        await self \notin sleeping;  \* Woken by timer
                }
                or {
                    \* JOIN - wait for another task to finish
                    waitJoin:
                        with (target \in (spawned \ {self})) {
                            await target \in finished \/ target \in errored;
                        }
                }
                or {
                    \* SPAWN - create a new task
                    spawn:
                        with (newTask \in {t \in 0..MaxTaskId : t \notin spawned}) {
                            spawned := spawned \cup {newTask};
                        }
                }
                or {
                    \* COMPLETE - finish successfully
                    complete:
                        finished := finished \cup {self};
                        goto taskDone;
                }
                or {
                    \* ERROR - finish with error
                    fail:
                        errored := errored \cup {self};
                        goto taskDone;
                }
            };

        taskDone:
            skip;  \* Process ends (pc[self] becomes "Done")
    }

    \* Separate process to wake sleeping tasks (models timer events)
    fair process (WakeTimer = MaxTaskId + 1)
    {
        timerLoop:
            while (TRUE) {
                \* Non-deterministically wake any sleeping task
                wake:
                    with (t \in sleeping) {
                        sleeping := sleeping \ {t};
                    }
            }
    }
} *)
\* BEGIN TRANSLATION (chksum(pcal) = "a194b721" /\ chksum(tla) = "6d6146d4")
VARIABLES spawned, sleeping, finished, errored, pc

(* define statement *)
IsNonexistent(t) == t \notin spawned
IsAlive(t) == t \in spawned /\ pc[t] # "Done"
IsTerminal(t) == t \in finished \/ t \in errored


vars == << spawned, sleeping, finished, errored, pc >>

ProcSet == (0..MaxTaskId) \cup {MaxTaskId + 1}

Init == (* Global variables *)
        /\ spawned = {0}
        /\ sleeping = {}
        /\ finished = {}
        /\ errored = {}
        /\ pc = [self \in ProcSet |-> CASE self \in 0..MaxTaskId -> "waitSpawn"
                                        [] self = MaxTaskId + 1 -> "timerLoop"]

waitSpawn(self) == /\ pc[self] = "waitSpawn"
                   /\ IF self # 0
                         THEN /\ self \in spawned
                         ELSE /\ TRUE
                   /\ pc' = [pc EXCEPT ![self] = "taskBody"]
                   /\ UNCHANGED << spawned, sleeping, finished, errored >>

taskBody(self) == /\ pc[self] = "taskBody"
                  /\ \/ /\ pc' = [pc EXCEPT ![self] = "yield"]
                     \/ /\ pc' = [pc EXCEPT ![self] = "goSleep"]
                     \/ /\ pc' = [pc EXCEPT ![self] = "waitJoin"]
                     \/ /\ pc' = [pc EXCEPT ![self] = "spawn"]
                     \/ /\ pc' = [pc EXCEPT ![self] = "complete"]
                     \/ /\ pc' = [pc EXCEPT ![self] = "fail"]
                  /\ UNCHANGED << spawned, sleeping, finished, errored >>

yield(self) == /\ pc[self] = "yield"
               /\ TRUE
               /\ pc' = [pc EXCEPT ![self] = "taskBody"]
               /\ UNCHANGED << spawned, sleeping, finished, errored >>

goSleep(self) == /\ pc[self] = "goSleep"
                 /\ sleeping' = (sleeping \cup {self})
                 /\ pc' = [pc EXCEPT ![self] = "waitWake"]
                 /\ UNCHANGED << spawned, finished, errored >>

waitWake(self) == /\ pc[self] = "waitWake"
                  /\ self \notin sleeping
                  /\ pc' = [pc EXCEPT ![self] = "taskBody"]
                  /\ UNCHANGED << spawned, sleeping, finished, errored >>

waitJoin(self) == /\ pc[self] = "waitJoin"
                  /\ \E target \in (spawned \ {self}):
                       target \in finished \/ target \in errored
                  /\ pc' = [pc EXCEPT ![self] = "taskBody"]
                  /\ UNCHANGED << spawned, sleeping, finished, errored >>

spawn(self) == /\ pc[self] = "spawn"
               /\ \E newTask \in {t \in 0..MaxTaskId : t \notin spawned}:
                    spawned' = (spawned \cup {newTask})
               /\ pc' = [pc EXCEPT ![self] = "taskBody"]
               /\ UNCHANGED << sleeping, finished, errored >>

complete(self) == /\ pc[self] = "complete"
                  /\ finished' = (finished \cup {self})
                  /\ pc' = [pc EXCEPT ![self] = "taskDone"]
                  /\ UNCHANGED << spawned, sleeping, errored >>

fail(self) == /\ pc[self] = "fail"
              /\ errored' = (errored \cup {self})
              /\ pc' = [pc EXCEPT ![self] = "taskDone"]
              /\ UNCHANGED << spawned, sleeping, finished >>

taskDone(self) == /\ pc[self] = "taskDone"
                  /\ TRUE
                  /\ pc' = [pc EXCEPT ![self] = "Done"]
                  /\ UNCHANGED << spawned, sleeping, finished, errored >>

Task(self) == waitSpawn(self) \/ taskBody(self) \/ yield(self)
                 \/ goSleep(self) \/ waitWake(self) \/ waitJoin(self)
                 \/ spawn(self) \/ complete(self) \/ fail(self)
                 \/ taskDone(self)

timerLoop == /\ pc[MaxTaskId + 1] = "timerLoop"
             /\ pc' = [pc EXCEPT ![MaxTaskId + 1] = "wake"]
             /\ UNCHANGED << spawned, sleeping, finished, errored >>

wake == /\ pc[MaxTaskId + 1] = "wake"
        /\ \E t \in sleeping:
             sleeping' = sleeping \ {t}
        /\ pc' = [pc EXCEPT ![MaxTaskId + 1] = "timerLoop"]
        /\ UNCHANGED << spawned, finished, errored >>

WakeTimer == timerLoop \/ wake

Next == WakeTimer
           \/ (\E self \in 0..MaxTaskId: Task(self))

Spec == /\ Init /\ [][Next]_vars
        /\ \A self \in 0..MaxTaskId : WF_vars(Task(self))
        /\ WF_vars(WakeTimer)

\* END TRANSLATION 

=============================================================================
