"""Navigation and desktop preferences over the existing workstation components."""

import sqlite3
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .incoming_ui import IncomingSubmissions
from .connection import DesktopConnection
from .connection_settings import ConnectionSettings
from .incoming import PreviewError
from .orders import AUTHORIZATION_PATH, DEFAULT_PATH, OrderStore

SETTINGS_PATH = DEFAULT_PATH.with_name("desktop.ini")


class DesktopShell(QWidget):
    def __init__(self, workstation, inspection, settings_path=None):
        super().__init__(workstation)
        self.workstation = workstation
        self.settings = QSettings(str(settings_path or SETTINGS_PATH), QSettings.Format.IniFormat)
        workstation.orders_path = Path(self.settings.value("orders_path", str(DEFAULT_PATH)))
        self.workflow_card = None
        root = QVBoxLayout(self)
        title = QLabel("SELBY  /  WORKSTATION V0.5c.1")
        title.setStyleSheet("font-size:20px; font-weight:600; padding:8px")
        root.addWidget(title)
        self.context = QLabel()
        self.context.setWordWrap(True)
        self.context.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.context)
        body = QHBoxLayout()
        navigation = QVBoxLayout()
        body.addLayout(navigation)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        self.pages = {}
        self.buttons = {}
        for index, name in enumerate(("Dashboard", "Orders", "Inspection", "Grading", "Settings", "Incoming Submissions", "Labels")):
            button = QPushButton('Incoming orders' if name == 'Incoming Submissions' else name)
            button.setCheckable(True)
            button.setMinimumWidth(125)
            button.clicked.connect(lambda checked=False, n=name: workstation.guard(
                lambda: self.navigate(n)))
            navigation.addWidget(button)
            self.buttons[name] = button
            action = QAction(name, workstation)
            action.setShortcut(f"Ctrl+{index + 1}")
            action.triggered.connect(lambda checked=False, n=name: workstation.guard(
                lambda: self.navigate(n)))
            workstation.addAction(action)
        navigation.addStretch()
        self.scan_button = QPushButton("Scan card")
        self.scan_button.clicked.connect(self.open_scanner)
        navigation.addWidget(self.scan_button)
        scan_action = QAction("Scan card", workstation)
        scan_action.setShortcut("Ctrl+Shift+S")
        scan_action.triggered.connect(self.open_scanner)
        workstation.addAction(scan_action)
        self.pages["Dashboard"] = self.dashboard()
        self.pages["Orders"] = QStackedWidget()
        self.pages["Inspection"] = inspection
        self.pages["Grading"] = QStackedWidget()
        self.grading_empty = self.grading_landing()
        self.pages["Grading"].addWidget(self.grading_empty)
        self.pages["Settings"] = self.settings_page()
        values = {key: self.settings.value(key) for key in self.settings.allKeys() if key.startswith('incoming/')}
        try:
            connection = DesktopConnection.load(values)
            self.pages["Incoming Submissions"] = IncomingSubmissions(self, connection=connection)
        except PreviewError as exc:
            self.pages["Incoming Submissions"] = IncomingSubmissions(self)
            self.pages["Incoming Submissions"].status.setText(str(exc))
        from .labels_page import LabelsPage
        self.pages['Labels'] = LabelsPage(self)
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.current = "Dashboard"
        self.navigate("Dashboard")
        action = QAction("Find internal card", workstation)
        action.setShortcut("Ctrl+L")
        action.triggered.connect(lambda: workstation.guard(self.focus_card_search))
        workstation.addAction(action)

    def open_scanner(self):
        from .scanner_ui import ScannerDialog
        if not hasattr(self, "scanner_dialog"):
            self.scanner_dialog = ScannerDialog(self)
        self.scanner_dialog.show()
        self.scanner_dialog.raise_()
        self.scanner_dialog.activateWindow()
        self.scanner_dialog.scanner_input.setFocus()

    @staticmethod
    def page(title):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(title)
        label.setStyleSheet("font-size:18px; font-weight:600")
        layout.addWidget(label)
        return page, layout

    def button(self, layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(lambda: self.workstation.guard(callback))
        layout.addWidget(button)
        return button

    def dashboard(self):
        page, layout = self.page("Dashboard")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.button(layout, "Browse orders / receive cards", lambda: self.navigate("Orders"))
        self.button(layout, "Open original scan…", self.workstation.choose_image)
        self.button(layout, "Open saved inspection / grading session…", self.workstation.choose_session)
        self.button(layout, "Resume current inspection", lambda: self.navigate("Inspection"))
        self.button(layout, "Return to selected order", lambda: self.navigate("Orders"))
        layout.addWidget(QLabel("Ctrl+1–5: modules · Ctrl+L: internal card lookup · Tab / Enter: form navigation"))
        layout.addStretch()
        return page

    def grading_landing(self):
        page, layout = self.page("Grading")
        label = QLabel("No inspection is loaded. Open a saved session or an original scan first.\n"
                       "Creating a dossier and associating a production card are explicit actions.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.button(layout, "Open saved session…", self.workstation.choose_session)
        self.button(layout, "Open original scan…", self.workstation.choose_image)
        self.button(layout, "Choose a card in Orders", lambda: self.navigate("Orders"))
        layout.addStretch()
        return page

    def settings_page(self):
        page, layout = self.page("Settings")
        self.paths = QLabel()
        self.paths.setWordWrap(True)
        self.paths.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.paths)
        self.connection_settings = ConnectionSettings(self.settings, self)
        self.connection_settings.save_requested.connect(self.save_connection)
        layout.addWidget(self.connection_settings)
        self.button(layout, "Use an existing orders registry…", self.choose_registry)
        self.button(layout, "Use default orders registry", lambda: self.change_registry(DEFAULT_PATH))
        layout.addWidget(QLabel("Administrator-managed configuration (read only):"))
        self.configuration = QComboBox()
        self.configuration.addItems(["Orders correction authorization", "Grading override authorization",
                                     "V0.4 grading policy"])
        layout.addWidget(self.configuration)
        self.configuration_text = QPlainTextEdit()
        self.configuration_text.setReadOnly(True)
        layout.addWidget(self.configuration_text)
        self.configuration.currentIndexChanged.connect(self.read_configuration)
        layout.addWidget(QLabel("Operator identity is entered in Orders or Inspection.\n"
                                "Registry selection is saved locally; policy and permissions are not edited here."))
        return page

    def save_connection(self, connection):
        page = self.pages['Incoming Submissions']
        if page.busy:
            self.connection_settings.status.setText('Wait for the current Incoming request to finish, then save again.')
            return
        if page.auth is not None and page.auth.connection == connection:
            self.connection_settings.status.setText('Connection already active. Open Incoming Orders to sign in or refresh.')
            return

        def apply(revoked=True):
            if not revoked:
                self.connection_settings.status.setText('Previous session revocation is pending offline. Reconnect and sign out before changing origins. Preferences were not changed.')
                return
            for key in ('environment', 'backend_origin', 'auth_origin'):
                self.settings.setValue('incoming/' + key, getattr(connection, key))
            self.settings.sync()
            if self.settings.status() != QSettings.Status.NoError:
                self.connection_settings.status.setText('Unable to save connection preferences. Check permissions on desktop.ini.')
                return
            page.configure(connection)
            self.connection_settings.status.setText('Connection saved and applied. Open Incoming Orders to sign in. Test connection checks reachability without credentials.')

        if page.auth is not None:
            page.disconnect()
            def completed(revoked):
                apply(revoked)
            page.fetch(page.auth.sign_out, completed, 'Revoking previous session before changing connection…')
        else:
            apply()

    def read_configuration(self):
        from .grading import AUTHORIZATION_PATH as GRADING_AUTHORIZATION
        from .grading import POLICY_PATH

        path = (AUTHORIZATION_PATH, GRADING_AUTHORIZATION, POLICY_PATH)[self.configuration.currentIndex()]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            text = f"Configuration cannot be read: {exc}\nAsk the workstation administrator."
        self.configuration_text.setPlainText(f"{path}\n\n{text}")

    def choose_registry(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select existing orders registry", "",
                                             "SQLite registry (*.sqlite3 *.db);;All files (*)")
        if path:
            self.change_registry(Path(path))

    def change_registry(self, path):
        path = Path(path).resolve()
        if path == self.workstation.orders_path.resolve():
            return
        if QMessageBox.question(self, "Switch orders registry?",
                f"Use {path}?\nSelected order/card context and unsubmitted order forms will clear. "
                "The active inspection stays open.\n"
                "Independent registries may contain overlapping IDs; no data will be merged.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        if path.exists():
            # Inspect before calling the existing service, which initializes empty stores.
            # Choosing an unrelated SQLite file must never add tables to that file.
            db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
            try:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                required = {"orders", "cards", "audit"}
                if version == 2:
                    required |= {"bridge_registry", "bridge_orders", "bridge_cards"}
                if version not in (1, 2) or not required <= tables:
                    raise ValueError("Select an existing SELBY orders registry (schema 1 or 2); this file is not compatible")
            finally:
                db.close()
        elif path != DEFAULT_PATH.resolve():
            raise ValueError("Registry file is missing. Select an existing registry or use the default registry")
        OrderStore(path)
        self.settings.setValue("orders_path", str(path))
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            raise OSError("Could not save registry preference; check Settings file permissions")
        self.workstation.orders_path = path
        if hasattr(self.workstation, "orders_dialog"):
            self.workstation.orders_dialog.deleteLater()
            del self.workstation.orders_dialog
        self.workflow_card = None
        self.navigate("Settings")

    def navigate(self, name):
        if name == 'Labels':
            self.pages['Labels'].refresh()
        if name == "Orders":
            self.workstation.open_orders()
            return
        if name == "Grading" and self.workstation.session:
            self.workstation.open_grading()
            return
        self.activate(name)

    def open_labels(self, order_id=None):
        self.activate('Labels')
        self.pages['Labels'].refresh(order_id)

    def activate(self, name):
        self.current = name
        self.stack.setCurrentWidget(self.pages[name])
        for label, button in self.buttons.items():
            button.setChecked(label == name)
        for toolbar in self.workstation.inspection_toolbars:
            toolbar.setVisible(name == "Inspection")
        self.update_context()
        if name == "Dashboard":
            path = self.workstation.orders_path
            if path.exists():
                try:
                    orders = OrderStore(path).search_orders()
                    self.summary.setText(f"{len(orders)} orders · {sum(o['card_count'] for o in orders)} cards\n"
                                         "Select Orders to browse, create an order, or look up a card.")
                except Exception as exc:
                    self.summary.setText(f"Orders registry unavailable: {exc}\n"
                                         "Open Settings to check the registry path or choose an existing registry.")
            else:
                self.summary.setText("No orders registry yet. Open Orders to create your first order.")
        if name == "Settings":
            self.paths.setText(f"Orders registry: {self.workstation.orders_path.resolve()}\n"
                               f"Recovery drafts: {self.workstation.draft_directory}\n"
                               f"Desktop preferences: {self.settings.fileName()}")
            self.read_configuration()

    def update_context(self):
        orders = getattr(self.workstation, "orders_dialog", None)
        selection = (f"{orders.order_id or 'no order'} / {orders.card_id or 'no card'}"
                     if orders else "no order / no card")
        session = self.workstation.session
        active = session.data["session_id"] if session else "none — open a scan or saved session"
        self.context.setText(f"Selected: {selection}\nActive session: {active} · "
                             f"Linked production card: {self.workflow_card or 'none verified for this session'}")

    def install(self, name, dialog):
        host = self.pages[name]
        if not hasattr(dialog, "desktop_scroll"):
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            dialog.setWindowFlags(Qt.WindowType.Widget)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(dialog)
            dialog.desktop_scroll = scroll
            host.addWidget(scroll)
        host.setCurrentWidget(dialog.desktop_scroll)
        dialog.show()
        self.activate(name)

    def session_changed(self):
        self.workflow_card = None
        if hasattr(self.workstation, "grading_dialog"):
            old = self.workstation.grading_dialog
            old.desktop_scroll.deleteLater()
            del self.workstation.grading_dialog
        self.pages["Grading"].setCurrentWidget(self.grading_empty)
        self.activate("Inspection")

    def focus_card_search(self):
        self.navigate("Orders")
        self.workstation.orders_dialog.card_search.setFocus()
        self.workstation.orders_dialog.card_search.selectAll()

    def open_card_workflow(self, grading=False):
        orders = self.workstation.orders_dialog
        orders.require_card()
        reference = orders.store.get_card(orders.card_id)["session_reference"]
        if not reference:
            orders.message.setText("This card has no linked grading session. Open a scan or saved session "
                                   "in Inspection, save its grading dossier, then use Associate saved grading session. "
                                   "Nothing has been created or linked.")
            return
        reference = orders.store.verify_association(orders.card_id)
        session = self.workstation.session
        same = (session and session.saved_path == Path(reference["path"])
                and session.saved_sha == reference["sha256"])
        if not same:
            self.workstation.require_finished_gesture()
            if not self.workstation.discard_allowed():
                return
            self.workstation.open_session(Path(reference["path"]))
        self.workflow_card = orders.card_id
        self.navigate("Grading" if grading else "Inspection")
