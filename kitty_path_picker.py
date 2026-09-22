"""Choose an on-screen file path and open it in Micro in the current Kitty tab.

Unlike Kitty's built-in hints overlay, this picker renders ``[00]`` through
``[99]`` *before* a path instead of replacing characters in it.  It deliberately
uses a short pause to disambiguate ``2`` (path 02) from ``12`` (path 12).
"""

import json
import os
import re
import select
import shlex
import sys
import termios
import time
import tty

from kittens.tui.handler import result_handler


_SEGMENT = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
_PATH = rf"(?:/(?:{_SEGMENT})(?:/{_SEGMENT})*|~/(?:{_SEGMENT})(?:/{_SEGMENT})*|(?:\./|\.\./)?{_SEGMENT}(?:/{_SEGMENT})*)"
_CANDIDATE = re.compile(
    rf"(?<![A-Za-z0-9_./~-])(?P<path>{_PATH})(?::(?P<line>[1-9][0-9]*)(?::(?P<column>[1-9][0-9]*))?)?"
)
_MOUSE = re.compile(r"\x1b\[<(?P<button>\d+);(?P<x>\d+);(?P<y>\d+)(?P<kind>[Mm])")
_SINGLE_DIGIT_DELAY = 0.45


def _absolute_file(path, cwd):
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    path = os.path.normpath(path)
    return path if os.path.isfile(path) else None


def _paths_by_line(screen, cwd):
    """Return the first 100 existing-file paths, retaining screen positions."""
    paths = []
    by_line = []
    for line_number, line in enumerate(screen.splitlines()):
        line_paths = []
        for match in _CANDIDATE.finditer(line):
            absolute_path = _absolute_file(match.group("path"), cwd)
            if absolute_path is None:
                continue
            path = {
                "index": len(paths),
                "start": match.start(),
                "end": match.end(),
                "absolute_path": absolute_path,
                "line": match.group("line") or "",
                "column": match.group("column") or "",
                "screen_line": line_number,
            }
            paths.append(path)
            line_paths.append(path)
            if len(paths) == 100:
                break
        by_line.append(line_paths)
        if len(paths) == 100:
            by_line.extend([] for _ in screen.splitlines()[line_number + 1 :])
            break
    return paths, by_line


def _style(text, code):
    return f"\x1b[{code}m{text}\x1b[0m"


def _render_line(line, paths, width):
    """Render a line and return visible click ranges as (left, right, index)."""
    output = []
    click_ranges = []
    source_position = 0
    column = 0

    def add(text, style=None, path_index=None):
        nonlocal column
        if column >= width or not text:
            return
        visible = text[: width - column]
        left = column
        column += len(visible)
        output.append(_style(visible, style) if style else visible)
        if path_index is not None:
            click_ranges.append((left, column, path_index))

    for path in paths:
        add(line[source_position : path["start"]])
        add(f"[{path['index']:02d}]", "30;46;1", path["index"])
        add(line[path["start"] : path["end"]], "94;1", path["index"])
        source_position = path["end"]
    add(line[source_position:])
    return "".join(output), click_ranges


def _draw(lines, paths_by_line, rows, columns, typed, message=""):
    """Redraw the source screen, with labels inserted before clickable paths."""
    sys.stdout.write("\x1b[H\x1b[2J")
    click_ranges = {}
    for row in range(rows):
        line = lines[row] if row < len(lines) else ""
        line_paths = paths_by_line[row] if row < len(paths_by_line) else ()
        rendered, ranges = _render_line(line, line_paths, columns)
        sys.stdout.write(rendered)
        if row != rows - 1:
            sys.stdout.write("\r\n")
        if ranges:
            click_ranges[row + 1] = ranges
    hint = "Path picker"
    if typed:
        hint += f": {typed}"
    if message:
        hint += f" — {message}"
    sys.stdout.write(f"\x1b]2;{hint}\x07")
    sys.stdout.flush()
    return click_ranges


def _selected_path(paths, typed):
    if not typed:
        return None
    index = int(typed)
    return paths[index] if index < len(paths) else None


