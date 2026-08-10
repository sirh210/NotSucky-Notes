# Archive

Superseded files, kept only because this project has no version control
history to recover them from. Nothing here is imported, tested, or shipped —
`notsucky*` is the only package included in the distribution.

| File | What it was | Why it is here |
| --- | --- | --- |
| `sticky_notes_v6_monolith.py` | The original single-file "Sticky Notes v6" application, later refactored into the `notsucky/` package. | Fully superseded. It also never ran as written: `QDrag` and `QSizePolicy` were only in scope via `from PySide6.QtWidgets import *`, `QGridLayout.rowWidget()`/`columnWidget()` do not exist, `event.mimeData.data(...)` is missing a call, and `drag.exec_()` is the removed Qt5 spelling — so its drag-to-reorder path raised on first use. |
| `_dump.py`, `_dump.py.tmp` | Throwaway scripts that printed `main.py` to stdout with the encoding forced. | Debugging leftovers, not part of the build. |

Safe to delete once the project is under version control.
