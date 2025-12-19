------------------------ MODULE DummyTaskExampleFail ------------------------
(*
 * Concrete model of the dummy_task example.
 * Instances EventLoop and adds program-specific pc tracking.
 *
 * Python code being modeled:
 *
 *   q = flowno.AsyncQueue()
 *
 *   async def dummy_task(_id: int):
 *       # pc: D1 (await put)
 *       print(f"task id: {_id}")
 *       await q.put(f"hello from {_id}")
 *       # pc: D2 (await get)
 *       x = 10
 *       recv = await q.get()
 *       # pc: D3 (done)
 *       print(f"task {_id} received: {recv}")
 *
 *   async def main():
 *       # pc: M1 (await spawn1)
 *       tasks = []
 *       tasks[0] = await flowno.spawn(dummy_task(0))
 *       # pc: M2 (await spawn2)
 *       tasks[1] = await flowno.spawn(dummy_task(1))
 *       # pc: M3 (await join1)
 *       await tasks[0].join()
 *       # pc: M4 (await join2)
 *       await tasks[1].join()
 *       # pc: M5 (await queue close)
 *       await q.close()
 *       # pc: M6 (done)
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

EL == INSTANCE EventLoop WITH 
    MaxTaskId <- 2,
    MaxQueueId <- 0,
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
MainPc == {"M1", "M2", "M3", "M4", "M5", "M6"}

\* Dummy task pc values  
DummyPc == {"D0", "D1", "D2", "D3"}

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
        IF t = MainTask THEN "M1"
        ELSE "D0"]
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
    /\ pc[MainTask] = "M1"
    /\ EL!IsRunning(MainTask)
    /\ EL!IsNonexistent(Dummy1)
    /\ taskState' = [taskState EXCEPT
        ![MainTask] = [state |-> EL!Ready],
        ![Dummy1] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT 
        ![MainTask] = "M2",  \* Next: spawn2
        ![Dummy1] = "D1"]
    /\ lastAction' = <<"MainSpawn1">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: spawn dummy_task(2)
MainSpawn2 ==
    /\ pc[MainTask] = "M2"
    /\ EL!IsRunning(MainTask)
    /\ EL!IsNonexistent(Dummy2)
    /\ taskState' = [taskState EXCEPT
        ![MainTask] = [state |-> EL!Ready],
        ![Dummy2] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT
        ![MainTask] = "M3",
        ![Dummy2] = "D1"]
    /\ lastAction' = <<"MainSpawn2">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: await tasks[0].join() - task 1 not done yet (block)
MainJoin1Block ==
    /\ pc[MainTask] = "M3"
    /\ EL!IsRunning(MainTask)
    /\ ~EL!IsTerminal(Dummy1)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Joining, target |-> Dummy1]]
    /\ joinWaiters' = [joinWaiters EXCEPT ![Dummy1] = @ \cup {MainTask}]
    /\ lastAction' = <<"MainJoin1Block">>
    /\ UNCHANGED <<queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered, pc>>

\* main: await tasks[0].join() - task 1 already done (immediate)
MainJoin1Immediate ==
    /\ pc[MainTask] = "M3"
    /\ EL!IsRunning(MainTask)
    /\ EL!IsTerminal(Dummy1)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT ![MainTask] = "M4"]
    /\ lastAction' = <<"MainJoin1Immediate">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: wakes from join on task 1, proceeds to join task 2 (resume)
MainJoin1Resume ==
    /\ pc[MainTask] = "M3"
    /\ EL!IsJoining(MainTask)
    /\ EL!JoinTarget(MainTask) = Dummy1
    /\ EL!IsTerminal(Dummy1)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Ready]]
    /\ joinWaiters' = [joinWaiters EXCEPT ![Dummy1] = @ \ {MainTask}]
    /\ pc' = [pc EXCEPT ![MainTask] = "M4"]
    /\ lastAction' = <<"MainJoin1Resume">>
    /\ UNCHANGED <<queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: close queue - queue still open
