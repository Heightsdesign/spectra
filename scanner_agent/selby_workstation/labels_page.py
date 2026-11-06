"""Labels module: browse existing production mappings without allocating identities."""

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .form_widgets import FormComboBox
from .incoming_ui import Fetch
from .label_mapping import mapped_orders
from .labels_ui import LabelDialog
from .operational_style import apply_operational_style, visual_role


class LabelsPage(QWidget):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell, self.busy, self.dialog = shell, False, None
        self.calibration_dialog = None
        apply_operational_style(self)
        root = QVBoxLayout(self)
        heading = QLabel("Labels — existing production orders")
        visual_role(heading, "heading")
        root.addWidget(heading)
        calibration = QHBoxLayout()
        calibration.addWidget(
            QLabel("Printer calibration · TEST / NOT VALID · 50 × 30 mm · no order required")
        )
        self.calibration_button = QPushButton("Printer calibration…")
        self.calibration_button.clicked.connect(self.open_calibration)
        calibration.addWidget(self.calibration_button)
        root.addLayout(calibration)
        note = QLabel(
            "Select an existing ORD → SP mapping. Previews do not submit print jobs. Sign in through Incoming orders; printing always requires current backend eligibility."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        self.orders = FormComboBox()
        self.orders.setMinimumContentsLength(35)
        root.addWidget(self.orders)
        self.refresh_button = QPushButton("Refresh mapped orders")
        self.open_button = QPushButton("Open label previews / printing")
        self.open_button.setProperty("actionRole", "primary")
        sign_in = QPushButton("Sign in / manage backend connection")
        actions = QHBoxLayout()
        for button in (self.refresh_button, self.open_button, sign_in):
            actions.addWidget(button)
        root.addLayout(actions)
        sign_in.clicked.connect(lambda: shell.navigate("Incoming Submissions"))
        self.status = QLabel("Open Labels to load the current registry.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.host = QScrollArea()
        self.host.setWidgetResizable(True)
        root.addWidget(self.host, 1)
        self.refresh_button.clicked.connect(self.refresh)
        self.open_button.clicked.connect(self.open_selected)
        self.orders.currentIndexChanged.connect(self.selection_changed)
        self.controls()

    def controls(self):
        waiting = (
            self.busy
            or bool(self.dialog and self.dialog.busy)
            or bool(self.calibration_dialog and self.calibration_dialog.busy)
        )
        self.calibration_button.setEnabled(not waiting)
        self.calibration_button.setToolTip(
            "Diagnostic hardware workflow; no customer order or payment is needed. Wait for any active label operation to finish."
        )
        self.refresh_button.setEnabled(not waiting)
        self.orders.setEnabled(not waiting)
        self.open_button.setEnabled(not waiting and bool(self.orders.currentData()))
        self.open_button.setToolTip(
            "Wait for the label operation to finish."
            if waiting
            else "Select a mapped order; backend sign-in and mapping confirmation are checked when opened."
        )
        self.open_button.setAccessibleDescription(self.open_button.toolTip())

    def open_calibration(self):
        if self.dialog and self.dialog.busy:
            return
        if self.calibration_dialog and self.calibration_dialog.isVisible():
            self.calibration_dialog.raise_()
            self.calibration_dialog.activateWindow()
            return
        from .calibration_ui import CalibrationDialog

        self.calibration_dialog = CalibrationDialog(self.shell.settings.fileName(), self)
        self.calibration_dialog.busy_changed.connect(self.controls)
        self.calibration_dialog.show()

    def selection_changed(self):
        if self.dialog and not self.dialog.busy:
            self.host.takeWidget()
            self.dialog.deleteLater()
            self.dialog = None
        self.controls()

    def refresh(self, order_id=None):
        if self.busy or (self.dialog and self.dialog.busy):
            return
        desired = (
            order_id
            if isinstance(order_id, str)
            else (self.orders.currentData() or {}).get("order_id")
        )
        path = self.shell.workstation.orders_path
        self.busy = True
        self.controls()
        self.status.setText("Reading existing mappings without changing the registry…")

        def completed(generation, rows, error):
            self.busy = False
            self.orders.clear()
            if error:
                self.status.setText(str(error))
            else:
                self.orders.addItem("Select an existing mapped order", None)
                for row in rows:
                    self.orders.addItem(
                        f"{row['order_id']} · {row['sp']} · {len(row['cards'])} PC mappings · {'confirmed' if row['confirmed'] else 'pending'}",
                        row,
                    )
                index = next(
                    (
                        i
                        for i in range(1, self.orders.count())
                        if self.orders.itemData(i)["order_id"] == desired
                    ),
                    0,
                )
                self.orders.setCurrentIndex(index)
                self.status.setText(
                    "Select an order, then open its label previews."
                    if rows
                    else "No mapped orders in this registry. Import through the existing production bridge; Labels creates nothing."
                )
            self.controls()

        self.job = Fetch(0, lambda: mapped_orders(path))
        self.job.result.ready.connect(completed)
        QThreadPool.globalInstance().start(self.job)

    def open_selected(self):
        context = self.orders.currentData()
        if self.busy or not context or (self.dialog and self.dialog.busy):
            return
        incoming = self.shell.pages["Incoming Submissions"]
        if incoming.auth is None:
            self.status.setText("Configure the backend and sign in through Incoming orders first.")
            return
        if self.dialog:
            self.host.takeWidget()
            self.dialog.deleteLater()
        self.dialog = LabelDialog(
            incoming.auth,
            context["sid"],
            self,
            settings_path=self.shell.settings.fileName(),
            mapping_context=context,
        )
        self.dialog.busy_changed.connect(self.dialog_activity)
        self.dialog.setWindowFlags(Qt.WindowType.Widget)
        self.host.setWidget(self.dialog)
        self.dialog.show()
        self.status.setText(
            f"Selected {context['order_id']} · validating the complete local/backend PC mapping."
        )
        self.controls()

    def dialog_activity(self):
        self.controls()
        if self.dialog and not self.dialog.busy:
            self.status.setText(
                f"Backend mapping verified for {self.orders.currentData()['order_id']}. Previews do not submit jobs."
                if self.dialog.state
                else self.dialog.status.text()
            )