def _run_picker(screen):
    # Kitty uses NULs to represent wrapped screen lines. They do not consume a
    # terminal cell, so remove them before calculating draw and click positions.
    lines = screen.replace("\0", "").splitlines()
    paths, paths_by_line = _paths_by_line(screen.replace("\0", ""), os.getcwd())
    if not paths:
        return ""

    size = os.get_terminal_size()
    rows, columns = size.lines, size.columns
    typed = ""
    message = "Type 00–99, or click a path"
    click_ranges = _draw(lines, paths_by_line, rows, columns, typed, message)
    message = ""
    deadline = None
    pending = ""

    with open("/dev/tty", "rb+", buffering=0) as terminal:
        original_mode = termios.tcgetattr(terminal.fileno())
        try:
            tty.setraw(terminal.fileno())
            sys.stdout.write("\x1b[?1000h\x1b[?1006h\x1b[?25l")
            sys.stdout.flush()
            while True:
                timeout = None if deadline is None else max(0, deadline - time.monotonic())
                readable, _, _ = select.select([terminal], [], [], timeout)
                if not readable:
                    selected = _selected_path(paths, typed)
                    if selected is not None:
                        return json.dumps(selected)
                    deadline = None
                    continue

                pending += os.read(terminal.fileno(), 64).decode("utf-8", "ignore")
                while pending:
                    mouse = _MOUSE.match(pending)
                    if mouse:
                        pending = pending[mouse.end() :]
                        if mouse.group("kind") == "M" and int(mouse.group("button")) == 0:
                            for left, right, index in click_ranges.get(int(mouse.group("y")), ()):
                                if left <= int(mouse.group("x")) - 1 < right:
                                    return json.dumps(paths[index])
                        continue
                    if pending.startswith("\x1b["):
                        break
                    char, pending = pending[0], pending[1:]
                    if char == "\x1b":
                        return ""
                    if char in "\r\n":
                        selected = _selected_path(paths, typed)
                        if selected is not None:
                            return json.dumps(selected)
                        message = "No matching path"
                    elif char in "\x7f\b":
                        typed = typed[:-1]
                        deadline = time.monotonic() + _SINGLE_DIGIT_DELAY if typed else None
                    elif char.isdigit() and len(typed) < 2:
                        typed += char
                        selected = _selected_path(paths, typed)
                        if len(typed) == 2:
                            if selected is not None:
                                return json.dumps(selected)
                            message = "No matching path"
                            typed = ""
                            deadline = None
                        else:
                            deadline = time.monotonic() + _SINGLE_DIGIT_DELAY
                    else:
                        continue
                    click_ranges = _draw(lines, paths_by_line, rows, columns, typed, message)
                    message = ""
        finally:
            termios.tcsetattr(terminal.fileno(), termios.TCSADRAIN, original_mode)
            sys.stdout.write("\x1b[?1000l\x1b[?1006l\x1b[?25h\x1b[0m")
            sys.stdout.flush()


def main(_args):
    return _run_picker(sys.stdin.read())


def _is_micro(window):
    child = getattr(window, "child", None)
    if child is None:
        return False
    command_lines = [getattr(child, "cmdline", ())]
    command_lines.extend(
        process.get("cmdline") or () for process in getattr(child, "foreground_processes", ())
    )
    return any(
        command_line and os.path.basename(command_line[0]) == "micro"
        for command_line in command_lines
    )


def _first_micro_in_same_tab(source_window):
    tab = source_window.tabref()
    if tab is None:
        return None
    return next((window for window in tab if _is_micro(window)), None)


def _remote(boss, source_window, *args):
    boss.call_remote_control(source_window, args)


@result_handler(type_of_input="screen")
def handle_result(_args, result, target_window_id, boss):
    if not result:
        return
    try:
        selected = json.loads(result)
    except (TypeError, ValueError):
        return

    source_window = boss.window_id_map.get(target_window_id)
    if source_window is None:
        return
    micro_window = _first_micro_in_same_tab(source_window)
    if micro_window is None:
        command = ["/home/koen/external/micro/micro", selected["absolute_path"]]
        if selected["line"]:
            position = selected["line"]
            if selected["column"]:
                position += ":" + selected["column"]
            command.append("+" + position)
        _remote(
            boss,
            source_window,
            "launch",
            "--type",
            "window",
            "--match",
            f"window_id:{source_window.id}",
            "--source-window",
            f"id:{source_window.id}",
            "--cwd",
            "current",
            *command,
        )
        return

    match_window = f"id:{micro_window.id}"
    _remote(boss, source_window, "send-key", "--match", match_window, "ctrl+e")
    _remote(
        boss,
        source_window,
        "send-text",
        "--match",
        match_window,
        "open " + shlex.quote(selected["absolute_path"]) + "\r",
    )
    if selected["line"]:
        position = selected["line"]
        if selected["column"]:
            position += ":" + selected["column"]
        _remote(boss, source_window, "send-key", "--match", match_window, "ctrl+e")
        _remote(boss, source_window, "send-text", "--match", match_window, "goto " + position + "\r")
    _remote(boss, source_window, "focus-window", "--match", match_window)