MainCloseOpen ==
    /\ pc[MainTask] = "M5"
    /\ EL!IsRunning(MainTask)
    /\ EL!CloseQueue(MainTask, Q)
    /\ pc' = [pc EXCEPT ![MainTask] = "M6"]
    /\ lastAction' = <<"MainCloseOpen">>
    /\ UNCHANGED <<joinWaiters, recv, delivered, pendingPut>>

\* main: close queue - queue already closed
MainCloseAlready ==
    /\ pc[MainTask] = "M5"
    /\ EL!IsRunning(MainTask)
    /\ ~EL!IsOpen(Q)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT ![MainTask] = "M6"]
    /\ lastAction' = <<"MainCloseAlready">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: await tasks[1].join() - task 2 not done yet (block)
MainJoin2Block ==
    /\ pc[MainTask] = "M4"
    /\ EL!IsRunning(MainTask)
    /\ ~EL!IsTerminal(Dummy2)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Joining, target |-> Dummy2]]
    /\ joinWaiters' = [joinWaiters EXCEPT ![Dummy2] = @ \cup {MainTask}]
    /\ lastAction' = <<"MainJoin2Block">>
    /\ UNCHANGED <<queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered, pc>>

\* main: await tasks[1].join() - task 2 already done (immediate)
MainJoin2Immediate ==
    /\ pc[MainTask] = "M4"
    /\ EL!IsRunning(MainTask)
    /\ EL!IsTerminal(Dummy2)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT ![MainTask] = "M5"]
    /\ lastAction' = <<"MainJoin2Immediate">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: wakes from join on task 2
MainJoin2Resume ==
    /\ pc[MainTask] = "M4"
    /\ EL!IsJoining(MainTask)
    /\ EL!JoinTarget(MainTask) = Dummy2
    /\ EL!IsTerminal(Dummy2)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Ready]]
    /\ joinWaiters' = [joinWaiters EXCEPT ![Dummy2] = @ \ {MainTask}]
    /\ pc' = [pc EXCEPT ![MainTask] = "M5"]
    /\ lastAction' = <<"MainJoin2Resume">>
    /\ UNCHANGED <<queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* main: completes
MainComplete ==
    /\ pc[MainTask] = "M6"
    /\ EL!IsRunning(MainTask)
    /\ taskState' = [taskState EXCEPT ![MainTask] = [state |-> EL!Done]]
    /\ lastAction' = <<"MainComplete">>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered, pc>>

\* ===== DUMMY TASK ACTIONS =====

