# Basedpyright Type Error Catalog

**Generated:** 1763512203.1090658

## Summary

- **Errors:** 95
- **Warnings:** 564
- **Notes:** 0
- **Total Issues:** 659

## Issues by Error Code

### unknown (143 occurrences)

**Example:** Argument of type "None" cannot be assigned to parameter "_task" of type "RawTask[Any, None, None]" in function "__init__"

**Severity breakdown:** error: 41, warning: 102

**Top affected files:**
  - `flow_hdl_view.py`: 45 occurrences
  - `flow.py`: 17 occurrences
  - `single_output.py`: 15 occurrences
  - `node_base.py`: 12 occurrences
  - `node.py`: 10 occurrences

### reportExplicitAny (136 occurrences)

**Example:** Type `Any` is not allowed (reportExplicitAny)

**Severity breakdown:** warning: 136

**Top affected files:**
  - `event_loop.py`: 36 occurrences
  - `flow.py`: 15 occurrences
  - `mono_node.py`: 15 occurrences
  - `node.py`: 11 occurrences
  - `node_base.py`: 10 occurrences

### reportPrivateUsage (56 occurrences)

**Example:** "_put_waiting" is protected and used outside of the class in which it is declared (reportPrivateUsage)

**Severity breakdown:** warning: 56

**Top affected files:**
  - `flow.py`: 15 occurrences
  - `flow_hdl_view.py`: 15 occurrences
  - `event_loop.py`: 9 occurrences
  - `node_base.py`: 9 occurrences
  - `single_output.py`: 3 occurrences

### reportMissingParameterType (51 occurrences)

**Example:** Type annotation is missing for parameter "tags" (reportMissingParameterType)

**Severity breakdown:** warning: 51

**Top affected files:**
  - `instrumentation.py`: 42 occurrences
  - `single_output.py`: 6 occurrences
  - `flow_hdl.py`: 2 occurrences
  - `__init__.py`: 1 occurrences

### reportUnusedImport (49 occurrences)

**Example:** Import "Generator" is not accessed (reportUnusedImport)

**Severity breakdown:** warning: 49

**Top affected files:**
  - `node_meta_single_dec.py`: 10 occurrences
  - `node.py`: 9 occurrences
  - `node_meta_multiple_dec.py`: 9 occurrences
  - `flow_hdl.py`: 8 occurrences
  - `flow.py`: 4 occurrences

### reportAny (46 occurrences)

**Example:** Type of "send_value" is Any (reportAny)

**Severity breakdown:** warning: 46

**Top affected files:**
  - `node_base.py`: 9 occurrences
  - `flow_hdl_view.py`: 7 occurrences
  - `http_client.py`: 7 occurrences
  - `instrumentation.py`: 3 occurrences
  - `single_output.py`: 3 occurrences

### reportUnannotatedClassAttribute (39 occurrences)

**Example:** Type annotation for attribute `tags` is required because this class is not decorated with `@final` (reportUnannotatedClassAttribute)

**Severity breakdown:** warning: 39

**Top affected files:**
  - `synchronization.py`: 5 occurrences
  - `selectors.py`: 4 occurrences
  - `event_loop.py`: 3 occurrences
  - `multiple_output.py`: 3 occurrences
  - `single_output.py`: 3 occurrences

### reportMissingTypeArgument (21 occurrences)

**Example:** Expected type arguments for generic class "Stream" (reportMissingTypeArgument)

**Severity breakdown:** error: 21

**Top affected files:**
  - `flow_hdl_view.py`: 9 occurrences
  - `node.py`: 5 occurrences
  - `flow.py`: 3 occurrences
  - `flow_hdl.py`: 2 occurrences
  - `group_node.py`: 1 occurrences

### reportImplicitOverride (17 occurrences)

**Example:** Method "filter" is not marked as override but is overriding a method in class "Filter" (reportImplicitOverride)

**Severity breakdown:** warning: 17

