"""
Generation tracking utilities for Flowno's dataflow execution system.

This module provides helper functions for working with generation tuples, which are
used throughout Flowno to track execution order, dependency resolution, and manage
streaming data in dataflow graphs.

Generation tuples are ordered sequences of integers (e.g., (0,), (1, 0), (2, 1, 3))
that version the data produced by nodes. Each position represents a different
run level, where:
- The first element (main_gen) tracks the primary execution count
- Later elements track nested levels for streaming or partial results

See the :py:mod:`flowno.core.flow.flow` module for more information on how
generations are used in Flowno's execution model.
"""

from typing import Literal

from flowno.core.types import Generation


def cmp_generation(gen_a: Generation, gen_b: Generation) -> Literal[-1, 0, 1]:
    """
    Compare two generation tuples according to Flowno's ordering rules.
    
    The ordering follows these principles:
    
    1. None values are considered "newest" (not yet run)
    2. For non-None tuples, lexicographical comparison is used first
    3. If lexicographical comparison gives equality but lengths differ, shorter tuples are considered "greater" (more final) than longer ones
    
    Args:
        gen_a: First generation tuple to compare
        gen_b: Second generation tuple to compare
        
    Returns:
        -1 if gen_a < gen_b (gen_a comes before gen_b)
        0 if gen_a == gen_b
        1 if gen_a > gen_b (gen_a comes after gen_b)
        
    Examples:
        >>> cmp_generation(None, None)
        0
        >>> cmp_generation(None, (0,))
        -1  # None comes before any tuple
        >>> cmp_generation((1,), (0,))
        1   # (1,) > (0,)
        >>> cmp_generation((0,), (0, 0))
        1   # Shorter tuple is considered greater
        >>> cmp_generation((0, 1), (0, 2))
        -1  # Lexicographical comparison
    """

    # None values indicate that the node has never been run
    if gen_a is None and gen_b is None:
        return 0
    elif gen_a is None and gen_b is not None:
        # node_a has never been run, so is considered "newer"/"less final" than node_b
        return -1
    elif gen_a is not None and gen_b is None:
        # node_b has never been run, so is considered "newer"/"less final" than node_a
        return 1
    assert gen_a is not None and gen_b is not None

    # Rule 1: Lexicographical comparison of indexes
    for idx_a, idx_b in zip(gen_a, gen_b):
        if idx_a < idx_b:
            return -1
        elif idx_a > idx_b:
            return 1

    # Rule 2: If one tuple is shorter, it's considered "greater" (more final result)
    if len(gen_a) < len(gen_b):
        return 1  # Shorter tuple (final result) comes after longer tuple (partial result)
    elif len(gen_a) > len(gen_b):
        return -1  # Longer tuple (partial result) comes before shorter tuple (final result)

    # Tuples are identical
    return 0


def inc_generation(gen: tuple[int, ...] | None, run_level: int = 0) -> tuple[int, ...]:
    """
    Increment the generation at the specified run level.
    
    Computes the minimal generation greater than `gen` according to `cmp_generation`.
    This is used to calculate the next generation when a node runs.
    
    Args:
        gen: The current generation to increment, or None
        run_level: The index within the generation tuple to increment
        
    Returns:
        A new generation tuple that is minimally greater than the input
        
    Raises:
        ValueError: If no generation greater than the input can be found
        
    Examples:
        >>> inc_generation(None, 0)
        (0,)        # First generation at run level 0
        >>> inc_generation((0,), 0)
        (1,)        # Increment run level 0
        >>> inc_generation((1,), 1)
        (1, 0)      # First generation at run level 1
        >>> inc_generation((1, 0), 1)
        (1, 1)      # Increment run level 1
        >>> inc_generation((0, 0), 2)
        (0, 0, 0)   # First generation at run level 2
    """
    if gen is None:
        return (0,) * (run_level + 1)
    else:  # Extend gen to length run_level + 1
        candidate_gen = gen[: run_level + 1]
        if len(candidate_gen) < run_level + 1:
            candidate_gen += (0,) * (run_level + 1 - len(candidate_gen))
        # First, check if the extended candidate_gen is greater than gen
        if cmp_generation(candidate_gen, gen) > 0:
            return candidate_gen
        else:
            # Attempt to increment starting from run_level down to 0
            for rl in range(run_level, -1, -1):
                new_gen = list(gen[: rl + 1])
                if len(new_gen) < run_level + 1:
                    new_gen.extend([0] * (run_level + 1 - len(new_gen)))
                new_gen[rl] += 1
                candidate_gen = tuple(new_gen)
                if cmp_generation(candidate_gen, gen) > 0:
                    return candidate_gen
            raise ValueError(f"Cannot increment generation {gen} at run_level {run_level}")


