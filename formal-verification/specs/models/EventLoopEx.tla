------------------------ MODULE EventLoopEx ------------------------
EXTENDS Naturals

CONSTANT MaxTaskId
CONSTANT MaxQueueId
CONSTANT TestQueueSize

VARIABLES
    taskState,
    joinWaiters,
    queueItems,
    queueMaxSize,
    queueClosed,
    getWaiters,
    putWaiters

\* Define the operator to replace the constant
MyMaxQueueSize(q) == TestQueueSize

\* Instantiate EventLoop with our concrete operator
\* Note: MaxTaskId and MaxQueueId are passed by name automatically if they match
EL == INSTANCE EventLoop WITH MaxQueueSize <- MyMaxQueueSize

\* Expose the spec and properties we want to check
Spec == EL!SpecExt
TypeOKFull == EL!TypeOKFull
NoDeadlockExt == EL!NoDeadlockExt

\* Expose invariants for checking
AtMostOneRunning == EL!AtMostOneRunning
JoinWaitersConsistent == EL!JoinWaitersConsistent
NoZombieWaiters == EL!NoZombieWaiters
GetWaitersConsistent == EL!GetWaitersConsistent
PutWaitersConsistent == EL!PutWaitersConsistent
WaiterStateConsistent == EL!WaiterStateConsistent
NoZombieQueueWaiters == EL!NoZombieQueueWaiters
ClosedQueueNoWaiters == EL!ClosedQueueNoWaiters

=============================================================================
