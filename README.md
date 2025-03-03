# Flowno

Flowno is a Python DSL for building concurrent, cyclic, and streaming
[dataflow](https://en.wikipedia.org/wiki/Dataflow_programming) programs—ideal
for designing modular LLM agents. Inspired by no-code flowchart tools like
[ComfyUI](https://github.com/comfyanonymous/ComfyUI), Flowno lets you describe
workflows in code while handling complex dependency resolution (including cycles
and streaming) behind the scenes.

## Key Features

- **Node-Based Design**  
  Define processing steps as nodes with a simple decorator. Nodes can be
  stateless or stateful - consume, yield or transform streams - single or
  multiple outputs. 

- **Cycles & Streaming**  
  Unlike many workflow/flowchart/visual dataflow tools, Flowno supports cyclic
  graphs and streaming outputs. Use default values to bootstrap cycles.

- **Concurrent By Default**  
  The Flowno runtime schedules nodes to run as soon as their inputs are ready.
  Flowno provides a set of basic non-blocking concurrency primitives.

- **Type-Checked & Autocompleted**
  Flowno is designed to work well with type checkers and IDEs to catch
  incompatible connections between nodes.
  


## Quickstart

Set up a virtual environment and install Flowno:

```bash
python -m venv .venv  # Requires Python 3.10+
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
pip install flowno
```

Create a minimal flow (`hello.py`):

```python
from flowno import node, FlowHDL

@node
async def Add(x, y):
    return x + y

@node
async def Print(value):
    print(f"Value: {value}")

with FlowHDL() as f:
    f.sum = Add(1, 2)
    f.print = Print(f.sum)

f.run_until_complete()
```
```bash
(.venv) $ python hello.py
Value: 3
```

## How It Works

Flowno has three key components that work together to create dataflow programs:

### 1. Node Creation
The `@node` decorator transforms `async` functions (or classes) into a
constructor for a new subclass of `DraftNode`. The transformed function
takes takes connections to other nodes or constant values as arguments and
returns a `DraftNode` instance. 

```python
@node
async def Add(x, y):
    return x + y

draft_node_1 = Add(1, 2)  # Creates a node that will add 1 and 2
draft_node_2 = Add(draft_node_1, 3)  # Connects to the output of draft_node_1 to first input of draft_node_2
```

### 2. Flow Description
The `FlowHDL` context manager provides a declarative way to define node 
connections. Inside this context, nodes are assigned as attributes and can reference 
other nodes' outputs:

```python
with FlowHDL() as f:
    f.node_a = Add(1, 2)          # No references
    f.node_b = Add(f.node_a, 1)   # Backward reference

    f.node_c = Add(f.node_d, 1)   # Forward reference
    f.node_d = Add(f.node_c, 1)   # Backward reference creating a cycle
```

The context uses Python's `__getattr__` method to return placeholder objects when 
accessing undefined attributes like `f.node_d`. These forward references are a core 
feature of Flowno—they're not errors. However, each forward-referenced node must 
eventually be defined in the flow (as shown in the last line for `f.node_d`). During 
`__exit__`, the placeholders are resolved into proper node connections, and all 
`DraftNode` instances are finalized into full `Node` objects.

This mechanism allows you to define nodes in any order, which simplifies the 
construction of cyclic graphs.

### 3. Execution
When you call `f.run_until_complete()`, Flowno executes your flow:

1. Identifies nodes ready to run (those with all inputs available)
2. Executes ready nodes concurrently
3. Propagates outputs to dependent nodes
4. For cyclic flows, uses default values to bootstrap the cycle

The runtime is asynchronous - nodes only wait for their direct dependencies and
run concurrently with other nodes.  Execution continues until all nodes complete
or, for cyclic flows, until an uncaught exception occurs.

## Features TODO

- **Conditional Nodes**  
  Currently all nodes are executed unconditionally. The only way to skip a node is to add an immediate return statement to bypass the node's logic. I plan to add a way to conditionally execute nodes based on the output of other nodes.

## Non-Goals

- **Visual Editor**  
  Flowno is a DSL for defining dataflows in code. It does not include a visual
  editor for creating flows. I have a crude prototype of a visual editor, but I
  just don't see the value in dragging and dropping nodes. A visual editor can't
  be used by a LLM agent, for example.

- **Backpropagation**  
  Flowno is not a machine learning framework. I considered adding some sort of
  automatic differentiation, but I could never do it as well as PyTorch, and
  cycles would be difficult.


## About The Naming Conventions

> A Foolish Consistency is the Hobgoblin of Little Minds
> 
> -- <cite>Style Guide for Python Code (PEP-8)</cite>

My naming conventions deviate from standard Python style. I capitalize node names 
(like `Add` instead of `add`) because they are factory functions that behave like 
classes - when you call a decorated node function, it returns a `DraftNode` 
instance.

The `FlowHDL` context with its `f.node_name = Node()` syntax is an abuse of 
Python's `__getattr__` method. However, this approach enables:
- LSP type checking support
- Slightly better IDE autocomplete functionality
- Forward references for natural cycle definitions

## License

Flowno is released under the MIT License.
