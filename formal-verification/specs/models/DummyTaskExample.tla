---------------------------- MODULE DummyTaskExample ----------------------------
(*
 * Concrete model of the dummy_task example.
 * Instances EventLoop and adds program-specific pc tracking.
 *
 * Python code being modeled:
 *
 *   q = flowno.AsyncQueue()
 *
 *   async def dummy_task(_id: int):
 *       print(f"task id: {_id}")
 *       await q.put(f"hello from {_id}")
 *       x = 10
 *       recv = await q.get()
 *       print(f"task {_id} received: {recv}")
 *       await q.close()
 *
 *   async def main():
 *       tasks = []
 *       for n in range(2):
 *           tasks.append(flowno.spawn(dummy_task(n)))
 *       for task in tasks:
 *           await task.join()
 *)
EXTENDS Integers, Sequences, FiniteSets

CONSTANT MaxQueueDepth  \* Bound queue size for model checking

\* ===== TASK AND QUEUE IDENTIFIERS =====

MainTask == 0
Dummy1 == 1
Dummy2 == 2
DummyTasks == {Dummy1, Dummy2}
AllTasks == {MainTask} \cup DummyTasks

Q == 0  \* Single queue

\* ===== VALUES =====

Value == {1, 2} \* Task IDs are the values
NoPut == -1
NoRecv == -1

\* ===== INSTANTIATE EVENT LOOP =====

VARIABLES
    taskState,
    joinWaiters,
    queueContents,
    queueMaxSize,
    queueClosed,
    getWaiters,
    putWaiters,
    pendingPut

\* We need to override MaxQueueSize since EventLoop expects it as a parameter
TestMaxQueueSize(q) == MaxQueueDepth

EL == INSTANCE EventLoop WITH 
    MaxTaskId <- 2,
    MaxQueueId <- 0,
    MaxQueueSize <- TestMaxQueueSize,
    Value <- Value,
    NoPut <- NoPut,
    taskState <- taskState,
    joinWaiters <- joinWaiters,
    queueContents <- queueContents,
    queueMaxSize <- queueMaxSize,
    queueClosed <- queueClosed,
    getWaiters <- getWaiters,
    putWaiters <- putWaiters,
    pendingPut <- pendingPut

elVars == <<taskState, joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut>>
queueVars == <<queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut>>

\* ===== PROGRAM-SPECIFIC VARIABLES =====

VARIABLES
    pc,             \* [AllTasks -> PcValue] - program counter per task
    recv,           \* [DummyTasks -> Value \cup {NoRecv}] - received value per dummy task
    delivered,      \* [DummyTasks -> Value \cup {NoRecv}] - temp storage for direct-to-waiter transfer
    lastAction      \* Debugging helper

progVars == <<pc, recv, delivered, lastAction>>
vars == <<taskState, joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, pc, recv, delivered, lastAction>>

\* ===== PC VALUES =====

\* Main task pc values
MainPc == {"start", "spawned_1", "spawned_both", "joining_1", "joining_2", "done"}

\* Dummy task pc values  
DummyPc == {"not_spawned", "start", "putting", "after_put", "getting", "after_get", "closing", "done"}

\* ===== TYPE INVARIANT =====

TypeOK ==
    /\ EL!TypeOKFull
    /\ pc \in [AllTasks -> MainPc \cup DummyPc]
    /\ recv \in [DummyTasks -> Value \cup {NoRecv}]
    /\ delivered \in [DummyTasks -> Value \cup {NoRecv}]

\* ===== INITIAL STATE =====

Init ==
    \* EventLoop initial state (but main starts Ready, others Nonexistent)
    /\ taskState = [t \in EL!Tasks |->
        IF t = MainTask THEN [state |-> EL!Ready]
        ELSE [state |-> EL!Nonexistent]]
    /\ joinWaiters = [t \in EL!Tasks |-> {}]
    /\ queueContents = [q \in EL!Queues |-> <<>>]
    /\ queueMaxSize = [q \in EL!Queues |-> MaxQueueDepth]
    /\ queueClosed = [q \in EL!Queues |-> FALSE]
    /\ getWaiters = [q \in EL!Queues |-> {}]
    /\ putWaiters = [q \in EL!Queues |-> {}]
    /\ pendingPut = [t \in EL!Tasks |-> NoPut]
    \* Program state
    /\ pc = [t \in AllTasks |->
        IF t = MainTask THEN "start"
        ELSE "not_spawned"]
    /\ recv = [t \in DummyTasks |-> NoRecv]
    /\ delivered = [t \in DummyTasks |-> NoRecv]
    /\ lastAction = <<"Init">>

\* ===== SCHEDULING (bridges EventLoop to our actions) =====

\* Any ready task can be scheduled (unchanged from EventLoop)
Schedule(t) ==
    /\ EL!Schedule(t)
    /\ UNCHANGED queueVars
    /\ lastAction' = <<"Schedule", t>>
    /\ UNCHANGED <<pc, recv, delivered>>

