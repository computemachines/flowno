# Discussion Notes - December 3, 2025

**Participants:** Developer, VS Code Copilot (Claude Opus 4.5)

## Topic: Understanding Streaming, Formal Verification, and Debugging Strategy

---

## Key Insights

### Parent Generation vs Clipped Generation

- **`parent_generation(gen)`**: Simply removes the last element of the generation tuple. E.g., `(0, 2)` → `(0,)`
- **`clip_generation(gen, run_level)`**: Finds the *largest* generation ≤ input that's compatible with the run level. More complex - may need to decrement values.

The parent generation check in `StreamGetCommand` handler detects when a producer has moved to a new parent generation (stream completed or restarted) while the consumer was still reading from the old one.

### Why Parent Generation Check Matters

Without it, when a producer finishes streaming and moves from `(0, 2)` to `(1,)`:
- `cmp_generation((1,), (0, 2))` returns 1 (greater than)
- Code thinks "data is ready" but `get_data(run_level=1)` returns `None`
- Consumer receives `None` instead of `StopAsyncIteration`

The parent generation check catches this and correctly signals stream completion.

### The Concurrency Hazard

The event loop queue contains `(task, send_value, exception)` tuples. When an item is added, assumptions are made about current state. By the time it's processed, earlier items may have changed that state.

Example: `StreamCancelCommand` added to queue, but by processing time the producer already moved to a new generation. Need to track `cancelled_at_generation` to scope cancellation correctly.

---

## Formal Verification Discussion

### Options Evaluated

| Approach | Finds Bugs | Explains Why | Scales | Learning Curve |
|----------|------------|--------------|--------|----------------|
| Fuzzing/Property testing | ✓ | ✗ | ✓✓ | Low |
| TLA+ model checking | ✓ | ✓ | ✗ (state explosion) | Medium |
| Theorem proving (Coq, Lean) | ✓ | ✓✓ | ✓ (if you can write proofs) | Very High |
| Runtime verification | ✓ | ✓ | ✓✓ | Low |

### TLA+ Reality Check

**Pros:**
- Amazon/AWS uses it for S3, DynamoDB - finds real bugs
- Event loop + queue + state machines is exactly what it's designed for
- Model checker automatically finds counterexamples

**Cons:**
- You model an *abstraction*, not actual Python code
- State space explodes with multiple nodes/states
- Proving "no combination of nodes can deadlock" for arbitrary graphs is likely beyond practical model checking

### The "Powerful for Toys" Concern

Valid worry. Most formal methods papers show 200-line protocols taking months to verify. The exceptions (AWS, Microsoft) have full-time verification teams.

---

## Agreed Plan

1. **Learn TLA+** - Forces precise thinking, catches design-level bugs
   - Start with just the event loop + task queue, ignoring streaming
   - Add streaming as a second layer

2. **Augment with "reason" lists** - Already started with `AsyncMapQueue`
   - Track *why* something was enqueued, not just *what*
   - Consider structured reasons:
     ```python
     @dataclass
     class EnqueueReason:
         source: str  # "StreamGetCommand", "ResumeNodeCommand", etc.
         generation: Generation | None
         details: str
     ```

3. **Build visual timeline tooling** - Analyze verbose instrumentation logs
   - Plot state evolution for good vs bad examples
   - Make contradictions visible

4. **Ship MVP app** - Once current bug is solved

5. **Hypothesis fuzzing** - Continually fuzz for edge cases TLA+ couldn't model efficiently

---

## The Core Problem

Two bugs with contradictory solutions. This usually means:
1. Mental model has an implicit wrong assumption
2. "Solutions" fix symptoms, not root cause  
3. Missing concept that would unify both cases

The UML sequence diagrams (4 weeks invested) helped solve the basic streaming problem. Similar investment in formal methods may help with the harder problems (cancellation, multi-consumer, cycle handling).

---

## Technical Notes

### Stream State Tracking

```python
@dataclass
class StreamConsumerState:
    last_consumed_generation: Generation | None = None
    last_consumed_parent_generation: Generation | None = None
    cancelled: bool = False
```

### Data Readiness Check

```python
# Data NOT ready if:
cmp_generation(clipped_stitched_gen, state.last_consumed_generation) <= 0

# Stream complete if:
current_parent_gen != state.last_consumed_parent_generation
```

### Barrier Purpose

Higher run levels should only operate in an environment with equal clipped generations. Barriers ensure all consumers at a given run level are "in sync" before the producer moves on.

Cancellation is a *separate* concern - could be handled via flags the producer checks at well-defined points.

---

## Resources Mentioned

- **TLA+**: "Learn TLA+" video course by Lamport (free), "Practical TLA+" book by Hillel Wayne
- **CSP**: Roscoe's "Understanding Concurrent Systems"
- **Hypothesis stateful testing**: For adversarial interleaving generation

---

## Next Session

- Potentially sketch TLA+ model of event loop
- Or: describe the two contradictory bugs for fresh perspective
