"""Helpers for argparse CLIs with global flags before or after subcommands."""

from __future__ import annotations

import argparse
from collections.abc import Iterable


def flag_present(argv: Iterable[str], flag: str) -> bool:
    prefix = f"{flag}="
    return flag in argv or any(arg.startswith(prefix) for arg in argv)


def apply_parsed_globals(
    args: argparse.Namespace,
    pre: argparse.Namespace,
    argv: list[str],
    names: Iterable[str],
) -> None:
    """Copy globally parsed values onto the subcommand namespace when present in argv."""
    for name in names:
        flag = f"--{name.replace('_', '-')}"
        if flag_present(argv, flag):
            setattr(args, name, getattr(pre, name))