**Top affected files:**
  - `mono_node.py`: 5 occurrences
  - `streaming_node.py`: 3 occurrences
  - `instrumentation.py`: 2 occurrences
  - `node_base.py`: 2 occurrences
  - `__init__.py`: 1 occurrences

### reportDeprecated (14 occurrences)

**Example:** This type is deprecated as of Python 3.10; use "| None" instead (reportDeprecated)

**Severity breakdown:** warning: 14

**Top affected files:**
  - `single_output.py`: 8 occurrences
  - `multiple_output.py`: 4 occurrences
  - `synchronization.py`: 1 occurrences
  - `node.py`: 1 occurrences

### reportUnknownParameterType (10 occurrences)

**Example:** Type of parameter "tags" is unknown (reportUnknownParameterType)

**Severity breakdown:** warning: 10

**Top affected files:**
  - `single_output.py`: 6 occurrences
  - `node.py`: 2 occurrences
  - `__init__.py`: 1 occurrences
  - `flow_hdl_view.py`: 1 occurrences

### reportUnusedCallResult (10 occurrences)

**Example:** Result of call expression is of type "_HANDLER" and is not used; assign to variable "_" if this is intentional (reportUnusedCallResult)

**Severity breakdown:** warning: 10

**Top affected files:**
  - `event_loop.py`: 9 occurrences
  - `flow_hdl_view.py`: 1 occurrences

### reportUnusedVariable (8 occurrences)

**Example:** Variable "input_port_index" is not accessed (reportUnusedVariable)

**Severity breakdown:** warning: 8

**Top affected files:**
  - `node_base.py`: 3 occurrences
  - `single_output.py`: 3 occurrences
  - `multiple_output.py`: 2 occurrences

### reportUnknownVariableType (7 occurrences)

**Example:** Type of "producer_node" is unknown (reportUnknownVariableType)

**Severity breakdown:** warning: 7

**Top affected files:**
  - `flow.py`: 2 occurrences
  - `single_output.py`: 2 occurrences
  - `flow_hdl_view.py`: 1 occurrences
  - `node_base.py`: 1 occurrences
  - `node.py`: 1 occurrences

### reportInconsistentOverload (7 occurrences)

**Example:** "__call__" is marked as overload, but additional overloads are missing (reportInconsistentOverload)

**Severity breakdown:** error: 7

**Top affected files:**
  - `wrappers.py`: 4 occurrences
  - `asyncgen_wrapper.py`: 2 occurrences
  - `node_meta_single_dec.py`: 1 occurrences

### reportUnnecessaryTypeIgnoreComment (6 occurrences)

**Example:** Unnecessary "# pyright: ignore" rule: "reportPrivateUsage" (reportUnnecessaryTypeIgnoreComment)

**Severity breakdown:** warning: 6

**Top affected files:**
  - `event_loop.py`: 4 occurrences
  - `node_base.py`: 2 occurrences

### reportUnknownMemberType (4 occurrences)

**Example:** Type of "tags" is unknown (reportUnknownMemberType)

**Severity breakdown:** warning: 4

**Top affected files:**
  - `flow.py`: 2 occurrences
  - `__init__.py`: 1 occurrences
  - `http_server.py`: 1 occurrences

### reportUndefinedVariable (4 occurrences)

**Example:** "Stream" is not defined (reportUndefinedVariable)

**Severity breakdown:** error: 4

**Top affected files:**
  - `commands.py`: 4 occurrences

### reportUnnecessaryCast (2 occurrences)

**Example:** Unnecessary "cast" call; type is already "SpawnCommand[object]" (reportUnnecessaryCast)

**Severity breakdown:** warning: 2

**Top affected files:**
  - `event_loop.py`: 1 occurrences
  - `node_base.py`: 1 occurrences

### reportUnnecessaryComparison (2 occurrences)

**Example:** Condition will always evaluate to False since the types "Command" and "None" have no overlap (reportUnnecessaryComparison)

**Severity breakdown:** warning: 2

**Top affected files:**
  - `event_loop.py`: 1 occurrences
  - `group_node.py`: 1 occurrences