def clip_generation(gen: Generation, run_level: int) -> Generation:
    """
    Clip a generation tuple to be compatible with a specific run level.
    
    This function returns the "highest" generation (according to `cmp_generation`) that is
    less than or equal to `gen` and has a length of at most `run_level + 1`. It's used
    to determine if a node with streaming capabilities should wait for more data or
    can proceed with what's available.
    
    Args:
        gen: The generation tuple to clip
        run_level: The run level to clip to
        
    Returns:
        A clipped generation tuple, or None if no suitable generation exists
        
    Examples:
        >>> clip_generation((0, 0), 3)
        (0, 0)      # Already compatible with run_level 3
        >>> clip_generation((0, 0), 2)
        (0, 0)      # Already compatible with run_level 2
        >>> clip_generation((0, 0), 0)
        None        # No compatible generation exists
        >>> clip_generation((1, 0), 1)
        (1, 0)      # Already compatible with run_level 1
        >>> clip_generation((1, 0), 0)
        (0,)        # Clipped to run_level 0
    """
    if gen is None:
        return None

    max_len = run_level + 1

    # If gen is already shorter or equal in length, start by considering gen itself.
    # If gen is longer, truncate it.
    if len(gen) > max_len:
        candidate = gen[:max_len]
    else:
        candidate = gen

    # If candidate <= gen, we can return candidate immediately.
    if cmp_generation(candidate, gen) <= 0:
        return candidate

    # Otherwise, we need to try to decrement candidate to find a suitable generation.
    # We'll try a simple heuristic:
    # - Starting from the end, try to decrement the last element until it is less than or equal.
    # This approach assumes integer increments. If your generation increments differently,
    # you may need a more sophisticated approach.

    candidate_list = list(candidate)

    # Try to decrement from the last element downward until we find a suitable generation or fail.
    for i in reversed(range(len(candidate_list))):
        # Decrement candidate_list[i] down to 0, checking each time
        original_val = candidate_list[i]
        for val in range(original_val, -1, -1):
            candidate_list[i] = val
            clipped_candidate = tuple(candidate_list)
            if cmp_generation(clipped_candidate, gen) <= 0:
                return clipped_candidate

        # If we can't find anything by decrementing this element,
        # try removing it if possible (making the tuple shorter).
        # Making the tuple shorter makes it "greater" according to cmp_generation rules,
        # so shorter won't help us if we need <= gen. If shorter is always greater,
        # this approach won't find a solution that way. But let's try anyway.
        candidate_list = candidate_list[:i]
        if not candidate_list:
            # no generation left
            return None

        # Check if shorter candidate is <= gen
        clipped_candidate = tuple(candidate_list)
        if cmp_generation(clipped_candidate, gen) <= 0:
            return clipped_candidate

    # If we exhaust all attempts, return None
    return None


def parent_generation(gen: Generation) -> Generation:
    """
    Return the parent generation of the given generation tuple.
    
    The parent generation is created by removing the last element of the
    generation tuple, representing moving up one run level in the hierarchy.
    
    Args:
        gen: The generation tuple to find the parent of
        
    Returns:
        The parent generation, or None if gen is None or empty
        
    Examples:
        >>> parent_generation(None)
        None
        >>> parent_generation((1, 2, 3))
        (1, 2)
        >>> parent_generation((1,))
        ()
        >>> parent_generation(())
        None
    """
    if gen is None:
        return None
    elif len(gen) == 0:
        return None
    elif len(gen) == 1:
        return tuple()
    else:
        return tuple(list(gen)[:-1])


def stitched_generation(gen: Generation, stitch_0: int) -> Generation:
    """
    Apply a "stitch" adjustment to a generation tuple.
    
    This function is used for cycle breaking in dataflow graphs. It adds the
    stitch value to the first element of the generation tuple, which affects
    how nodes in a cycle will be scheduled.
    
    Args:
        gen: The generation tuple to stitch
        stitch_0: Value to add to the first element
        
    Returns:
        The modified generation tuple, or a special value for None input
        
    Examples:
        >>> stitched_generation(None, 0)
        None
        >>> stitched_generation(None, 1)
        (0,)
        >>> stitched_generation((1, 2), 3)
        (4, 2)
        >>> stitched_generation((), 5)
        ()
    """
    if gen is None:
        if stitch_0 != 0:
            return (stitch_0 - 1,)
        else:
            return None

    if gen == ():
        return gen
    list_gen = list(gen)
    list_gen[0] += stitch_0
    return tuple(list_gen)
