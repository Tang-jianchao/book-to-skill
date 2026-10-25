#!/usr/bin/env python3
"""Fallback pack helper: build a notes skeleton or a private RAG corpus."""

import os
import sys

# Keep a deployed skill directory clean: importing the package below would
# otherwise write __pycache__/*.pyc beside the sources. Must be set BEFORE
# `book_to_skill` is imported.
if __name__ == "__main__":
    sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from book_to_skill.packs import main

if __name__ == "__main__":
    raise SystemExit(main())
