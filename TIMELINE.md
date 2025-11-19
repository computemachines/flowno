# Event Timeline - The Bug Sequence

## Initial State
- Source: Not started, generation = None
- Consumer1: Not started, generation = None
- Consumer2: Not started, generation = None

---

## T1: Source Starts (First Iteration of while True)
```
evaluate_node(Source) while loop iteration #1
  → _wait_for_start_next_generation(Source, 0)
  → yields WaitForStartNextGenerationCommand
  → Status: Ready
  → Generator SUSPENDS
```

## T2: Solver Resumes Source
```
Resolution queue gets Source
Solver: _find_node_solution(Source) → [Source]
  → _resume_node(Source)
  → yields ResumeNodeCommand(Source)
  → Status: Running
  → Generator RESUMES from yield
```

## T3: Source Executes
```
gather_inputs() → no inputs for Source
node.call() → creates new async generator
_handle_async_generator_node(generator):

  Inner loop iteration #1:
    result = await anext(generator) → "alpha"
    push_data(result, 1) → Source.generation = (0, 0)
    enqueue outputs → [Consumer1, Consumer2] to queue
    _wait_for_start_next_generation(Source, 1)
      → yields WaitForStartNextGenerationCommand
      → Status: Ready
      → Inner generator SUSPENDS
```

## T4: Solver Resumes Source for Next Chunk
```
Resolution queue: [Consumer1, Consumer2]
Solver processes Consumer1:
  - Consumer1 has stale input (Source at (0,0), Consumer1 at None)
  - _find_node_solution(Consumer1) → [Source]
  - _resume_node(Source)
  - Status: Running
  - Inner generator RESUMES
```

## T5: Source Tries Next Chunk
```
Inner loop iteration #2:
  result = await anext(generator) → raises StopAsyncIteration
  → exits inner loop
  → pushes run level 0 data: Source.generation = (0,)
  → exits _handle_async_generator_node
```

## T6: Source's Finally Block
```
finally:
  _enqueue_output_nodes(Source)  ← PROBLEM?
    → enqueues [Consumer1, Consumer2] AGAIN
```

## T7: Source's While Loop Continues
```
  → reaches end of try/finally
  → loops back to while True at line 591
  → _wait_for_start_next_generation(Source, 0)
  → yields WaitForStartNextGenerationCommand
  → Status: Ready
  → Outer generator SUSPENDS
```

## T8: Consumer1 Executes
```
Resolution queue: [Consumer1, Consumer2]
Solver processes Consumer1:
  - _find_node_solution(Consumer1) → [Consumer1]
  - _resume_node(Consumer1)
  - Consumer1 runs to completion
  - Consumer1.generation = (0,)
  - Consumer1 enqueues [] (no outputs)
  - Consumer1 loops back, waits for next generation
```

## T9: Consumer2 Gets Processed
```
Resolution queue: [Consumer2]
Solver processes Consumer2:
  - Consumer2 needs Source at higher generation?
  - OR Consumer2 just runs?
  - Consumer2 reads first chunk, waits for second chunk
  - Consumer2 becomes Stalled
```

## T10: THE BUG - Source Resumes AGAIN
```
Solver processes Consumer1 or Consumer2 from queue (they were re-enqueued)
Finds stale inputs from Source
  → _resume_node(Source)  ← WHY IS THIS VALID?
  → Status: Running
  → Source's outer generator RESUMES from line 592
```

## T11: Source Second Execution (WRONG!)
```
evaluate_node(Source) while loop iteration #2
  gather_inputs() → creates FRESH Stream objects (empty)
  node.call() → creates FRESH async generator (starts over!)
  _handle_async_generator_node(NEW generator):
    result = await anext(generator) → "alpha" AGAIN!
```

---

# The Questions This Raises

## Question 1: Why does line 619's enqueue happen?
The finally block runs when:
- Coroutine completes normally
- Generator raises StopAsyncIteration
- Exception occurs

Should outputs be enqueued in ALL these cases?

## Question 2: What makes iteration #2 start?
The while True loop continues. Line 592 suspends.
Who resumes it? Solver, because Consumer1 or Consumer2 was in the queue.

**Should Consumer1/Consumer2 even BE in the queue at T10?**
They were already processed at T8/T9!

## Question 3: What is the loop exit condition?
The while True at line 591 has no break statement.
The only way out is if an exception propagates up.

**For a mononode that finishes: should it exit the loop? How?**

## Question 4: Double enqueue of consumers
Consumers get enqueued:
- T3: After Source yields chunk "alpha"
- T6: After Source finishes (StopAsyncIteration)

**Should T6's enqueue happen if outputs were already enqueued in T3?**

---

# Pattern Recognition Exercise

Which of these feels most "wrong"?

A) The finally block always enqueuing, even when outputs already enqueued
B) The while loop having no exit condition except exceptions
C) The solver deciding to resume a finished node
D) gather_inputs() creating fresh Streams on iteration #2
E) node.call() creating a fresh generator on iteration #2

What's the ROOT cause vs what's a symptom?
