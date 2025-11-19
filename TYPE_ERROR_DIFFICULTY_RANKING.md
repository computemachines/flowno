# Type Error Difficulty Ranking

Based on analysis of 659 type issues found by basedpyright.

## Difficulty Scale
- **1-3**: Simple mechanical fixes, no deep understanding needed
- **4-6**: Requires understanding code flow and type relationships
- **7-9**: Complex architectural or advanced typing issues

---

## Difficulty 1: Trivial Cleanup (49 issues)

### reportUnusedImport (49 occurrences)
**What:** Imports that aren't being used
**Fix:** Delete the unused import lines
**Example:** `from collections.abc import Generator` when Generator isn't used
**Time:** 5 seconds per fix
**Risk:** None

---

## Difficulty 2: Simple Syntax Updates (83 issues)

### Missing TYPE_CHECKING Imports (4 occurrences) ✅ FIXED
**What:** Forward-referenced types missing from TYPE_CHECKING block
**Fix:** Add imports under `if TYPE_CHECKING:` guard
**Example:** What we just fixed in commands.py
**Time:** 2-5 minutes to identify and fix
**Risk:** Low

### reportDeprecated (14 occurrences)
**What:** Old Python typing syntax
**Fix:** Update to modern syntax
**Examples:**
- `Optional[T]` → `T | None`
- `Tuple[...]` → `tuple[...]`
- `Union[A, B]` → `A | B`
**Time:** 30 seconds per fix
**Risk:** None

### reportImplicitOverride (17 occurrences)
**What:** Methods override parent methods without `@override` decorator
**Fix:** Add `@override` decorator from typing_extensions
**Example:** Method `filter()` overrides parent `Filter.filter()`
**Time:** 30 seconds per fix
**Risk:** None

### reportUnannotatedClassAttribute (39 occurrences)
**What:** Class attributes without type annotations
**Fix:** Add type annotations like `tags: list[str]`
**Example:** `self.tags = tags` → `tags: list[str]; self.tags = tags`
**Time:** 1-2 minutes per fix (need to infer correct type)
**Risk:** Low

### reportUnusedVariable (8 occurrences)
**What:** Variables assigned but never used
**Fix:** Either remove or rename to `_` if intentionally ignored
**Example:** `input_port_index, val = ...` → `_, val = ...`
**Time:** 30 seconds per fix
**Risk:** Low

### reportUnnecessaryTypeIgnoreComment (6 occurrences)
**What:** Type ignore comments that are no longer needed
**Fix:** Remove the `# type: ignore` or `# pyright: ignore` comment
**Time:** 10 seconds per fix
**Risk:** None

---

## Difficulty 3: Simple Type Annotations (51 issues)

### reportMissingParameterType (51 occurrences)
**What:** Function parameters without type annotations
**Fix:** Add type annotation based on how parameter is used
**Example:** `def foo(tags):` → `def foo(tags: list[str]):`
**Time:** 2-5 minutes per fix (need to trace usage)
**Risk:** Low, but need to ensure correct type

---

## Difficulty 4: Generic Type Arguments (21 issues)

### reportMissingTypeArgument (21 occurrences)
**What:** Generic classes used without type parameters
**Fix:** Add proper type arguments
**Example:** `Stream` → `Stream[int]` or `Stream[object]`
**Time:** 5-10 minutes per fix (need to understand data flow)
**Risk:** Medium - incorrect type arguments can break type safety
**Files affected:** Mostly `flow_hdl_view.py`, `node.py`, `flow.py`

---

## Difficulty 5: Replacing Any Types (182 issues)

### reportExplicitAny (136 occurrences)
**What:** Explicit use of `Any` type annotation
**Fix:** Replace with specific types
**Example:** `def foo(x: Any)` → `def foo(x: int | str | MyClass)`
**Time:** 10-20 minutes per fix (need to understand all possible types)
**Risk:** Medium - may require adding generic parameters or union types
**Note:** Some `Any` might be intentional for truly dynamic code

### reportAny (46 occurrences)
**What:** Variables/expressions inferred as `Any`
**Fix:** Add explicit type annotations to clarify type
**Example:** When return type is inferred as `Any`, add explicit return type
**Time:** 10-20 minutes per fix
**Risk:** Medium

---

## Difficulty 6: Architectural Issues (79 issues)

### reportPrivateUsage (56 occurrences)
**What:** Accessing protected/private members from outside the class
**Fix:** Either make members public or refactor to use proper API
**Example:** Accessing `queue._put_waiting` from outside the queue class
**Time:** 20-60 minutes per fix (may require refactoring)
**Risk:** High - changes to class interfaces
**Decision needed:** Some may warrant making attributes public

### reportUnknownParameterType (10 occurrences)
**What:** Parameter type cannot be inferred and has no annotation
**Fix:** Add type annotation, may reveal deeper type issues
**Time:** 10-30 minutes
**Risk:** Medium

### reportUnknownVariableType (7 occurrences)
**What:** Variable type cannot be inferred
**Fix:** Add type annotation or restructure code for better inference
**Time:** 10-30 minutes
**Risk:** Medium

### reportUnknownMemberType (4 occurrences)
**What:** Member access on unknown type
**Fix:** Fix the parent type issue first
**Time:** 10-30 minutes
**Risk:** Medium

### reportUnnecessaryComparison/reportUnnecessaryIsInstance/reportUnnecessaryCast (6 occurrences)
**What:** Dead code or redundant type checks
**Fix:** Remove unnecessary code or fix type narrowing logic
**Time:** 10-30 minutes
**Risk:** Low to Medium

