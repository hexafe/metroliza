"""Dedicated spawn dispatcher: no recorder, application bootstrap or Qt hooks."""

import multiprocessing

if __name__ == "__main__":
    # PyInstaller's multiprocessing hook also dispatches resource tracking and
    # exits the child after spawn_main. No product imports may precede this.
    multiprocessing.freeze_support()
    raise SystemExit(2)  # A direct invocation is not an application launch.
