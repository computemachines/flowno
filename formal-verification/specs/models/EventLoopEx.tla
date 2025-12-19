------------------------ MODULE EventLoopEx ------------------------
EXTENDS Naturals, Integers

CONSTANT MaxTaskId
CONSTANT MaxQueueId
CONSTANT TestQueueSize

VARIABLES
    taskState,
    joinWaiters,
    queueContents,
    queueMaxSize,
    queueClosed,
    getWaiters,
    putWaiters,
    pendingPut

\* Define constants for EventLoop
Value == {0, 1}
NoPut == -1

\* Instantiate EventLoop
EL == INSTANCE EventLoop WITH 
    Value <- Value,
    NoPut <- NoPut

\* Custom Init that sets queueMaxSize from TestQueueSize
Init ==
    /\ EL!Init
    /\ queueContents = [q \in EL!Queues |-> <<>>]
    /\ queueMaxSize = [q \in EL!Queues |-> TestQueueSize]
    /\ queueClosed = [q \in EL!Queues |-> FALSE]
    /\ getWaiters = [q \in EL!Queues |-> {}]
    /\ putWaiters = [q \in EL!Queues |-> {}]
    /\ pendingPut = [t \in EL!Tasks |-> NoPut]

\* Expose the spec with our custom Init
vars == <<taskState, joinWaiters, queueContents, queueMaxSize, queueClosed, getWaiters, putWaiters, pendingPut>>
Spec == Init /\ [][EL!NextExt]_vars
TypeOKFull == EL!TypeOKFull
NoDeadlockExt == EL!NoDeadlock

\* Expose invariants for checking
AtMostOneRunning == EL!AtMostOneRunning
JoinWaitersConsistent == EL!JoinWaitersConsistent
NoZombieWaiters == EL!NoZombieWaiters
GetWaitersConsistent == EL!GetWaitersConsistent
PutWaitersConsistent == EL!PutWaitersConsistent
WaiterStateConsistent == EL!WaiterStateConsistent
ClosedQueueNoWaiters == EL!ClosedQueueNoWaiters

=============================================================================
