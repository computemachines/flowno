# Formal Verification for Flowno

This directory contains TLA+ specifications that formally verify properties of the Flowno dataflow framework.

## Overview

We're using **TLA+** (Temporal Logic of Actions) to specify and verify Flowno's behavior. TLA+ lets us:

1. **Specify** the intended behavior mathematically
2. **Check** that our implementation satisfies key properties
3. **Find** bugs like deadlocks, race conditions, and invariant violations

## Learning Path

We'll build specifications incrementally:

### Level 1: Abstract Specifications (Design Intent)
High-level specs that capture *what* Flowno should do, not *how* it does it.
- Node execution semantics
- Data flow between nodes
- Generation-based ordering

### Level 2: Refinement Specifications (Implementation)
More detailed specs that follow the actual implementation more closely.
- Event loop behavior
- Task scheduling
- Queue operations

### Level 3: Property Checking
Verify critical properties:
- **Safety**: Bad things never happen (no deadlocks, no data races)
- **Liveness**: Good things eventually happen (all nodes complete)
- **Invariants**: Data consistency is maintained

## Key Flowno Concepts to Verify

Based on the documentation, these are the core behaviors:

1. **Node Triggering**: When a node evaluates, it triggers all dependent downstream nodes
2. **Input Freshness**: Before evaluation, a node waits for all inputs to be newer than its last evaluation
3. **Cycle Bootstrap**: Cycles use default values to bootstrap
4. **Generation Tracking**: Per-node generation values keep flow in lockstep

## Running Verification

```bash
# From the flowno root directory
java -jar ./formal-verification/tla2tools.jar ./formal-verification/specs/YourSpec.tla
```

## File Organization

```
formal-verification/
├── README.md           # This file
├── tla2tools.jar       # TLC model checker
├── specs/              # TLA+ specifications
│   ├── 01_SingleNode.tla       # Simplest spec: one node
│   ├── 02_TwoNodes.tla         # Data flow between nodes
│   ├── 03_CyclicFlow.tla       # Cyclic dependencies
│   └── ...
└── docs/               # Learning materials
    └── TLA_Primer.md   # Quick intro to TLA+ syntax
```

## TLA+ Quick Reference

```tla
(* This is a comment *)

VARIABLES x, y          \* Declare state variables

Init == x = 0 /\ y = 0  \* Initial state predicate

Next == x' = x + 1      \* Transition predicate (x' is next state of x)

Spec == Init /\ [][Next]_<<x,y>>  \* Full specification

TypeInvariant == x \in Nat       \* Type checking invariant
```

## Resources

- [TLA+ Video Course by Lamport](https://lamport.azurewebsites.net/video/videos.html)
- [Learn TLA+](https://learntla.com/)
- [TLA+ Toolbox](https://github.com/tlaplus/tlaplus/releases)