### reportUnnecessaryIsInstance (2 occurrences)

**Example:** Unnecessary isinstance call; "Coroutine[Any, Any, tuple[object, ...]] | AsyncGenerator[tuple[object, ...], None]" is always an instance of "Coroutine[Unknown, Unknown, Unknown] | AsyncGenerator[Unknown, Unknown]" (reportUnnecessaryIsInstance)

**Severity breakdown:** warning: 2

**Top affected files:**
  - `flow.py`: 1 occurrences
  - `single_output.py`: 1 occurrences

### reportOverlappingOverload (2 occurrences)

**Example:** Overload 1 for "output" overlaps overload 2 and returns an incompatible type (reportOverlappingOverload)

**Severity breakdown:** error: 2

**Top affected files:**
  - `mono_node.py`: 1 occurrences
  - `node.py`: 1 occurrences

### reportUnusedFunction (2 occurrences)

**Example:** Function "_node_id" is not accessed (reportUnusedFunction)

**Severity breakdown:** warning: 2

**Top affected files:**
  - `node_base.py`: 2 occurrences

### reportGeneralTypeIssues (2 occurrences)

**Example:** Covariant type variable cannot be used in parameter type (reportGeneralTypeIssues)

**Severity breakdown:** error: 2

**Top affected files:**
  - `node_base.py`: 2 occurrences

### reportImplicitStringConcatenation (1 occurrences)

**Example:** Implicit string concatenation not allowed (reportImplicitStringConcatenation)

**Severity breakdown:** warning: 1

**Top affected files:**
  - `flow_hdl_view.py`: 1 occurrences

### reportNoOverloadImplementation (1 occurrences)

**Example:** "output" is marked as overload, but no implementation is provided (reportNoOverloadImplementation)

**Severity breakdown:** error: 1

**Top affected files:**
  - `mono_node.py`: 1 occurrences

### reportSelfClsParameterName (1 occurrences)

**Example:** Instance methods should take a "self" parameter (reportSelfClsParameterName)

**Severity breakdown:** error: 1

**Top affected files:**
  - `node_base.py`: 1 occurrences

## Issues by File

### src/flowno/core/flow_hdl_view.py
**Total issues:** 86 (Errors: 9, Warnings: 77)

**Error codes:**
  - `unknown`: 45
  - `reportPrivateUsage`: 15
  - `reportMissingTypeArgument`: 9
  - `reportAny`: 7
  - `reportExplicitAny`: 3
  - `reportUnusedImport`: 2
  - `reportUnannotatedClassAttribute`: 1
  - `reportImplicitStringConcatenation`: 1
  - `reportUnknownParameterType`: 1
  - `reportUnknownVariableType`: 1
  - `reportUnusedCallResult`: 1

### src/flowno/core/event_loop/event_loop.py
**Total issues:** 68 (Errors: 3, Warnings: 65)

**Error codes:**
  - `reportExplicitAny`: 36
  - `reportUnusedCallResult`: 9
  - `reportPrivateUsage`: 9
  - `reportUnnecessaryTypeIgnoreComment`: 4
  - `reportUnannotatedClassAttribute`: 3
  - `unknown`: 3
  - `reportAny`: 2
  - `reportUnnecessaryCast`: 1
  - `reportUnnecessaryComparison`: 1

### src/flowno/core/flow/flow.py
**Total issues:** 62 (Errors: 4, Warnings: 58)

**Error codes:**
  - `unknown`: 17
  - `reportExplicitAny`: 15
  - `reportPrivateUsage`: 15
  - `reportUnusedImport`: 4
  - `reportMissingTypeArgument`: 3
  - `reportAny`: 2
  - `reportUnknownVariableType`: 2
  - `reportUnknownMemberType`: 2
  - `reportUnnecessaryIsInstance`: 1
  - `reportUnannotatedClassAttribute`: 1

### src/flowno/core/flow/instrumentation.py
**Total issues:** 57 (Errors: 0, Warnings: 57)

