"""Nonsecret, explicitly saved desktop connection preferences."""
import os
from PySide6.QtCore import Signal, Slot, QThreadPool
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QComboBox, QLineEdit, QPushButton
from .connection import DesktopConnection
from .incoming import PreviewError
from .incoming_ui import Fetch


class ConnectionSettings(QWidget):
    save_requested = Signal(object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel('Incoming Orders connection — nonsecret preferences only')
        layout.addWidget(title)
        form = QFormLayout()
        self.environment = QComboBox()
        for label, value in [('Not configured', ''), ('Local / development', 'development'), ('Production / HTTPS', 'production')]:
            self.environment.addItem(label, value)
        self.backend = QLineEdit()
        self.portal = QLineEdit()
        form.addRow('Environment', self.environment)
        form.addRow('FastAPI origin', self.backend)
        form.addRow('Portal authentication origin', self.portal)
        layout.addLayout(form)
        self.local_button = QPushButton('Use local development defaults')
        self.test_button = QPushButton('Test connection')
        self.save_button = QPushButton('Save connection')
        for button in (self.local_button, self.test_button, self.save_button):
            layout.addWidget(button)
        self.status = QLabel('Backend not configured. Choose local defaults or enter the intended origins, test, then save.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        hint = QLabel('Save applies immediately. No password or session is stored here. HTTP is permitted only for loopback hosts. The portal origin must match FastAPI AUTH_ORIGIN exactly. Saving does not grant operator permissions.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        values = {key: settings.value(key) for key in settings.allKeys() if key.startswith('incoming/')}
        self.backend.setText(str(values.get('incoming/backend_origin', '')))
        self.portal.setText(str(values.get('incoming/auth_origin', '')))
        self.environment.setCurrentIndex(max(0, self.environment.findData(values.get('incoming/environment', ''))))
        try:
            connection = DesktopConnection.load(values)
            if connection:
                self.environment.setCurrentIndex(self.environment.findData(connection.environment))
                self.backend.setText(connection.backend_origin)
                self.portal.setText(connection.auth_origin)
                self.status.setText('Backend configured. Test connection to check reachability; sign in from Incoming Orders.')
        except PreviewError as exc:
            self.status.setText('Invalid connection: ' + str(exc))
        self.overridden = any(key in os.environ for key in ('SELBY_ENVIRONMENT', 'SELBY_BACKEND_ORIGIN', 'SELBY_AUTH_ORIGIN'))
        if self.overridden:
            self.status.setText('Connection is managed by SELBY_* environment overrides. Ask the launcher administrator to change/remove those overrides before saving preferences here.')
            for widget in (self.environment, self.backend, self.portal, self.local_button, self.save_button):
                widget.setEnabled(False)
        self.job = None
        self.local_button.clicked.connect(self.local_defaults)
        self.test_button.clicked.connect(self.test_connection)
        self.save_button.clicked.connect(self.save)

    def local_defaults(self):
        self.environment.setCurrentIndex(self.environment.findData('development'))
        self.backend.setText('http://127.0.0.1:8000')
        self.portal.setText('http://127.0.0.1:3000')
        self.status.setText('Local development defaults selected. Test and Save to apply; no connection has been saved yet.')

    def connection(self):
        return DesktopConnection(self.environment.currentData(), self.backend.text().strip(), self.portal.text().strip())

    def save(self):
        if self.overridden:
            return
        try:
            self.save_requested.emit(self.connection())
        except PreviewError as exc:
            self.status.setText('Invalid connection: ' + str(exc))

    def test_connection(self):
        if self.job is not None:
            return
        try:
            connection = self.connection()
        except PreviewError as exc:
            self.status.setText('Invalid connection: ' + str(exc))
            return
        self.status.setText('Checking backend reachability… No credentials are sent.')
        self.test_button.setEnabled(False)
        if not self.overridden:
            for widget in (self.environment, self.backend, self.portal, self.local_button, self.save_button):
                widget.setEnabled(False)
        self.job = Fetch(0, connection.check)
        self.job.result.ready.connect(self.checked)
        QThreadPool.globalInstance().start(self.job)

    @Slot(int, object, object)
    def checked(self, generation, value, error):
        self.job = None
        self.test_button.setEnabled(True)
        if not self.overridden:
            for widget in (self.environment, self.backend, self.portal, self.local_button, self.save_button):
                widget.setEnabled(True)
        self.status.setText(str(error) if error else value)