\* ===== MAIN TASK ACTIONS =====

\* main: spawn dummy_task(1)
MainSpawn1 ==
    /\ pc[MainTask] = "start"
    /\ EL!IsRunning(MainTask)
    /\ EL!IsNonexistent(Dummy1)
    /\ taskState' = [taskState EXCEPT
        ![MainTask] = [state |-> EL!Ready],
        ![Dummy1] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT 
        ![MainTask] = "spawned_1",
        ![Dummy1] = "start"]
    /\ lastAction' = <<"MainSpawn1">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: spawn dummy_task(2)
MainSpawn2 ==
    /\ pc[MainTask] = "spawned_1"
    /\ EL!IsRunning(MainTask)
    /\ EL!IsNonexistent(Dummy2)
    /\ taskState' = [taskState EXCEPT
        ![MainTask] = [state |-> EL!Ready],
        ![Dummy2] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT
        ![MainTask] = "spawned_both",
        ![Dummy2] = "start"]
    /\ lastAction' = <<"MainSpawn2">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: await tasks[0].join() - task 1 not done yet
MainJoin1Wait ==
    /\ pc[MainTask] = "spawned_both"
    /\ EL!IsRunning(MainTask)
    /\ ~EL!IsTerminal(Dummy1)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Joining, target |-> Dummy1]]
    /\ joinWaiters' = [joinWaiters EXCEPT ![Dummy1] = @ \cup {MainTask}]
    /\ pc' = [pc EXCEPT ![MainTask] = "joining_1"]
    /\ lastAction' = <<"MainJoin1Wait">>
    /\ UNCHANGED <<queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: await tasks[0].join() - task 1 already done
MainJoin1Done ==
    /\ pc[MainTask] = "spawned_both"
    /\ EL!IsRunning(MainTask)
    /\ EL!IsTerminal(Dummy1)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT ![MainTask] = "joining_1"]
    /\ lastAction' = <<"MainJoin1Done">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: wakes from join on task 1, proceeds to join task 2
MainWakeFromJoin1 ==
    /\ pc[MainTask] = "joining_1"
    /\ EL!IsJoining(MainTask)
    /\ EL!JoinTarget(MainTask) = Dummy1
    /\ EL!IsTerminal(Dummy1)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Ready]]
    /\ joinWaiters' = [joinWaiters EXCEPT ![Dummy1] = @ \ {MainTask}]
    /\ lastAction' = <<"MainWakeFromJoin1">>
    /\ UNCHANGED <<queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, pc, recv, delivered>>

\* main: await tasks[1].join() - task 2 not done yet
MainJoin2Wait ==
    /\ pc[MainTask] = "joining_1"
    /\ EL!IsRunning(MainTask)
    /\ ~EL!IsTerminal(Dummy2)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Joining, target |-> Dummy2]]
    /\ joinWaiters' = [joinWaiters EXCEPT ![Dummy2] = @ \cup {MainTask}]
    /\ pc' = [pc EXCEPT ![MainTask] = "joining_2"]
    /\ lastAction' = <<"MainJoin2Wait">>
    /\ UNCHANGED <<queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: await tasks[1].join() - task 2 already done  
MainJoin2Done ==
    /\ pc[MainTask] = "joining_1"
    /\ EL!IsRunning(MainTask)
    /\ EL!IsTerminal(Dummy2)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT ![MainTask] = "joining_2"]
    /\ lastAction' = <<"MainJoin2Done">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: wakes from join on task 2
MainWakeFromJoin2 ==
    /\ pc[MainTask] = "joining_2"
    /\ EL!IsJoining(MainTask)
    /\ EL!JoinTarget(MainTask) = Dummy2
    /\ EL!IsTerminal(Dummy2)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Ready]]
    /\ joinWaiters' = [joinWaiters EXCEPT ![Dummy2] = @ \ {MainTask}]
    /\ lastAction' = <<"MainWakeFromJoin2">>
    /\ UNCHANGED <<queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, pc, recv, delivered>>

\* main: completes
MainComplete ==
    /\ pc[MainTask] = "joining_2"
    /\ EL!IsRunning(MainTask)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Done]]
    /\ pc' = [pc EXCEPT ![MainTask] = "done"]
    /\ lastAction' = <<"MainComplete">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* ===== DUMMY TASK ACTIONS =====

