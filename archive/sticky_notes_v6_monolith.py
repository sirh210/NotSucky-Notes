"""
Sticky Notes v6 - Resizable UI + Drag-to-Reorder Grid + Local 'notes' Folder
Usage: python sticky_notes_resizable.py
Requires: pip install PySide6 pyside6-addons (optional, for PDF export)
"""

import os
import sys
import json
import uuid
from datetime import datetime

# Qt imports
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QTimer, QMimeData, Signal
from PySide6.QtGui import QFont, QColor

# ─── Configuration ────────────────────────────────────────────────
NOTES_DIR = os.path.join(os.getcwd(), "notes")  # Saves in local "notes" folder
AUTO_SAVE_INTERVAL_MS = 30_000

COLORS = {
    "Yellow":   {"bg": "#FFF9C4", "fg": "#F57F17", "accent": "#FFD600"},
    "Green":    {"bg": "#C8E6C9", "fg": "#2E7D32", "accent": "#4CAF50"},
    "Blue":     {"bg": "#BBDEFB", "fg": "#1565C0", "accent": "#2196F3"},
    "Pink":     {"bg": "#F8BBD0", "fg": "#AD1457", "accent": "#E91E63"},
    "Orange":   {"bg": "#FFE0B2", "fg": "#E65100", "accent": "#FF9800"},
    "Purple":   {"bg": "#E1BEE7", "fg": "#6A1B9A", "accent": "#9C27B0"},
}

DEFAULT_COLOR = "Yellow"


# ─── Note Data Model ──────────────────────────────────────────────
class Note:
    def __init__(self, title="", content="", color=DEFAULT_COLOR):
        self.id = str(uuid.uuid4())[:8]
        self.title = title or f"Note {uuid.uuid4().hex[:6]}"
        self.content = content
        self.color = color
        self.x = None
        self.y = None
        self.minimized = False
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

    def to_dict(self):
        return {**vars(self), "created_at": self.created_at, "updated_at": self.updated_at}

    @classmethod
    def from_dict(cls, data):
        note = cls(title=data.get("title", ""), content=data.get("content", ""), color=data.get("color", DEFAULT_COLOR))
        for k in ["id", "x", "y", "minimized"]: setattr(note, k, data.get(k))
        note.created_at = data.get("created_at", datetime.now().isoformat())
        note.updated_at = data.get("updated_at", datetime.now().isoformat())
        return note

    @property
    def file_path(self):
        os.makedirs(NOTES_DIR, exist_ok=True)
        return os.path.join(NOTES_DIR, f"{self.id}.json")


class FileManager:
    @staticmethod
    def ensure_dir():
        os.makedirs(NOTES_DIR, exist_ok=True)

    @classmethod
    def save_note(cls, note):
        cls.ensure_dir()
        with open(note.file_path, "w", encoding="utf-8") as f:
            json.dump(vars(note), f, indent=2, ensure_ascii=False)

    @classmethod
    def delete_note(cls, note):
        p = os.path.join(NOTES_DIR, f"{note.id}.json")
        if os.path.exists(p): os.remove(p)

    @classmethod
    def load_notes(cls) -> list[Note]:
        cls.ensure_dir()
        notes = []
        for fn in os.listdir(NOTES_DIR):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(NOTES_DIR, fn), "r", encoding="utf-8") as f:
                        notes.append(Note.from_dict(json.load(f)))
                except Exception: continue
        return notes


