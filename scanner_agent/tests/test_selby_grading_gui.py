# ruff: noqa: E402
"""Qt vertical slice: existing face records through final draft grade and export."""

import json

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QFileDialog, QMessageBox
from test_selby_grading import face_session
from test_selby_gui import window as window

from selby_workstation import grading
from selby_workstation.condition import complete_category, manual_finding
from selby_workstation.session import Session


def test_grading_panel_two_faces_penalty_revision_validation_and_export(
    window, tmp_path, monkeypatch
):
    w, app = window

    def fail(parent, title, message, *args):
        pytest.fail(f"Unexpected workstation warning: {title}: {message}")

    monkeypatch.setattr(QMessageBox, "warning", fail)
    front = face_session(tmp_path / "grading-front", "front")
    back = face_session(tmp_path / "grading-back", "back")
    manual_finding(
        front,
        "edges",
        [[120, 140], [125, 140], [125, 145], [120, 145]],
        "wear",
        "Synthetic grading GUI wear",
    )
    complete_category(front, "edges", "Reviewed synthetic edge wear")
    front_path = front.save(tmp_path / "input-sessions")
    back_path = back.save(tmp_path / "input-sessions")
    w.open_session(front_path)
    w.open_grading()
    app.processEvents()
    d = w.grading_dialog
    assert '"state": "Draft"' in d.result.toPlainText()
    d.card.setText("SYNTHETIC-GUI-CARD")
    d.create()
    d.notes.setText("Same-card front inspection attached")
    d.attach_current()
    assert grading.evaluate(w.session)["state"] == "Incomplete"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(back_path), "JSON"))
    d.notes.setText("Same-card saved back inspection attached")
    d.attach_saved()
    d.table.selectRow(0)
    assert d.penalty.value() == 0 and not d.warranted.isChecked()
    d.notes.setText("Synthetic edge wear warrants one point")
    d.severity.setValue(2)
    d.warranted.setChecked(True)
    d.penalty.setValue(1)
    d.record_penalty()
    d.face.setCurrentText("back")
    d.center_score.setValue(9.5)
    d.notes.setText("Explicit independent back centering assessment")
    d.center_review()
    r = grading.evaluate(w.session)
    assert r["state"] == "Ready for operator review"
    assert r["subgrades"]["edges"] == 9 and r["subgrades"]["centering"] == 9.5
    d.notes.setText("Closer inspection: revise edge penalty to zero")
    d.warranted.setChecked(False)
    d.penalty.setValue(0)
    d.record_penalty()
    assert grading.evaluate(w.session)["subgrades"]["edges"] == 10
    d.undo(-1)
    assert grading.evaluate(w.session)["subgrades"]["edges"] == 9
    d.undo(1)
    assert grading.evaluate(w.session)["subgrades"]["edges"] == 10
    d.attest.setChecked(True)
    d.notes.setText("Same physical card; reviewed both sides and damage deduplication")
    d.validate()
    assert grading.evaluate(w.session)["state"] == "Human validated"
    assert grading.evaluate(w.session)["final_grade"] == 9
    save_dir = tmp_path / "graded-sessions"
    save_dir.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(save_dir))
    w.choose_save()
    saved = next(save_dir.glob("*.json"))
    assert Session.reopen(saved).data["saved_grading_diagnostic"]["final_grade"] == 9
    export_dir = tmp_path / "graded-exports"
    export_dir.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(export_dir))
    w.choose_export()
    exported = json.loads(next(export_dir.glob("*.json")).read_text())
    assert exported["grading"]["final_grade"] == 9
    assert not exported["automatic_acceptance"]
    assert exported["inspection"]["grading"]["working"]["faces"]["back"]["saved_path"] == str(
        back_path
    )
    d.close()
    w.open_session(saved)
    w.open_grading()
    assert '"state": "Human validated"' in w.grading_dialog.result.toPlainText()
    w.grading_dialog.close()


def test_viewing_predictions_after_grading_does_not_invalidate_decision(window, tmp_path):
    w, app = window
    front = face_session(tmp_path / "engine-front", "front")
    back = face_session(tmp_path / "engine-back", "back")
    assert not front.data["prediction_exposure"]
    grading.initialize(front, "SYNTHETIC-ENGINE-TO-GUI")
    grading.attach_face(front, front, "Front engineering fixture")
    grading.attach_face(front, back, "Back engineering fixture")
    grading.set_centering_review(front, "back", 10, "Explicit back assessment")
    grading.human_validate(front, "Synthetic confirmation of both faces", True)
    saved = front.save(tmp_path / "sessions")
    w.open_session(saved)
    assert w.session.data["prediction_exposure"]
    w.open_grading()
    app.processEvents()
    assert grading.evaluate(w.session)["state"] == "Human validated"
    assert '"final_grade": 10' in w.grading_dialog.result.toPlainText()
    w.grading_dialog.close()