**Error codes:**
  - `reportMissingParameterType`: 42
  - `reportExplicitAny`: 9
  - `reportAny`: 2
  - `reportUnannotatedClassAttribute`: 2
  - `reportImplicitOverride`: 2

### src/flowno/core/node_base.py
**Total issues:** 56 (Errors: 11, Warnings: 45)

**Error codes:**
  - `unknown`: 12
  - `reportExplicitAny`: 10
  - `reportPrivateUsage`: 9
  - `reportAny`: 9
  - `reportUnusedVariable`: 3
  - `reportUnusedFunction`: 2
  - `reportUnnecessaryTypeIgnoreComment`: 2
  - `reportGeneralTypeIssues`: 2
  - `reportImplicitOverride`: 2
  - `reportSelfClsParameterName`: 1
  - `reportMissingTypeArgument`: 1
  - `reportUnnecessaryCast`: 1
  - `reportUnknownVariableType`: 1
  - `reportUnannotatedClassAttribute`: 1

### src/flowno/decorators/single_output.py
**Total issues:** 54 (Errors: 7, Warnings: 47)

**Error codes:**
  - `unknown`: 15
  - `reportDeprecated`: 8
  - `reportUnknownParameterType`: 6
  - `reportMissingParameterType`: 6
  - `reportExplicitAny`: 4
  - `reportAny`: 3
  - `reportUnusedVariable`: 3
  - `reportPrivateUsage`: 3
  - `reportUnannotatedClassAttribute`: 3
  - `reportUnknownVariableType`: 2
  - `reportUnnecessaryIsInstance`: 1

### src/flowno/decorators/node.py
**Total issues:** 44 (Errors: 11, Warnings: 33)

**Error codes:**
  - `reportExplicitAny`: 11
  - `unknown`: 10
  - `reportUnusedImport`: 9
  - `reportMissingTypeArgument`: 5
  - `reportUnknownParameterType`: 2
  - `reportAny`: 2
  - `reportUnannotatedClassAttribute`: 2
  - `reportDeprecated`: 1
  - `reportOverlappingOverload`: 1
  - `reportUnknownVariableType`: 1

### src/flowno/core/mono_node.py
**Total issues:** 29 (Errors: 8, Warnings: 21)

**Error codes:**
  - `reportExplicitAny`: 15
  - `unknown`: 6
  - `reportImplicitOverride`: 5
  - `reportOverlappingOverload`: 1
  - `reportNoOverloadImplementation`: 1
  - `reportAny`: 1

### src/flowno/core/flow_hdl.py
**Total issues:** 26 (Errors: 2, Warnings: 24)

**Error codes:**
  - `reportUnusedImport`: 8
  - `reportExplicitAny`: 7
  - `unknown`: 5
  - `reportMissingTypeArgument`: 2
  - `reportMissingParameterType`: 2
  - `reportAny`: 2

### src/flowno/core/group_node.py
**Total issues:** 20 (Errors: 1, Warnings: 19)

**Error codes:**
  - `unknown`: 8
  - `reportExplicitAny`: 4
  - `reportUnusedImport`: 2
  - `reportMissingTypeArgument`: 1
  - `reportUnnecessaryComparison`: 1
  - `reportPrivateUsage`: 1
  - `reportAny`: 1
  - `reportUnannotatedClassAttribute`: 1
  - `reportImplicitOverride`: 1

### src/flowno/core/event_loop/synchronization.py
**Total issues:** 14 (Errors: 0, Warnings: 14)

**Error codes:**
  - `reportUnannotatedClassAttribute`: 5
  - `unknown`: 5
  - `reportDeprecated`: 1
  - `reportUnusedImport`: 1
  - `reportImplicitOverride`: 1
  - `reportPrivateUsage`: 1

### src/flowno/core/event_loop/instrumentation.py
**Total issues:** 13 (Errors: 2, Warnings: 11)

**Error codes:**
  - `unknown`: 4
  - `reportExplicitAny`: 3
  - `reportAny`: 3
  - `reportUnannotatedClassAttribute`: 2
  - `reportPrivateUsage`: 1