# ─── Individual Note Window ──────────────────────────────────────
class NoteWidget(QWidget):
    close_requested = Signal(str)
    minimize_requested = Signal(str)

    def __init__(self, note: Note, dashboard: 'DashboardWindow'):
        super().__init__()
        self.note = note
        self.dashboard = dashboard
        self._drag_pos = None

        scheme = COLORS.get(note.color, COLORS[DEFAULT_COLOR])
        self.setStyleSheet(f"""
            QWidget {{ background-color: {scheme['bg']}; border-radius: 8px; }}
            QTextEdit {{ background-color: transparent; border: none; font-family: 'Segoe UI'; font-size: 14px; color: {scheme['fg']}; }}
        """)

        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        title_bar = QWidget()
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet(f"background-color: {scheme['accent']}; border-top-left-radius: 8px; border-top-right-radius: 8px;")

        h_layout = QHBoxLayout(title_bar)
        h_layout.setContentsMargins(8, 4, 8, 4)

        self.title_input = QLineEdit(note.title)
        self.title_input.setStyleSheet("background: transparent; border: none; color: #333; font-weight: bold;")
        self.title_input.textChanged.connect(self._auto_save)
        h_layout.addWidget(self.title_input)

        for name, s in COLORS.items():
            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"background-color: {s['bg']}; border-radius: 6px; border: 1px solid #555;")
            dot.setCursor(Qt.PointingHandCursor)
            dot.mousePressEvent = lambda e, c=name: self._change_color(c) if s["bg"] != scheme["bg"] else None
            h_layout.addWidget(dot)

        min_btn = QLabel("─")
        min_btn.setStyleSheet("background: transparent; color: #333; font-size: 14px; border-radius: 4px;")
        min_btn.setCursor(Qt.PointingHandCursor)
        min_btn.mousePressEvent = lambda e: self.minimize_requested.emit(self.note.id)

        close_btn = QLabel("✕")
        close_btn.setStyleSheet("background: transparent; color: #c0392b; font-size: 14px; border-radius: 4px;")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.mousePressEvent = lambda e: self.close_requested.emit(self.note.id)

        h_layout.addStretch()
        h_layout.addWidget(min_btn)
        h_layout.addWidget(close_btn)
        main_layout.addWidget(title_bar)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(note.content)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.text_edit.textChanged.connect(self._on_text_changed)
        main_layout.addWidget(self.text_edit, 1)

        status_bar = QWidget()
        status_bar.setFixedHeight(20)
        status_bar.setStyleSheet(f"background-color: {scheme['accent']}; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;")

        self.status_label = QLabel(f"{len(note.content)} chars")
        self.status_label.setStyleSheet("color: #555; font-size: 10px; padding: 2px;")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(6, 0, 6, 0)
        status_layout.addWidget(self.status_label)
        main_layout.addWidget(status_bar)

        if note.x is not None and note.y is not None: self.move(note.x, note.y)
        else: self.move(50 + (hash(self.note.id) % 400), 30 + (hash(self.note.id)//200)%300)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.childAt(event.pos()) in [self.text_edit]:
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.LeftButton) and self._drag_pos:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.note.x, self.note.y = self.x(), self.y()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def _on_text_changed(self):
        self.status_label.setText(f"{len(self.text_edit.toPlainText())} chars")
        QTimer.singleShot(1000, lambda: self._auto_save())

    def _auto_save(self):
        self.note.title = self.title_input.text()
        self.note.content = self.text_edit.toPlainText().rstrip("\n")
        self.note.updated_at = datetime.now().isoformat()
        FileManager.save_note(self.note)

    def _change_color(self, color_name):
        if color_name == self.note.color: return
        self.note.color = color_name
        scheme = COLORS[color_name]
        self.setStyleSheet(f"""
            QWidget {{ background-color: {scheme['bg']}; border-radius: 8px; }}
            QTextEdit {{ background-color: transparent; border: none; font-family: 'Segoe UI'; font-size: 14px; color: {scheme['fg']}; }}
        """)


# ─── Dashboard (Fully Resizable + Drag-to-Reorder Grid) ──────────
class DashboardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("📝 NotSucky Notes")
        self.resize(950, 680)  # Initial size, fully resizable
        self.setStyleSheet("QMainWindow { background-color: #2D2D30; } QWidget#central { background-color: transparent; }")

        self.notes = {}
        self.minimized_ids = []
        self.search_term = ""

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(65)
        header.setStyleSheet("background-color: #1E1E22;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 10, 20, 10)

        title_lbl = QLabel("📝 NotSucky Notes")
        title_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #fff;")
        path_lbl = QLabel(f"Saved to: {NOTES_DIR}")
        path_lbl.setStyleSheet("font-size: 9px; color: #888; margin-top: 4px;")

        left_widget = QWidget()
        l_layout = QVBoxLayout(left_widget)
        l_layout.addWidget(title_lbl)
        l_layout.addWidget(path_lbl, alignment=Qt.AlignBottom)
        h_layout.addWidget(left_widget, alignment=Qt.AlignLeft | Qt.AlignVCenter)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Filter notes...")
        self.search_input.setFixedWidth(250)
        self.search_input.setStyleSheet("""background-color: #3E3E42; color: #ccc; border-radius: 6px; padding: 8px; font-size: 12px;""")
        self.search_input.textChanged.connect(self._refresh_grid)
        h_layout.addWidget(self.search_input, alignment=Qt.AlignCenter)

        new_btn = QPushButton("+ New Note")
        new_btn.setFixedSize(130, 36)
        new_btn.setStyleSheet("""QPushButton { background-color: #4CAF50; color: white; border-radius: 6px; font-weight: bold; } QPushButton:hover { background-color: #45a049; }""")
        new_btn.clicked.connect(self.create_note)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFixedSize(100, 32)
        refresh_btn.setStyleSheet("""QPushButton { background-color: #3E3E42; color: #ccc; border-radius: 6px; } QPushButton:hover { background-color: #50505A; }""")
        refresh_btn.clicked.connect(self._refresh_grid)

        btns = QWidget()
        b_layout = QHBoxLayout(btns)
        b_layout.setContentsMargins(0, 0, 0, 0)
        b_layout.addWidget(refresh_btn)
        b_layout.addWidget(new_btn)
        h_layout.addWidget(btns, alignment=Qt.AlignRight | Qt.AlignVCenter)

        main_layout.addWidget(header)

        # Resizable Grid Container (scrollable)
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.grid_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.grid_scroll.setStyleSheet("background: transparent; border: none;")

        self.grid_frame = QWidget()
        self.grid_layout = QGridLayout(self.grid_frame)
        self.grid_layout.setContentsMargins(20, 15, 20, 65)
        self.grid_layout.setHorizontalSpacing(16)
        self.grid_layout.setVerticalSpacing(16)

        # Make all columns stretch equally for resizing
        for i in range(4): self.grid_layout.setColumnStretch(i, 1)

        self.grid_scroll.setWidget(self.grid_frame)
        main_layout.addWidget(self.grid_scroll, 1)

        # Minimized Dock (scrollable, resizable)
        self.dock_frame = QWidget()
        self.dock_frame.setFixedHeight(48)
        self.dock_frame.setStyleSheet("background-color: #1E1E22; border-top: 1px solid #3E3E42;")

        dock_layout = QHBoxLayout(self.dock_frame)
        dock_layout.setContentsMargins(15, 6, 15, 6)

        self.dock_scroll = QScrollArea()
        self.dock_scroll.setWidgetResizable(True)
        self.dock_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.dock_scroll.setStyleSheet("background: transparent; border: none;")

        self.dock_content = QWidget()
        self.dock_layout_inner = QHBoxLayout(self.dock_content)
        self.dock_layout_inner.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.dock_layout_inner.setContentsMargins(0, 0, 15, 0)
        self.dock_scroll.setWidget(self.dock_content)

        dock_layout.addWidget(self.dock_scroll)
        main_layout.addWidget(self.dock_frame)

        # Auto-save timer
        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self._auto_save_loop)
        self.auto_save_timer.start(AUTO_SAVE_INTERVAL_MS)

        self._load_notes()

    def _refresh_grid(self):
        for i in reversed(range(self.grid_layout.count())):
            w = self.grid_layout.itemAt(i).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        notes = FileManager.load_notes()
        query = self.search_input.text().strip().lower()
        filtered = [n for n in notes if not query or query in n.title.lower() or query in n.content.lower()]
        filtered.sort(key=lambda n: n.updated_at or "", reverse=True)

        if not filtered:
            lbl = QLabel("No matching notes.\nCreate one with '+ New Note'")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #666; font-size: 14px; background-color: transparent;")
            self.grid_layout.addWidget(lbl, 0, 0, 1, 4)
            return

        row = col = 0
        for note in filtered:
            card = self._create_note_card(note)
            self.grid_layout.addWidget(card, row, col)
            col += 1
            if col >= 4: col = 0; row += 1

    def _create_note_card(self, note):
        scheme = COLORS.get(note.color, COLORS[DEFAULT_COLOR])
        card = QWidget()

        # Flexible sizing for resizable UI
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card.setMinimumSize(180, 150)
        card.setStyleSheet(f"background-color: {scheme['bg']}; border-radius: 8px;")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        title_lbl = QLabel(note.title or "Untitled")
        title_lbl.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {scheme['fg']};")
        layout.addWidget(title_lbl)

        preview = note.content[:80].replace("\n", " ")
        lbl = QLabel(preview)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"font-size: 11px; color: #555;")
        layout.addWidget(lbl, stretch=1)

        meta = f"[{note.id}] | {len(note.content)} chars" + (" ⏸️" if note.minimized else "")
        status = QLabel(meta)
        status.setStyleSheet("font-size: 9px; color: #888;")
        layout.addWidget(status)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setStyleSheet(f"background-color: transparent; color: #c0392b; font-size: 14px; border: none; border-radius: 10px;")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(lambda _, n=note: self.delete_note(n))
        layout.addWidget(del_btn, alignment=Qt.AlignRight)

        # Drag & Drop Setup for Reordering
        card.setAcceptDrops(True)
        card.mousePressEvent = lambda e, c=card, n=note: self._start_drag(e, c, n)
        card.mouseMoveEvent = lambda e: self._drag_move(e)
        card.dragEnterEvent = lambda e: self._drag_enter(e)
        card.dropEvent = lambda e: self._drop_on_card(e, card)

        card.open_note_ref = note  # Store reference for click handling
        card.mouseDoubleClickEvent = lambda e, n=note: self.open_note(n)

        return card

    def _start_drag(self, event, widget, note):
        if event.button() != Qt.LeftButton or isinstance(event.widget(), (QPushButton, QLineEdit)): return
        drag = QDrag(widget)
        mime = QMimeData()
        # Store current grid position for swapping
        row, col = self.grid_layout.rowWidget(widget), self.grid_layout.columnWidget(widget)
        mime.setData("application/x-note-pos", f"{row},{col}".encode())
        mime.setUrls([note.file_path])
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)

    def _drag_move(self, event):
        if event.buttons() & Qt.LeftButton:
            event.acceptProposedAction()

    def _drag_enter(self, event):
        if event.mimeData().hasFormat("application/x-note-pos"):
            event.acceptProposedAction()

    def _drop_on_card(self, event, target_widget):
        if not event.mimeData().hasFormat("application/x-note-pos"): return

        source_data = str(event.mimeData.data("application/x-note-pos"), encoding="utf-8")
        src_row, src_col = map(int, source_data.split(","))

        # Find source widget
        widgets_in_grid = [self.grid_layout.itemAtPosition(r, c).widget()
                           for r in range(self.grid_layout.rowCount())
                           for c in range(self.grid_layout.columnCount())]
        source_widget = None
        for w in widgets_in_grid:
            if w and self.grid_layout.rowWidget(w) == src_row and self.grid_layout.columnWidget(w) == src_col:
                source_widget = w
                break

        if not source_widget or source_widget == target_widget: return

        # Swap positions in layout
        tgt_row, tgt_col = self.grid_layout.rowWidget(target_widget), self.grid_layout.columnWidget(target_widget)

        self.grid_layout.addWidget(source_widget, tgt_row, tgt_col)
        self.grid_layout.addWidget(target_widget, src_row, src_col)

        event.acceptProposedAction()

    def open_note(self, note):
        if note.id in self.notes and self.notes[note.id].isVisible():
            self.notes[note.id].raise_()
            self.notes[note.id].activateWindow()
            return

        if note.minimized and note.id in self.minimized_ids:
            self.minimized_ids.remove(note.id)
            self._update_dock_ui()

        nw = NoteWidget(note, self)
        nw.close_requested.connect(self.close_note)
        nw.minimize_requested.connect(self.minimize_note)

        self.notes[note.id] = nw
        nw.show()

    def close_note(self, note_id):
        if note_id in self.notes:
            widget = self.notes.pop(note_id)
            widget.close()
            if note_id in self.minimized_ids:
                self.minimized_ids.remove(note_id)
                self._update_dock_ui()
            self._refresh_grid()

    def minimize_note(self, note_id):
        if note_id in self.notes:
            widget = self.notes[note_id]
            widget.note.minimized = True
            FileManager.save_note(widget.note)
            if note_id not in self.minimized_ids:
                self.minimized_ids.append(note_id)
            widget.hide()
            self._update_dock_ui()

    def restore_note(self, note_id):
        if note_id in self.minimized_ids:
            self.minimized_ids.remove(note_id)
            self._update_dock_ui()

            notes = FileManager.load_notes()
            restored_note = next((n for n in notes if n.id == note_id), None)
            if restored_note: self.open_note(restored_note)

    def _update_dock_ui(self):
        while self.dock_layout_inner.count():
            w = self.dock_layout_inner.takeAt(0).widget()
            if w: w.deleteLater()

        for nid in self.minimized_ids:
            notes = FileManager.load_notes()
            note = next((n for n in notes if n.id == nid), None)
            if not note: continue

            scheme = COLORS.get(note.color, COLORS[DEFAULT_COLOR])
            btn = QPushButton(f"📝 {note.title or 'Untitled'}")
            btn.setFixedWidth(140)
            btn.setStyleSheet(f"""background-color: {scheme['accent']}; color: #222; border-radius: 6px; font-size: 11px; padding: 4px 8px; margin-right: 4px;""")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, nid=nid: self.restore_note(nid))
            self.dock_layout_inner.addWidget(btn)

    def delete_note(self, note):
        reply = QMessageBox.question(self, "Delete Note", f"Delete '{note.title or 'Untitled'}' permanently?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            FileManager.delete_note(note)

            if note.id in self.notes and self.notes[note.id].isVisible():
                self.close_note(note.id)
            elif note.id in self.minimized_ids:
                self.minimized_ids.remove(note.id)
                self._update_dock_ui()

            self._refresh_grid()

    def create_note(self):
        note = Note()
        FileManager.save_note(note)
        self.open_note(note)

    def _load_notes(self):
        notes = FileManager.load_notes()
        for n in notes:
            if n.minimized and n.id not in self.minimized_ids:
                self.minimized_ids.append(n.id)

        self._update_dock_ui()
        self._refresh_grid()

    def _auto_save_loop(self):
        for nid, widget in list(self.notes.items()):
            if widget.isVisible():
                FileManager.save_note(widget.note)


# ─── Main Entry Point ─────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs(NOTES_DIR, exist_ok=True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = DashboardWindow()
    window.show()

    print(f"📝 NotSucky Notes running. Files saved to: {NOTES_DIR}")
    sys.exit(app.exec())
