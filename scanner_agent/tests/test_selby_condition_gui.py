# ruff: noqa: E402
import os
from copy import deepcopy

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from test_selby_gui import window as window
from test_selby_v02 import geometry

from selby_workstation.condition import category_status
from selby_workstation.inspection import validate_group


def test_complete_condition_workflow_and_patch_coordinates(window, tmp_path):
    import json

    import numpy as np
    from PIL import Image

    from selby_workstation.condition import CATEGORIES, current_findings, map_points
    from selby_workstation.inspection import export_report, recover
    from selby_workstation.session import Session

    w, app = window
    # New synthetic evidence; never modify an image already opened by a session.
    rgb = w.session.rgb.copy()
    for x, y in [(100, 100), (450, 100), (450, 598), (100, 598),
                 (250, 100), (450, 300), (250, 598), (100, 300), (250, 300)]:
        rgb[y:y + 6, x:x + 6] = 255
    image = tmp_path / "condition-fixture.bmp"
    Image.fromarray(rgb).save(image)
    w.open_image(image)
    w.operator.setText("AUTOMATED synthetic workflow validation")
    w.sync_fields()
    geometry(w.session)
    validate_group(w.session, "physical")
    w.refresh()
    w.open_condition()
    app.processEvents()
    dialog = w.condition_dialog
    for category_index, category in enumerate(CATEGORIES):
        dialog.tabs.setCurrentIndex(category_index)
        dialog.run()
        findings = current_findings(w.session, category)
        assert findings and all(f["decision"] == "unreviewed" for f in findings)
        for row in range(len(findings)):
            dialog.table.selectRow(row)
            dialog.notes.setText("Synthetic decision exercise; not a real defect assessment")
            for decision in ("confirmed", "reclassified", "rejected"):
                dialog.review(decision)
                assert dialog.selected()["decision"] == decision
        # Exercise dragging in every extracted view, including all eight mappings.
        dialog.draw.setChecked(True)
        dialog.notes.setText("Synthetic manual annotation")
        dialog.kind.setCurrentText("wear")
        for view in dialog.views[category]:
            view.restore(dict(zoom=2, center=(view.image_size / 2).tolist()
                              if isinstance(view.image_size, np.ndarray)
                              else (np.asarray(view.image_size) / 2).tolist()))
            center = np.asarray(view.image_size) / 2
            a, b = center - [3, 3], center + [3, 3]
            start = view.viewportTransform().map(QPointF(*a)).toPoint()
            end = view.viewportTransform().map(QPointF(*b)).toPoint()
            # Qt integer event positions quantize gestures; compare actual mapped pixels.
            expected_a = view.original(QPointF(start))
            expected_b = view.original(QPointF(end))
            expected = map_points(view.matrix, [expected_a,
                [expected_b[0], expected_a[1]], expected_b,
                [expected_a[0], expected_b[1]]])
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
            app.processEvents()
            finding = w.session.data["condition"]["findings"][-1]
            assert finding["origin"] == "manual"
            assert np.asarray(finding["polygon_original"]) == pytest.approx(expected)
        dialog.draw.setChecked(False)
        dialog.complete()
        assert category_status(w.session, category) == "operator_reviewed"
    before = deepcopy(w.session.data["condition"])
    path = w.save_version(tmp_path / "sessions")
    assert Session.reopen(path).data["condition"] == before
    draft = sorted(w.draft_directory.glob("*.json"), key=lambda p: p.stat().st_mtime_ns)[-1]
    assert recover(draft).data["condition"] == before
    exported = export_report(w.session, tmp_path / "exports")
    value = json.loads(exported.read_text(encoding="utf-8"))
    assert value["kind"] == "selby_inspection_diagnostic"
    assert exported.name.startswith("inspection-")
    assert value["inspection"]["condition"] == before
    assert value["automatic_acceptance"] is False
    assert value["review_status"] == "review_required"
    assert exported.with_suffix(".md").read_text(encoding="utf-8").startswith(
        "# SELBY inspection diagnostic")
    dialog.close()


def test_condition_four_views_manual_drag_review_history_and_save(window, tmp_path):
    w, app = window
    w.operator.setText("Condition GUI reviewer")
    w.sync_fields()
    geometry(w.session, 6)
    validate_group(w.session, "physical")
    w.refresh()
    w.open_condition()
    app.processEvents()
    dialog = w.condition_dialog
    assert len(dialog.views["corners"]) == 4 and len(dialog.views["edges"]) == 4
    dialog.tabs.setCurrentIndex(2)
    dialog.notes.setText("Visible surface mark entered manually")
    dialog.kind.setCurrentText("scratch")
    dialog.draw.setChecked(True)
    view = dialog.views["surface"][0]
    start = view.viewportTransform().map(QPointF(200, 250)).toPoint()
    end = view.viewportTransform().map(QPointF(230, 270)).toPoint()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    app.processEvents()
    assert len(w.session.data["condition"]["findings"]) == 1
    finding = deepcopy(w.session.data["condition"]["findings"][0])
    assert finding["decision"] == "confirmed" and finding["type"] == "scratch"
    dialog.undo(-1)
    assert "condition" not in w.session.data
    dialog.undo(1)
    assert w.session.data["condition"]["findings"] == [finding]
    dialog.table.selectRow(0)
    dialog.notes.setText("Printed texture, not a scratch")
    dialog.kind.setCurrentText("artwork_or_texture")
    dialog.review("reclassified")
    assert w.session.data["condition"]["findings"][0]["decision"] == "reclassified"
    dialog.complete()
    assert category_status(w.session, "surface") == "operator_reviewed"
    path = w.save_version(tmp_path / "versions")
    dialog.close()
    w.open_session(path)
    assert w.session.data["condition"]["findings"][0]["type"] == "artwork_or_texture"
    assert list(w.draft_directory.glob("*.json"))


def test_zoom_sync_and_manual_surface_without_boundaries(window):
    w, app = window
    w.operator.setText("Condition reviewer")
    w.sync_fields()
    w.open_condition()
    app.processEvents()
    dialog = w.condition_dialog
    assert not dialog.views["corners"] and not dialog.views["edges"]
    dialog.tabs.setCurrentIndex(2)
    assert dialog.views["surface"][0].image_size == (560, 720)
    dialog.close()
    geometry(w.session)
    validate_group(w.session, "physical")
    w.refresh()
    w.open_condition()
    app.processEvents()
    dialog = w.condition_dialog
    first = dialog.views["corners"][0]
    first.zoom(2)
    dialog.synchronize(first)
    assert all(
        v.transform().m11() == pytest.approx(first.transform().m11())
        for v in dialog.views["corners"]
    )
    dialog.overlay.setChecked(False)
    assert not any(v.show_findings for views in dialog.views.values() for v in views)
    dialog.close()
