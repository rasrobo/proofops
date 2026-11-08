"""Tests must never prompt and never touch the network.

Several tests call `cli.main()`, which passes through the one-time diagnostics question. Run from an
interactive terminal, that question read the developer's own keystrokes — so the suite could hang, or
silently record a consent decision on the machine running it.
"""
import os

os.environ.setdefault("PROOPS_NO_PROMPT", "1")
