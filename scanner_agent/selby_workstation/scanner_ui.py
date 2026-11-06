"""One explicit keyboard-wedge capture surface; never intercept unrelated typing."""

from time import monotonic

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .incoming import PreviewError
from .incoming_ui import Fetch
from .operational_style import apply_operational_style
from .scanner_keyboard import PROFILES, SYSTEM_PROFILE, ScannerInput
from .scanning import identify, resolve


class ScannerDialog(QDialog):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell, self.busy = shell, False
        self.last, self.last_at = None, 0
        self.current_payload = None
        self.new_original = False
        self.setWindowTitle("SELBY · Scan card")
        self.setMinimumWidth(640)
        apply_operational_style(self)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Keyboard-wedge input ready · profile hardware acceptance pending"))
        note = QLabel(
            "Scan in Physical scanner input; type or paste in Manual QR input.\nA scan identifies a card; backend eligibility is required for inspection."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(QLabel("Scanner input profile"))
        self.profile = QComboBox()
        for label, value in PROFILES:
            self.profile.addItem(label, value)
        selected = self.profile.findData(shell.settings.value("scanner/profile", SYSTEM_PROFILE))
        self.profile.setCurrentIndex(max(0, selected))
        layout.addWidget(self.profile)
        profile_note = QLabel(
            "Correction applies only to key events in Physical scanner input. "
            "Manual input/paste stays unchanged. Windows keeps its keyboard layout."
        )
        profile_note.setWordWrap(True)
        layout.addWidget(profile_note)
        self.suffix = QComboBox()
        self.suffix.addItems(["Enter / Return suffix", "No suffix · use Identify"])
        self.suffix.setCurrentIndex(int(shell.settings.value("scanner/suffix", 0)))
        self.suffix.currentIndexChanged.connect(
            lambda i: shell.settings.setValue("scanner/suffix", i)
        )
        layout.addWidget(self.suffix)
        layout.addWidget(QLabel("Physical scanner input"))
        self.scanner_input = ScannerInput(self)
        self.scanner_input.profile = self.profile.currentData()
        layout.addWidget(self.scanner_input)
        self.profile.currentIndexChanged.connect(self.profile_changed)
        self.scan_button = QPushButton("Identify scan")
        self.scan_button.setAutoDefault(False)
        self.scan_button.clicked.connect(self.submit_scanner)
        layout.addWidget(self.scan_button)
        self.clear_scan_button = QPushButton("Clear scanner input")
        self.clear_scan_button.setAutoDefault(False)
        self.clear_scan_button.clicked.connect(self.clear_scanner)
        layout.addWidget(self.clear_scan_button)
        self.scanner_input.scan_returned.connect(
            lambda: self.submit_scanner() if self.suffix.currentIndex() == 0 else None
        )
        layout.addWidget(QLabel("Manual QR input / paste · unchanged by scanner profile"))
        self.input = QLineEdit()
        self.input.setMaxLength(256)
        self.input.setPlaceholderText("Full SELBY QR payload / manual fallback")
        layout.addWidget(self.input)
        self.button = QPushButton("Identify manual input")
        self.button.setAutoDefault(False)
        layout.addWidget(self.button)
        self.new_button = QPushButton("Open original scan for identified card…")
        self.new_button.setAutoDefault(False)
        self.new_button.setEnabled(False)
        self.new_button.clicked.connect(self.start_original)
        layout.addWidget(self.new_button)
        self.status = QLabel("Awaiting a complete scan. No serial port is opened.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.show_diagnostic = QCheckBox("Show last input diagnostic (memory only)")
        layout.addWidget(self.show_diagnostic)
        self.input_diagnostic = QLabel()
        self.input_diagnostic.setTextFormat(Qt.TextFormat.PlainText)
        self.input_diagnostic.setWordWrap(True)
        self.input_diagnostic.setMinimumHeight(64)
        self.input_diagnostic.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.input_diagnostic.hide()
        layout.addWidget(self.input_diagnostic)
        self.show_diagnostic.toggled.connect(self.toggle_diagnostic)
        self.button.clicked.connect(self.submit)
        self.input.returnPressed.connect(
            lambda: self.submit() if self.suffix.currentIndex() == 0 else None
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.scanner_input.setFocus()

    def profile_changed(self):
        self.scanner_input.clear()
        self.current_payload = None
        self.new_button.setEnabled(False)
        self.scanner_input.profile = self.profile.currentData()
        self.shell.settings.setValue("scanner/profile", self.profile.currentData())
        self.shell.settings.sync()
        self.input_diagnostic.clear()
        self.status.setText("Scanner profile changed. Scan the complete label again.")
        self.scanner_input.setFocus()

    def toggle_diagnostic(self, visible):
        self.input_diagnostic.setVisible(visible)
        self.adjustSize()

    def clear_scanner(self):
        self.scanner_input.clear()
        self.scanner_input.setFocus()

    def submit_scanner(self):
        if self.busy:
            return
        received = self.scanner_input.received
        payload = self.scanner_input.decoded
        error = self.scanner_input.error
        self.scanner_input.clear()
        self.scanner_input.setFocus()
        if error:
            self.input_diagnostic.setText(f"Received: {received!r}\nValidated payload: REJECTED")
            self.status.setText(error)
            self.new_button.setEnabled(False)
            self.current_payload = None
            return
        self.submit(payload=payload, received=received)

    def start_original(self):
        if self.current_payload and not self.busy:
            self.input.setText(self.current_payload)
            self.last = None
            self.submit(new_original=True)

    def submit(self, new_original=False, payload=None, received=None):
        if self.busy:
            return
        self.status.setStyleSheet("")
        if payload is None:
            payload = self.input.text()
            self.input.clear()
        if received is None:
            received = payload
        self.input_diagnostic.setText(f"Received: {received!r}\nValidated payload: REJECTED")
        self.new_original = new_original
        self.new_button.setEnabled(False)
        self.current_payload = None
        if payload == self.last and monotonic() - self.last_at < 2:
            try:
                identify(payload)
                self.input_diagnostic.setText(
                    f"Received: {received!r}\nValidated payload: {payload}"
                )
            except PreviewError:
                pass
            self.status.setText("Repeated scan ignored. Wait two seconds to refresh eligibility.")
            return
        self.last, self.last_at = payload, monotonic()
        self.pending_payload = payload
        try:
            kind, reference = identify(payload)
            self.input_diagnostic.setText(f"Received: {received!r}\nValidated payload: {payload}")
            if kind == "diagnostic":
                self.status.setText(
                    f"Diagnostic recognized: {reference} · TEST / NOT VALID · grading not opened."
                )
                return
            auth = self.shell.pages["Incoming Submissions"].auth
            if auth is None:
                raise PreviewError(
                    "Configure the backend and sign in through Incoming orders first."
                )
            path = self.shell.workstation.orders_path.resolve()
            connection = auth.connection
        except PreviewError as exc:
            self.status.setText(str(exc))
            return
        self.busy = True
        self.input.setEnabled(False)
        self.button.setEnabled(False)
        self.scanner_input.setEnabled(False)
        self.scan_button.setEnabled(False)
        self.profile.setEnabled(False)
        self.suffix.setEnabled(False)
        self.clear_scan_button.setEnabled(False)
        self.status.setText(
            f"Identified {kind}: {reference} · checking authoritative backend state…"
        )

        def completed(generation, value, error):
            self.busy = False
            self.input.setEnabled(True)
            self.button.setEnabled(True)
            self.scanner_input.setEnabled(True)
            self.scan_button.setEnabled(True)
            self.profile.setEnabled(True)
            self.suffix.setEnabled(True)
            self.clear_scan_button.setEnabled(True)
            self.scanner_input.setFocus()
            if error:
                self.status.setText(str(error))
                return
            if (
                path != self.shell.workstation.orders_path.resolve()
                or auth is not self.shell.pages["Incoming Submissions"].auth
                or auth.connection != connection
            ):
                self.status.setText("Connection or registry changed. Scan again.")
                return
            self.shell.workstation.guard(lambda: self.present(value))

        self.job = Fetch(0, lambda: resolve(path, payload, auth.intake_client()))
        self.job.result.ready.connect(completed)
        QThreadPool.globalInstance().start(self.job)

    def present(self, result):
        context, card = result["context"], result["card"]
        if not card:
            self.shell.navigate("Orders")
            self.shell.workstation.orders_dialog.open_order(context["order_id"])
            self.status.setText(
                f"Order lookup: {context['order_id']} · {context['sp']} · grading not opened."
            )
            return
        # A blocked scan stays in this read-only result view, without changing selection/status.
        from .orders import OrderStore

        store = OrderStore(context["path"])
        local = store.get_card(card["card_id"])
        heading = f"{local['metadata'].get('description', '')}\n{context['order_id']} · {context['sp']}\n{card['pc']} · {card['card_id']}"
        eligibility = result["eligibility"]
        local_reasons = []
        if local["status"] in ("completed", "cancelled"):
            local_reasons.append("Local card status: " + local["status"])
        order = store.get_order(context["order_id"])
        if order["status"] in ("completed", "shipped", "cancelled"):
            local_reasons.append("Local order status: " + order["status"])
        if local_reasons:
            eligibility = dict(eligible=False, reasons=eligibility["reasons"] + local_reasons)
        if not eligibility["eligible"]:
            self.status.setStyleSheet("color: #ffbd69")
            self.status.setText(
                heading
                + "\nBLOCKED: "
                + "; ".join(
                    str(reason.get("code", ""))
                    + (
                        ": " + str(reason.get("message") or reason.get("en"))
                        if reason.get("message") or reason.get("en")
                        else ""
                    )
                    if isinstance(reason, dict)
                    else str(reason)
                    for reason in eligibility["reasons"]
                )
            )
            return
        self.shell.navigate("Orders")
        orders = self.shell.workstation.orders_dialog
        orders.open_card(card["card_id"])
        self.shell.open_card_workflow()
        self.status.setStyleSheet("color: #55e0bd")
        if not local["session_reference"]:
            self.current_payload = self.pending_payload
            self.new_button.setEnabled(True)
            if self.new_original:
                # Existing file picker, discard confirmation and Session creation.
                # No dossier/association is synthesized from a QR identity.
                self.shell.workstation.choose_image()
        self.status.setText(
            heading
            + "\nEligible · "
            + (
                "Existing inspection opened."
                if local["session_reference"]
                else "No linked session. Use Open original scan, save the dossier, then explicitly associate it in Orders."
            )
        )
        if local["session_reference"]:
            self.accept()

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
