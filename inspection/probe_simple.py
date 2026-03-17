"""Probe a specific line: inspect locals, stack, and all suspended tasks."""
import sys
import types
from typing import Any, Callable

TraceFunction = Callable[[types.FrameType, str, Any], Any]

from flowno.core.event_loop import EventLoop
from flowno.core.event_loop.primitives import sleep, spawn

# We'll capture the event loop so we can inspect its task queue
el = EventLoop()

TaskState = str  # "ready" | "sleeping" | "waiting"
SuspendedInfo = tuple[TaskState, object, types.FrameType]


def get_suspended_task_frames(event_loop: EventLoop) -> list[SuspendedInfo]:
    """Peek at the frames of all suspended coroutines in the event loop."""
    frames: list[SuspendedInfo] = []
    # Tasks in the ready queue
    for task_packet in event_loop.tasks:
        task: object = task_packet[0]
        frame: types.FrameType | None = getattr(task, 'gi_frame', None) or getattr(task, 'cr_frame', None)
        if frame:
            frames.append(('ready', task, frame))
    # Tasks sleeping
    for _, task in event_loop.sleeping:
        frame = getattr(task, 'gi_frame', None) or getattr(task, 'cr_frame', None)
        if frame:
            frames.append(('sleeping', task, frame))
    # Tasks waiting on other tasks (join/cancel)
    for _watched_task, waiters in event_loop.watching_task.items():
        for watcher in waiters:
            frame = getattr(watcher, 'gi_frame', None) or getattr(watcher, 'cr_frame', None)
            if frame:
                frames.append(('waiting', watcher, frame))
    return frames


def format_frame(frame: types.FrameType) -> str:
    """Format a single frame for display."""
    code: types.CodeType = frame.f_code
    return f"  {code.co_filename}:{frame.f_lineno} in {code.co_name}"


def format_locals(frame: types.FrameType, skip_dunders: bool = True) -> str:
    """Format local variables, filtering out uninteresting ones."""
    lines: list[str] = []
    for name, value in sorted(frame.f_locals.items()):
        if skip_dunders and name.startswith('__'):
            continue
        r: str = repr(value)
        if len(r) > 80:
            r = r[:77] + "..."
        lines.append(f"    {name} = {r}")
    return '\n'.join(lines)


def format_stack(frame: types.FrameType) -> str:
    """Walk the stack and format each frame."""
    lines: list[str] = []
    f: types.FrameType | None = frame
    while f:
        lines.append(format_frame(f))
        f = f.f_back
    return '\n'.join(lines)


# --- The breakpoint machinery ---

BREAKPOINTS: list[tuple[str, int]] = []
hit_count: int = 0


def add_breakpoint(filename_suffix: str, lineno: int) -> None:
    BREAKPOINTS.append((filename_suffix, lineno))


def trace_calls(frame: types.FrameType, event: str, arg: Any) -> TraceFunction | None:
    """Global trace function. Returns per-line tracer for files we care about."""
    if event == 'call':
        co: types.CodeType = frame.f_code
        for suffix, _ in BREAKPOINTS:
            if co.co_filename.endswith(suffix):
                return trace_lines
    return None


def trace_lines(frame: types.FrameType, event: str, arg: Any) -> TraceFunction | None:
    """Per-line trace function. Fires our probe when we hit a breakpoint."""
    if event != 'line':
        return trace_lines

    co: types.CodeType = frame.f_code
    for suffix, lineno in BREAKPOINTS:
        if co.co_filename.endswith(suffix) and frame.f_lineno == lineno:
            fire_probe(frame)
    return trace_lines


def fire_probe(frame: types.FrameType) -> None:
    global hit_count
    hit_count += 1
    co: types.CodeType = frame.f_code

    print(f"\n{'='*60}")
    print(f"PROBE HIT #{hit_count}: {co.co_filename}:{frame.f_lineno} in {co.co_name}")
    print(f"{'='*60}")

    print(f"\n--- Locals ---")
    print(format_locals(frame))

    print(f"\n--- Call Stack ---")
    print(format_stack(frame))

    print(f"\n--- Other Suspended Tasks ---")
    suspended: list[SuspendedInfo] = get_suspended_task_frames(el)
    if not suspended:
        print("    (none)")
    for state, task, tframe in suspended:
        if tframe is frame:
            continue
        print(f"  [{state}] {task!r}")
        print(f"    suspended at: {format_frame(tframe)}")
        print(f"    locals:")
        print(format_locals(tframe))

    print(f"{'='*60}\n")


# === The program under test ===

async def worker(name: str, delay: float) -> str:
    result = f"hello from {name}"
    await sleep(delay)
    print(f"[{name}] woke up")
    return result

async def main() -> None:
    t1 = await spawn(worker("alice", 0.5))
    t2 = await spawn(worker("bob", 0.1))
    r2 = await t2.join()
    r1 = await t1.join()
    print(f"results: {r1}, {r2}")

# Set a breakpoint on the print line inside worker
add_breakpoint("probe_simple.py", 137)

sys.settrace(trace_calls)
el.run_until_complete(main())
sys.settrace(None)