---

## Difficulty 7: Overload Issues (12 issues)

### reportOverlappingOverload (2 occurrences)
**What:** Overload signatures that conflict with each other
**Fix:** Restructure overload signatures to be mutually exclusive
**Example:** Two overloads both match the same input types
**Time:** 1-2 hours (requires understanding all call patterns)
**Risk:** High - affects API surface
**Files:** `mono_node.py:108`, `node.py:193`

### reportNoOverloadImplementation (1 occurrence)
**What:** `@overload` decorators without an implementation
**Fix:** Add the actual implementation function
**Time:** 1-2 hours
**Risk:** High
**Files:** `mono_node.py:108`

### reportInconsistentOverload (7 occurrences)
**What:** Overload signatures don't match the implementation signature
**Fix:** Make implementation signature compatible with all overloads
**Time:** 1-3 hours per issue
**Risk:** High - complex signature juggling
**Files:** `wrappers.py` (4), `asyncgen_wrapper.py` (2), `node_meta_single_dec.py` (1)

### reportUnusedCallResult (10 occurrences)
**What:** Function returns a value that should be used but isn't
**Fix:** Either use the result or assign to `_`
**Time:** 5-10 minutes
**Risk:** Low

---

## Difficulty 8: Variance and Complex Generic Issues (145 issues)

### reportGeneralTypeIssues (2 occurrences)
**What:** Covariant type variables used in parameter positions (unsound)
**Fix:** Change variance or restructure the type hierarchy
**Example:** `def foo(x: _T_co)` where `_T_co` is covariant
**Time:** 2-4 hours (deep type theory knowledge required)
**Risk:** Very High - may require major refactoring
**Files:** `node_base.py:336` (2 occurrences)

### "unknown" errors (143 occurrences) - varies widely
**What:** Complex type mismatches, wrong types assigned
**Examples:**
- "Argument of type X cannot be assigned to parameter of type Y"
- "Type X is not assignable to type Y"
- Type inference failures in complex generic contexts
**Fix:** Highly variable - some easy, some extremely hard
**Time:** 15 minutes to 4+ hours depending on complexity
**Risk:** High - often reveals design issues
**Difficulty range:** 3-8 depending on specific error
**Top files:** `flow_hdl_view.py` (45), `flow.py` (17), `single_output.py` (15)

---

## Difficulty 9: Decorator Generic Type Transformations (11+ issues)

### @node Decorator Type Signature Issues
**What:** The `@node` decorator needs to properly transform function signatures into node types
**Complexity:**
- Takes a callable and returns a different type (DraftNode subclass)
- Must preserve generic type parameters from function to node
- Multiple overloads for different input/output arities
- Needs to work with both sync and async functions
- Complex interplay with `@single_output` and `@multiple_output`

**Related errors:**
- `node.py:193` - Overload 2 overlaps overload 3
- `node.py:241` - Inconsistent overload implementation
- `node_meta_single_dec.py:120` - Missing overloads
- `node_meta_single_dec.py:164` - Type not assignable to return type
- Various `reportExplicitAny` in decorator files

**Fix:** Requires:
1. Deep understanding of decorator type transformation
2. Advanced knowledge of Python's type system (ParamSpec, Concatenate, etc.)
3. Careful overload design to handle all cases
4. May need to use `typing.Protocol` for complex cases

**Time:** 8-20+ hours of work
**Risk:** Extreme - core API functionality
**Why it's the hardest:**
- Decorators that transform types are one of the hardest typing challenges
- Multiple layers of abstraction (decorator → metaclass → node class)
- Generic type propagation through multiple layers
- Must work at both type-checking time and runtime

---

## Difficulty 10 (Bonus): Import Cycles

### reportImportCycles (multiple occurrences)
**What:** Circular dependencies between modules
**Current state:** Partially mitigated with `TYPE_CHECKING` guards
**Fix options:**
1. More `TYPE_CHECKING` guards (band-aid) - Difficulty 3
2. Refactor module structure to break cycles (proper fix) - Difficulty 8
**Time:** 4-40+ hours depending on approach
**Risk:** Extreme if doing full refactor
**Note:** Some cycles may be acceptable if they only exist at type-checking time

---

## Summary by Difficulty

| Difficulty | Count | Effort | Examples |
|------------|-------|--------|----------|
| 1 | 49 | Minutes | Unused imports |
| 2 | 79 | Hours | Deprecated syntax, simple annotations |
| 3 | 51 | Hours | Missing parameter types |
| 4 | 21 | Days | Generic type arguments |
| 5 | 182 | Days-Weeks | Replace Any types |
| 6 | 79 | Weeks | Private usage, architectural |
| 7 | 12 | Weeks | Overload issues |
| 8 | 145 | Weeks-Months | Variance, complex unknowns |
| 9 | 11+ | Months | Decorator type transformations |
| 10 | varies | Varies | Import cycle refactoring |

**Total: 650 issues** (after our fix of 9 issues)

---

## Recommended Fixing Order

1. **Quick wins** (Difficulty 1-2): Fix 128 issues in 1-2 days
2. **Type annotations** (Difficulty 3): Fix 51 issues in 2-3 days
3. **Generic arguments** (Difficulty 4): Fix 21 issues in 1-2 weeks
4. **Any replacement** (Difficulty 5): Ongoing effort, 2-4 weeks
5. **Architectural** (Difficulty 6+): Requires design decisions, 1-3 months

The @node decorator issues (Difficulty 9) should be tackled last as they represent the most complex type transformations in the codebase.
