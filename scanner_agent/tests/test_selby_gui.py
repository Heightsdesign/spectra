# ruff: noqa: E402
"""Real Qt event-loop interaction tests with an offscreen Windows rendering surface."""

import os
from copy import deepcopy

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_centering import fixture

from selby_workstation.app import Workstation
from selby_workstation.session import Session


@pytest.fixture
def window(tmp_path):
    application = QApplication.instance() or QApplication([])
    widget = Workstation()
    widget.draft_directory = tmp_path / "drafts"
    widget.show()
    application.processEvents()
    image, physical = fixture(tmp_path)
    widget.open_image(image)
    widget.load_source(physical)
    application.processEvents()
    yield widget, application
    widget.dirty = False
    widget.close()
    application.processEvents()


def test_v02_undo_redo_autosave_recovery_and_face(window, tmp_path):
    w, app = window
    w.operator.setText("V0.2 reviewer")
    w.face.setCurrentText("back")
    w.apply_edit("physical", 0, [[120.125, 115.5], [420.25, 117.75]])
    draft_line = deepcopy(w.session.data["physical"][0])
    w.review(False)
    confirmed = deepcopy(w.session.data["physical"][0])
    w.undo_redo(-1)
    assert w.session.data["physical"][0] == draft_line
    w.undo_redo(1)
    assert w.session.data["physical"][0] == confirmed
    w.autosave_now()
    drafts = list(w.draft_directory.glob("*.json"))
    assert len(drafts) == 1
    w.autosave_now()
    assert len(list(w.draft_directory.glob("*.json"))) == 1
    w.open_recovery(drafts[0])
    assert w.session.data["physical"][0] == confirmed
    assert w.face.currentText() == "back"
    assert "unavailable" in w.measurement.text()
    assert w.operator.text() == "V0.2 reviewer"


def test_draw_confirm_nudge_save_reopen_through_gui(window, tmp_path):
    w, app = window
    w.operator.setText("Qt reviewer")
    w.set_mode("draw")
    points = [[120.0, 115.0], [420.0, 117.0]]
    for point in points:
        pos = w.canvas.viewportTransform().map(QPointF(*point)).toPoint()
        QTest.mouseClick(
            w.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos
        )
    app.processEvents()
    stored = w.session.data["physical"][0]
    assert stored["definition"] == "manual" and stored["line_abc"] is not None
    w.review(False)
    assert w.session.data["physical"][0]["status"] == "annotated"
    w.set_mode("edit")
    w.canvas.setFocus()
    before = np.array(w.session.data["physical"][0]["endpoints"])
    QTest.keyClick(w.canvas, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()
    assert np.allclose(
        np.array(w.session.data["physical"][0]["endpoints"]) - before, [0.1, 0], atol=1e-10
    )
    assert w.session.data["physical"][0]["status"] == "unannotated"
    saved = w.save_version(tmp_path / "versions")
    geometry = w.session.data["physical"][0].copy()
    w.open_session(saved)
    app.processEvents()
    assert w.session.data["physical"][0] == geometry
    assert Session.reopen(saved).data["operator"] == "Qt reviewer"


def test_endpoint_drag_preview_cancel_and_release(window):
    w, app = window
    w.session.edit("physical", 0, [[120, 115], [420, 117]])
    w.refresh()
    w.set_mode("edit")
    before = np.array(w.session.data["physical"][0]["endpoints"])
    start = w.canvas.viewportTransform().map(QPointF(*before[0])).toPoint()
    finish = start + type(start)(20, 5)
    QTest.mousePress(
        w.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start
    )
    QTest.mouseMove(w.canvas.viewport(), finish)
    assert np.array_equal(w.session.data["physical"][0]["endpoints"], before)
    QTest.keyClick(w.canvas, Qt.Key.Key_Escape)
    QTest.mouseRelease(
        w.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, finish
    )
    assert np.array_equal(w.session.data["physical"][0]["endpoints"], before)
    QTest.mousePress(
        w.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start
    )
    QTest.mouseMove(w.canvas.viewport(), finish)
    QTest.mouseRelease(
        w.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, finish
    )
    app.processEvents()
    after = np.array(w.session.data["physical"][0]["endpoints"])
    assert not np.array_equal(after[0], before[0]) and np.array_equal(after[1], before[1])
    QTest.keyClick(w.canvas, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    nudged = np.array(w.session.data["physical"][0]["endpoints"])
    assert np.allclose(nudged[0] - after[0], [0.1, 0], atol=1e-10)
    assert np.array_equal(nudged[1], after[1])


def test_candidate_seed_uncertainty_and_zoom_mapping(window):
    w, app = window
    w.candidate.setCurrentIndex(1)
    w.use_candidate()
    assert w.session.data["physical"][0]["definition"] == "candidate"
    assert w.session.data["physical"][0]["status"] == "unannotated"
    w.session.set_notes("physical", 0, "Two visible transitions")
    w.refresh()
    w.review(True)
    assert w.session.data["physical"][0]["status"] == "ambiguous"
    point = np.array([120.123456789, 200.987654321])
    for factor in [0.25, 1, 4, 16]:
        w.canvas.restore(dict(zoom=factor, center=[280, 350]))
        app.processEvents()
        screen = w.canvas.viewportTransform().map(QPointF(*point))
        assert np.allclose(w.canvas.original(screen), point, atol=1e-10)


def test_pan_changes_view_without_geometry_edits(window):
    w, app = window
    w.canvas.restore(dict(zoom=4, center=[280, 350]))
    app.processEvents()
    before = w.canvas.view_state()
    decisions = deepcopy(w.session.data["physical"])
    start = w.canvas.viewport().rect().center()
    finish = start + type(start)(40, -20)
    QTest.mousePress(
        w.canvas.viewport(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, start
    )
    QTest.mouseMove(w.canvas.viewport(), finish)
    QTest.mouseRelease(
        w.canvas.viewport(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, finish
    )
    app.processEvents()
    assert not np.allclose(w.canvas.view_state()["center"], before["center"])
    assert w.session.data["physical"] == decisions


def test_unfinished_placement_cannot_be_saved_or_confirmed(window, tmp_path, monkeypatch):
    w, app = window
    w.operator.setText("Qt reviewer")
    w.session.edit("physical", 0, [[120, 115], [420, 117]])
    w.refresh()
    w.set_mode("draw")
    point = w.canvas.viewportTransform().map(QPointF(130, 120)).toPoint()
    QTest.mouseClick(
        w.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point
    )
    app.processEvents()
    assert len(w.canvas.pending) == 1
    with pytest.raises(ValueError, match="Finish drawing"):
        w.save_version(tmp_path / "versions")
    monkeypatch.setattr(w, "guard", lambda action: action())
    with pytest.raises(ValueError, match="Finish drawing"):
        w.review(False)
    assert w.session.data["physical"][0]["status"] == "unannotated"
    w.clear_side()
    assert not w.canvas.pending
