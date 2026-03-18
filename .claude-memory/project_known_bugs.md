---
name: Known Bugs — Stale Check and Binary Tree Deadlock
description: Two active bugs found during the 2026-03-17 investigation session
type: project
---

## Bug 1: Double-execution in acyclic streaming graphs

**Symptom:** `test_source_two_forks_two_collectors` fails — graph executes correctly once, then re-executes with data loss (Fork misses item 0 on second pass). Second run overwrites correct first run results.

**Root cause hypothesis:** The stale check at `node_base.py:648` uses `<= 0`:
```python
if cmp_generation(clipped_gen, self.generation) <= 0:
    stale_inputs.append(input_port)
```
Equal generations (`cmp((0,), (0,)) = 0`) satisfy `<= 0`, marking completed nodes as stale. This triggers re-resolution and re-execution.

**Confirmed via:** `debug_stale.py` instrumentation showed Source re-resolving at generation (0,) because `cmp((0,), (0,)) = 0 <= 0`.

**Complication:** The `<=` is needed for the initial case where both nodes are `None` (`cmp(None, None) = 0`). Changing to `<` would break initial startup.

**Why:** Concurrent streaming with multiple consumers creates complex interleaving where this re-execution matters.

**How to apply:** Fix needs to either track completion state explicitly, or handle the initial `None`/`None` case separately from the equal-generation case.

## Bug 2: Binary tree streaming deadlock

**Symptom:** `test_known_concurrency_bug` hangs — binary tree topology (Source → Fork^4 → Join^4) deadlocks.

**Root cause hypothesis:** Barrier1 mechanism requires a Fork producer to wait for ALL consumers to read before yielding the next item. Join nodes consume streams sequentially (`consume_all(a)` then `consume_all(b)`). In a tree topology, Fork_parent waits for Fork_child_B to read, but Fork_child_B's consumer (Join) is blocked draining Fork_child_A first, and Fork_child_A needs Fork_parent to yield more items.

**Why:** Sequential stream consumption + barrier synchronization + tree topology creates circular wait conditions.

**How to apply:** This is a deeper architectural issue with how barriers interact with multi-consumer streaming. May need a fundamentally different approach to backpressure in fan-out topologies.