\* dummy: print then put - immediate (queue has space)
DummyPut(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "start"
    /\ EL!CanPutImmediate(t, Q)
    /\ IF EL!HasWaitingGetter(Q)
       THEN \E waiter \in getWaiters[Q] :
            /\ EL!PutDirectToWaiter(t, Q, t, waiter)  \* Message is task ID
            /\ delivered' = [delivered EXCEPT ![waiter] = t]
            /\ UNCHANGED recv
       ELSE
            /\ EL!PutIntoQueue(t, Q, t)
            /\ UNCHANGED <<recv, delivered>>
    /\ pc' = [pc EXCEPT ![t] = "after_put"]
    /\ lastAction' = <<"DummyPut", t>>

\* dummy: print then put - blocks (queue full)
DummyPutBlocks(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "start"
    /\ EL!YieldPutBlocks(t, Q, t)
    /\ pc' = [pc EXCEPT ![t] = "putting"]
    /\ lastAction' = <<"DummyPutBlocks", t>>
    /\ UNCHANGED <<recv, delivered>>

\* dummy: was blocked on put, now unblocked
DummyPutUnblocked(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "putting"
    /\ EL!IsReady(t)
    /\ pc' = [pc EXCEPT ![t] = "after_put"]
    /\ lastAction' = <<"DummyPutUnblocked", t>>
    /\ UNCHANGED <<taskState, joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* dummy: x=10 then get - immediate (queue has items)
DummyGet(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "after_put"
    /\ EL!CanGetImmediate(t, Q)
    /\ LET msg == EL!QueueHead(Q)  \* Capture BEFORE action modifies queue
       IN /\ recv' = [recv EXCEPT ![t] = msg]
          /\ EL!YieldGetImmediate(t, Q)
    /\ pc' = [pc EXCEPT ![t] = "after_get"]
    /\ lastAction' = <<"DummyGet", t>>
    /\ UNCHANGED delivered

\* dummy: x=10 then get - blocks (queue empty)
DummyGetBlocks(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "after_put"
    /\ EL!YieldGetBlocks(t, Q)
    /\ pc' = [pc EXCEPT ![t] = "getting"]
    /\ lastAction' = <<"DummyGetBlocks", t>>
    /\ UNCHANGED <<recv, delivered>>

\* dummy: was blocked on get, now running again (message delivered via PutDirectToWaiter)
DummyGetUnblocked(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "getting"
    /\ EL!IsReady(t)
    /\ delivered[t] # NoRecv
    /\ recv' = [recv EXCEPT ![t] = delivered[t]]
    /\ delivered' = [delivered EXCEPT ![t] = NoRecv]
    /\ pc' = [pc EXCEPT ![t] = "after_get"]
    /\ lastAction' = <<"DummyGetUnblocked", t>>
    /\ UNCHANGED <<taskState, joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut>>

\* dummy: print then close - queue still open
DummyCloseOpen(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "after_get"
    /\ EL!CloseQueue(t, Q)
    /\ pc' = [pc EXCEPT ![t] = "closing"]
    /\ lastAction' = <<"DummyCloseOpen", t>>
    /\ UNCHANGED <<recv, delivered>>

\* dummy: print then close - queue already closed
DummyCloseAlready(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "after_get"
    /\ EL!IsRunning(t)
    /\ ~EL!IsOpen(Q)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT ![t] = "closing"]
    /\ lastAction' = <<"DummyCloseAlready", t>>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* dummy: completes
DummyComplete(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "closing"
    /\ EL!Complete(t)
    /\ pc' = [pc EXCEPT ![t] = "done"]
    /\ lastAction' = <<"DummyComplete", t>>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* ===== NEXT STATE =====

Next ==
    \* Scheduling
    \/ \E t \in AllTasks : Schedule(t)
    \* Main task
    \/ MainSpawn1
    \/ MainSpawn2
    \/ MainJoin1Wait
    \/ MainJoin1Done
    \/ MainWakeFromJoin1
    \/ MainJoin2Wait
    \/ MainJoin2Done
    \/ MainWakeFromJoin2
    \/ MainComplete
    \* Dummy tasks
    \/ \E t \in DummyTasks : DummyPut(t)
    \/ \E t \in DummyTasks : DummyPutBlocks(t)
    \/ \E t \in DummyTasks : DummyPutUnblocked(t)
    \/ \E t \in DummyTasks : DummyGet(t)
    \/ \E t \in DummyTasks : DummyGetBlocks(t)
    \/ \E t \in DummyTasks : DummyGetUnblocked(t)
    \/ \E t \in DummyTasks : DummyCloseOpen(t)
    \/ \E t \in DummyTasks : DummyCloseAlready(t)
    \/ \E t \in DummyTasks : DummyComplete(t)

Spec == Init /\ [][Next]_vars

\* ===== INVARIANTS =====

\* The assertion you want violated: message matches sender ID
MessageMatchesId ==
    \A t \in DummyTasks :
        (pc[t] \in {"after_get", "closing", "done"} /\ recv[t] # NoRecv) 
        => recv[t] = t

\* Sanity: queue contents length matches item count (implicit in queueContents)
QueueConsistent ==
    Len(queueContents[Q]) <= MaxQueueDepth

=============================================================================