\* dummy: print then put - immediate (queue has space or waiter)
DummyPutImmediate(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "D1"
    /\ EL!IsRunning(t)
    /\ EL!CanPutImmediate(t, Q)
    /\ IF EL!HasWaitingGetter(Q)
       THEN \E waiter \in getWaiters[Q] :
            /\ EL!PutDirectToWaiter(t, Q, t, waiter)  \* Message is task ID
            /\ delivered' = [delivered EXCEPT ![waiter] = t]
            /\ UNCHANGED recv
       ELSE
            /\ EL!PutIntoQueue(t, Q, t)
            /\ UNCHANGED <<recv, delivered>>
    /\ pc' = [pc EXCEPT ![t] = "D2"]
    /\ lastAction' = <<"DummyPutImmediate", t>>

\* dummy: print then put - blocks (queue full)
DummyPutBlock(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "D1"
    /\ EL!IsRunning(t)
    /\ EL!YieldPutBlocks(t, Q, t)
    /\ lastAction' = <<"DummyPutBlock", t>>
    /\ UNCHANGED <<recv, delivered, pc>>

\* dummy: was blocked on put, now unblocked
\* This fires when task was blocked on put and is now in ReadyResuming state.
\* The value was already consumed into the queue by GetFromQueueWakePutter.
DummyPutResume(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "D1"
    /\ EL!IsReadyResuming(t)  \* Just unblocked from put (not fresh spawn)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT ![t] = "D2"]
    /\ lastAction' = <<"DummyPutResume", t>>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered>>

\* dummy: x=10 then get - immediate (queue has items)
DummyGetImmediate(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "D2"
    /\ EL!IsRunning(t)
    /\ EL!CanGetImmediate(t, Q)
    /\ LET msg == EL!QueueHead(Q)  \* Capture BEFORE action modifies queue
       IN /\ recv' = [recv EXCEPT ![t] = msg]
          /\ EL!YieldGetImmediate(t, Q)
    /\ pc' = [pc EXCEPT ![t] = "D3"]
    /\ lastAction' = <<"DummyGetImmediate", t>>
    /\ UNCHANGED delivered

\* dummy: x=10 then get - blocks (queue empty)
DummyGetBlock(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "D2"
    /\ EL!IsRunning(t)
    /\ EL!YieldGetBlocks(t, Q)
    /\ lastAction' = <<"DummyGetBlock", t>>
    /\ UNCHANGED <<recv, delivered, pc>>

\* dummy: was blocked on get, now unblocked (message delivered via PutDirectToWaiter)
DummyGetResume(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "D2"
    /\ EL!IsReadyResuming(t)  \* Just unblocked from get (not fresh spawn)
    /\ delivered[t] # NoRecv
    /\ recv' = [recv EXCEPT ![t] = delivered[t]]
    /\ delivered' = [delivered EXCEPT ![t] = NoRecv]
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT ![t] = "D3"]
    /\ lastAction' = <<"DummyGetResume", t>>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut>>

\* dummy: completes
DummyComplete(t) ==
    /\ t \in DummyTasks
    /\ pc[t] = "D3"
    /\ EL!IsRunning(t)
    /\ EL!Complete(t)
    /\ lastAction' = <<"DummyComplete", t>>
    /\ UNCHANGED <<joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut, recv, delivered, pc>>

\* ===== NEXT STATE =====

Next ==
    \* Scheduling
    \/ \E t \in AllTasks : Schedule(t)
    \* Main task
    \/ MainSpawn1
    \/ MainSpawn2
    \/ MainJoin1Immediate
    \/ MainJoin1Block
    \/ MainJoin1Resume
    \/ MainJoin2Immediate
    \/ MainJoin2Block
    \/ MainJoin2Resume
    \/ MainCloseOpen
    \/ MainCloseAlready
    \/ MainComplete
    \* Dummy tasks
    \/ \E t \in DummyTasks : DummyPutImmediate(t)
    \/ \E t \in DummyTasks : DummyPutBlock(t)
    \/ \E t \in DummyTasks : DummyPutResume(t)
    \/ \E t \in DummyTasks : DummyGetImmediate(t)
    \/ \E t \in DummyTasks : DummyGetBlock(t)
    \/ \E t \in DummyTasks : DummyGetResume(t)
    \/ \E t \in DummyTasks : DummyComplete(t)

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

\* ===== INVARIANTS =====

\* The assertion you want violated: message matches sender ID
MessageMatchesId ==
    \A t \in DummyTasks :
        (pc[t] \in {"D2", "D3"} /\ recv[t] # NoRecv) 
        => recv[t] = t

\* Sanity: queue contents length matches item count (implicit in queueContents)
QueueConsistent ==
    Len(queueContents[Q]) <= MaxQueueDepth

\* ===== LIVENESS PROPERTIES =====

\* Eventually all tasks complete (this should fail if Dummy2 gets stuck)
EventuallyComplete ==
    /\ <>(pc[MainTask] = "M6" /\ EL!IsTerminal(MainTask))
    /\ <>(pc[Dummy1] = "D3" /\ EL!IsTerminal(Dummy1))
    /\ <>(pc[Dummy2] = "D3" /\ EL!IsTerminal(Dummy2))

=============================================================================