### src/flowno/io/http_client.py
**Total issues:** 13 (Errors: 0, Warnings: 13)

**Error codes:**
  - `reportAny`: 7
  - `reportExplicitAny`: 3
  - `unknown`: 2
  - `reportPrivateUsage`: 1

### src/flowno/decorators/node_meta_single_dec.py
**Total issues:** 12 (Errors: 2, Warnings: 10)

**Error codes:**
  - `reportUnusedImport`: 10
  - `reportInconsistentOverload`: 1
  - `unknown`: 1

### src/flowno/core/streaming_node.py
**Total issues:** 11 (Errors: 4, Warnings: 7)

**Error codes:**
  - `unknown`: 4
  - `reportExplicitAny`: 3
  - `reportImplicitOverride`: 3
  - `reportAny`: 1

### src/flowno/decorators/node_meta_multiple_dec.py
**Total issues:** 11 (Errors: 0, Warnings: 11)

**Error codes:**
  - `reportUnusedImport`: 9
  - `reportExplicitAny`: 2

### src/flowno/core/event_loop/commands.py
**Total issues:** 10 (Errors: 4, Warnings: 6)

**Error codes:**
  - `reportUndefinedVariable`: 4
  - `reportUnusedImport`: 3
  - `reportExplicitAny`: 3

### src/flowno/core/event_loop/primitives.py
**Total issues:** 10 (Errors: 4, Warnings: 6)

**Error codes:**
  - `unknown`: 5
  - `reportExplicitAny`: 3
  - `reportAny`: 2

### src/flowno/decorators/multiple_output.py
**Total issues:** 9 (Errors: 0, Warnings: 9)

**Error codes:**
  - `reportDeprecated`: 4
  - `reportUnannotatedClassAttribute`: 3
  - `reportUnusedVariable`: 2

### src/flowno/decorators/wrappers.py
**Total issues:** 9 (Errors: 4, Warnings: 5)

**Error codes:**
  - `reportInconsistentOverload`: 4
  - `reportExplicitAny`: 2
  - `reportUnannotatedClassAttribute`: 2
  - `reportUnusedImport`: 1

### src/flowno/__init__.py
**Total issues:** 5 (Errors: 0, Warnings: 5)

**Error codes:**
  - `reportUnknownParameterType`: 1
  - `reportMissingParameterType`: 1
  - `reportUnannotatedClassAttribute`: 1
  - `reportImplicitOverride`: 1
  - `reportUnknownMemberType`: 1

### src/flowno/core/event_loop/selectors.py
**Total issues:** 5 (Errors: 0, Warnings: 5)

**Error codes:**
  - `reportUnannotatedClassAttribute`: 4
  - `reportPrivateUsage`: 1

### src/flowno/utilities/asyncgen_wrapper.py
**Total issues:** 5 (Errors: 2, Warnings: 3)

**Error codes:**
  - `reportUnannotatedClassAttribute`: 3
  - `reportInconsistentOverload`: 2

### src/flowno/io/http_server.py
**Total issues:** 4 (Errors: 1, Warnings: 3)

**Error codes:**
  - `reportUnannotatedClassAttribute`: 2
  - `reportUnknownMemberType`: 1
  - `unknown`: 1

### src/flowno/utilities/coroutine_wrapper.py
**Total issues:** 4 (Errors: 0, Warnings: 4)

**Error codes:**
  - `reportUnannotatedClassAttribute`: 3
  - `reportImplicitOverride`: 1

### src/flowno/core/event_loop/types.py
**Total issues:** 3 (Errors: 0, Warnings: 3)

**Error codes:**
  - `reportExplicitAny`: 3

### src/flowno/core/event_loop/queues.py
**Total issues:** 2 (Errors: 0, Warnings: 2)

**Error codes:**
  - `reportAny`: 2

### src/flowno/core/event_loop/tasks.py
**Total issues:** 1 (Errors: 0, Warnings: 1)

**Error codes:**
  - `reportImplicitOverride`: 1
