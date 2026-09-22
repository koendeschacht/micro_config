"""Open visible file paths in the first Micro pane in the current Kitty tab.

This file is a Kitty ``hints`` custom processor.  It deliberately uses only
the documented custom-processor hooks, so removing the one Kitty key mapping
that invokes it cleanly disables the feature.
"""

import os
import re
import shlex


# Path components in source trees and Python tracebacks.  Paths containing
# spaces are intentionally out of scope for this first version: in terminal
# output they are ambiguous without quotes or hyperlink metadata.
_SEGMENT = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
_PATH = rf"(?:/(?:{_SEGMENT})(?:/{_SEGMENT})*|~/(?:{_SEGMENT})(?:/{_SEGMENT})*|(?:\./|\.\./)?{_SEGMENT}(?:/{_SEGMENT})*)"
_CANDIDATE = re.compile(
    rf"(?<![A-Za-z0-9_./~-])(?P<path>{_PATH})(?::(?P<line>[1-9][0-9]*)(?::(?P<column>[1-9][0-9]*))?)?"
)


def _absolute_file(path, cwd):
    """Return an existing regular file for *path*, resolved from *cwd*."""
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    path = os.path.normpath(path)
    return path if os.path.isfile(path) else None


def _hint_width(index):
    """Return the number of cells Kitty uses for a decimal hint label."""
    return len(str(index))


def _label_start(text, path_start, label_width, previous_mark_end):
    """Reserve preceding separator cells for Kitty's label when possible.

    Kitty draws the hint label by replacing the first cells of a marked range.
    A mark is therefore extended left, but never across a newline or into the
    preceding mark.  The selected path remains in ``groupdict`` unchanged.
    """
    start = path_start
    while (
        start > previous_mark_end
        and path_start - start < label_width
        and text[start - 1] not in "\r\n"
    ):
        start -= 1
    return start


def mark(text, _args, Mark, _extra_cli_args):
    """Mark only file paths visible in the source pane, up to hint 99."""
    cwd = os.getcwd()
    hint_index = 0
    # Character position zero is available until the first mark is emitted.
    # Use -1 here because mark ends are exclusive positions.
    previous_mark_end = -1
    for match in _CANDIDATE.finditer(text):
        path = match.group("path")
        absolute_path = _absolute_file(path, cwd)
        if absolute_path is None:
            continue

        label_start = _label_start(
            text,
            match.start(),
            _hint_width(hint_index),
            previous_mark_end,
        )

        yield Mark(
            hint_index,
            label_start,
            match.end(),
            text[label_start : match.end()],
            {
                "absolute_path": absolute_path,
                "line": match.group("line") or "",
                "column": match.group("column") or "",
            },
        )
        previous_mark_end = match.end()
        hint_index += 1
        if hint_index == 100:
            return


def _is_micro(window):
    """Whether Micro is the foreground process of this Kitty window."""
    child = getattr(window, "child", None)
    if child is None:
        return False

    command_lines = [getattr(child, "cmdline", ())]
    command_lines.extend(
        process.get("cmdline") or () for process in getattr(child, "foreground_processes", ())
    )
    for command_line in command_lines:
        if command_line and os.path.basename(command_line[0]) == "micro":
            return True
    return False


def _first_micro_in_same_tab(source_window):
    tab = source_window.tabref()
    if tab is None:
        return None
    for window in tab:
        if _is_micro(window):
            return window
    return None


def _remote(boss, source_window, *args):
    boss.call_remote_control(source_window, args)


def _show_error(boss, message):
    show_error = getattr(boss, "show_error", None)
    if show_error is not None:
        show_error("Path hints", message)


def handle_result(_args, data, target_window_id, boss, _extra_cli_args, *_unused):
    """Open the chosen path in Micro, then focus its existing Kitty pane."""
    selected = next(
        (
            groupdict
            for match, groupdict in zip(data["match"], data["groupdicts"])
            if match
        ),
        None,
    )
    if selected is None:
        return

    source_window = boss.window_id_map.get(target_window_id)
    if source_window is None:
        return
    micro_window = _first_micro_in_same_tab(source_window)
    if micro_window is None:
        _show_error(boss, "No active Micro instance in this Kitty tab")
        return

    path = selected["absolute_path"]
    match_window = f"id:{micro_window.id}"
    _remote(boss, source_window, "send-key", "--match", match_window, "ctrl+e")
    _remote(
        boss,
        source_window,
        "send-text",
        "--match",
        match_window,
        "open " + shlex.quote(path) + "\r",
    )

    line = selected.get("line")
    if line:
        position = line
        if selected.get("column"):
            position += ":" + selected["column"]
        _remote(boss, source_window, "send-key", "--match", match_window, "ctrl+e")
        _remote(boss, source_window, "send-text", "--match", match_window, "goto " + position + "\r")

    # focus-window exposes a Micro pane that is hidden by Kitty's stack layout
    # as well as focusing it in normal split layouts.  The target is guaranteed
    # to be in the source tab, so this never switches tabs.
    _remote(boss, source_window, "focus-window", "--match", match_window)
