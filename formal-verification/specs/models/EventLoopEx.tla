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

\* Define the operator to replace the constant
MyMaxQueueSize(q) == TestQueueSize

\* Instantiate EventLoop with our concrete operator
EL == INSTANCE EventLoop WITH 
    MaxQueueSize <- MyMaxQueueSize,
    Value <- Value,
    NoPut <- NoPut

\* Expose the spec and properties we want to check
Spec == EL!SpecExt
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
