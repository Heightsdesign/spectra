"""In-memory remote preview with bounded background GETs; no import actions."""

from datetime import datetime

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from threading import Event
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .incoming import PreviewError
from .connection import DesktopConnection
from .desktop_auth import DesktopAuthService


class Result(QObject):
    ready = Signal(int, object, object)


class Fetch(QRunnable):
    def __init__(self, generation, callback):
        super().__init__()
        self.generation, self.callback = generation, callback
        self.result = Result()

    def run(self):
        try:
            value, error = self.callback(), None
        except PreviewError as exc:
            value, error = None, exc
        except Exception:
            # Never expose response bodies, credentials, URLs or customer data in errors.
            value, error = None, PreviewError('Unable to read preview data. Check the backend configuration.')
        self.callback = None
        self.result.ready.emit(self.generation, value, error)


class IncomingSubmissions(QScrollArea):
    def __init__(self, parent=None, connection=None, auth_service=None):
        super().__init__(parent)
        self.auth = auth_service
        self.configuration_error = None
        try:
            configured = connection or DesktopConnection.load()
            if self.auth is None and configured is not None:
                self.auth = DesktopAuthService(configured)
        except PreviewError as exc:
            self.configuration_error = str(exc)
        self.cancel_login = Event()
        self.setWidgetResizable(True)
        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)
        title = QLabel('Incoming orders')
        layout.addWidget(title)
        self.setup_button = QPushButton('Configure connection in Settings')
        self.setup_button.clicked.connect(self.open_settings)
        layout.addWidget(self.setup_button)
        self.connection_state = QLabel('Backend not configured' if self.auth is None else 'Backend configured · reachability not checked')
        self.connection_state.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.connection_state)
        explanation = QLabel('Read-only online declarations. Online confirmation is not physical receipt, payment or inspection clearance. Local Orders and grading tools remain available offline.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.account = QLabel('Not signed in')
        self.account.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.account)
        self.login_form = QWidget()
        form = QFormLayout(self.login_form)
        self.email = QLineEdit()
        self.email.setMaxLength(254)
        self.email.setPlaceholderText('operator@example.org')
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMaxLength(128)
        form.addRow('Operator email', self.email)
        form.addRow('Password', self.password)
        layout.addWidget(self.login_form)
        buttons = QHBoxLayout()
        self.connect_button = QPushButton('Sign in')
        self.disconnect_button = QPushButton('Sign out')
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.disconnect_button)
        layout.addLayout(buttons)
        secure_hint = QLabel('The password is never saved. The expiring session is stored in Windows Credential Manager for this Windows account.')
        secure_hint.setWordWrap(True)
        layout.addWidget(secure_hint)
        self.status = QLabel('Disconnected. Local workstation remains available.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        search = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search reference or customer name')
        self.search.setMaxLength(200)
        self.refresh_button = QPushButton('Search / refresh')
        self.previous_button = QPushButton('Previous 50')
        self.next_button = QPushButton('Next 50')
        for widget in (self.search, self.refresh_button, self.previous_button, self.next_button):
            search.addWidget(widget)
        layout.addLayout(search)
        self.queue = self.table(layout, ['Reference', 'Customer', 'Declared', 'Received', 'Submitted', 'Intake status'])
        self.open_button = QPushButton('Open selected order')
        layout.addWidget(self.open_button)
        self.intake_button = QPushButton('Start / resume reception…')
        layout.addWidget(self.intake_button)
        self.intake_button.clicked.connect(self.open_intake)
        self.production_button = QPushButton('Prepare / reopen production order…')
        layout.addWidget(self.production_button)
        self.production_button.clicked.connect(self.open_production)
        self.labels_button = QPushButton('Print labels…')
        layout.addWidget(self.labels_button)
        self.labels_button.clicked.connect(self.open_labels)
        self.detail = QLabel('Select a submission to preview its declared and received cards.')
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.detail)
        layout.addWidget(QLabel('Expected cards — customer declaration entries; quantity may exceed one'))
        self.expected = self.table(layout, ['Card', 'Game', 'Expansion', 'Number', 'Language', 'Declared quantity'])
        photo_hint = QLabel('Customer pre-shipment photographs — unverified customer declarations, not SELBY inspection evidence. Copy numbers are not received physical-card IDs.')
        photo_hint.setWordWrap(True)
        layout.addWidget(photo_hint)
        self.photos = self.table(layout, ['Declared card', 'Copy number', 'Side', 'Uploaded at'])
        self.photo_button = QPushButton('View selected pre-shipment photograph')
        layout.addWidget(self.photo_button)
        self.photo_preview = QLabel('No customer photograph selected.')
        self.photo_preview.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.photo_preview)
        self.photo_rows = []
        layout.addWidget(QLabel('Received physical cards — individual backend PC identities'))
        self.physical = self.table(layout, ['Received card reference', 'Declared card', 'Match status', 'Parcel reference', 'Notes'])
        layout.addWidget(QLabel('Parcels'))
        self.parcels = self.table(layout, ['Parcel reference', 'Status'])
        layout.addWidget(QLabel('Reconciliation discrepancies'))
        self.issues = self.table(layout, ['Kind', 'Quantity', 'Entry UUID', 'Physical UUID', 'Status', 'Notes / resolution'])
        self.client = None
        self.generation = 0
        self.offset = 0
        self.rows = []
        self.selected = None
        self.busy = False
        self.job = None
        self.connect_button.clicked.connect(self.connect_backend)
        self.disconnect_button.clicked.connect(self.sign_out)
        self.refresh_button.clicked.connect(self.refresh)
        self.search.returnPressed.connect(self.refresh)
        self.previous_button.clicked.connect(lambda: self.page(-50))
        self.next_button.clicked.connect(lambda: self.page(50))
        self.queue.itemSelectionChanged.connect(self.open_selected)
        self.open_button.clicked.connect(self.open_selected)
        self.password.returnPressed.connect(self.connect_backend)
        self.photo_button.clicked.connect(self.open_photo)
        self.photos.itemSelectionChanged.connect(self.photo_selection_changed)
        self.controls()
        if self.auth is not None:
            QTimer.singleShot(0, self.restore_session)
        else:
            self.status.setText(self.configuration_error or 'Incoming Orders is not configured. Open Settings, choose local development defaults or your approved origins, then Save connection. Local modules remain available.')

    def open_settings(self):
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'navigate'):
                parent.navigate('Settings')
                return
            parent = parent.parent()

    def configure(self, connection):
        self.disconnect()
        self.auth = DesktopAuthService(connection)
        self.configuration_error = None
        self.connection_state.setText('Backend configured · ' + connection.backend_origin)
        self.status.setText('Connection configured. Authentication required. Sign in, or use Settings to test reachability.')
        self.controls()

    @staticmethod
    def table(layout, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setMinimumHeight(145)
        layout.addWidget(table)
        return table

    @staticmethod
    def fill(table, rows):
        table.blockSignals(True)
        table.setRowCount(0)
        for values in rows:
            row = table.rowCount()
            table.insertRow(row)
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem('—' if value is None else str(value)))
        table.resizeColumnsToContents()
        table.blockSignals(False)

    def controls(self):
        connected = self.client is not None
        self.login_form.setVisible(not connected)
        for widget in (self.email, self.password, self.connect_button):
            widget.setEnabled(self.auth is not None and not connected and not self.busy)
        self.connect_button.setVisible(not connected)
        self.disconnect_button.setEnabled(self.auth is not None)
        for widget in (self.search, self.queue):
            widget.setEnabled(connected and not self.busy)
        self.refresh_button.setEnabled(self.auth is not None and not self.busy)
        self.previous_button.setEnabled(connected and not self.busy and self.offset > 0)
        self.next_button.setEnabled(connected and not self.busy and len(self.rows) == 50)
        self.open_button.setEnabled(connected and not self.busy and 0 <= self.queue.currentRow() < len(self.rows))
        self.intake_button.setEnabled(connected and not self.busy and self.selected is not None)
        self.production_button.setEnabled(connected and not self.busy and self.selected is not None)
        self.labels_button.setEnabled(connected and not self.busy and self.selected is not None)
        self.photo_button.setEnabled(connected and not self.busy and 0 <= self.photos.currentRow() < len(self.photo_rows))

    def clear_detail(self):
        self.selected = None
        self.photo_rows = []
        self.photo_preview.clear()
        self.photo_preview.setText('No customer photograph selected.')
        self.detail.setText('Select a submission. No local ORD / SLB-C association is established by this preview.')
        for table in (self.expected, self.physical, self.parcels, self.issues, self.photos):
            self.fill(table, [])

    def disconnect(self):
        # Closing/hiding a preview is not server logout: secure restore remains available.
        self.cancel_login.set()
        self.generation += 1
        self.client = None
        self.password.clear()
        self.email.clear()
        self.account.setText('Not signed in')
        self.rows = []
        self.offset = 0
        self.fill(self.queue, [])
        self.clear_detail()
        self.busy = False
        self.status.setText('Disconnected. Preview cleared; local workstation remains available.')
        self.controls()

    def sign_out(self):
        if self.auth is None:
            self.disconnect()
            return
        self.disconnect()
        self.fetch(self.auth.sign_out, self.signed_out, 'Signing out. Local modules remain available.')

    def signed_out(self, revoked):
        self.connection_state.setText('Backend configured · authentication required' if revoked else 'Backend unreachable · revocation pending')
        self.status.setText('Signed out. Session revoked or already inactive.' if revoked else
            'Signed out locally. Server revocation is pending offline; reconnect and refresh to complete it. Local modules remain available.')

    def business(self, callback):
        def guarded():
            try:
                return callback()
            except PreviewError as exc:
                if exc.disconnect and self.auth is not None:
                    try:
                        self.auth.sign_out()
                    except PreviewError:
                        pass
                raise
        return guarded

    def fetch(self, callback, receive, message=None):
        self.busy = True
        self.generation += 1
        self.status.setText(message or 'Loading remote preview… Local modules remain available.')
        self.controls()
        job = Fetch(self.generation, callback)
        # Receiver is a QObject slot so Qt queues delivery back to the UI thread.
        self.receive = receive
        job.result.ready.connect(self.completed)
        self.job = job
        QThreadPool.globalInstance().start(job)

    @Slot(int, object, object)
    def completed(self, generation, value, error):
        if generation != self.generation:
            return
        self.job = None
        self.busy = False
        if error:
            # Clear stale/customer data on all failures, including session expiry.
            self.fill(self.queue, [])
            self.rows = []
            self.clear_detail()
            if error.disconnect:
                self.disconnect()
            if error.kind == 'offline':
                self.connection_state.setText('Backend unreachable · local modules available')
            elif error.kind == 'permission':
                self.connection_state.setText('Backend reachable · permission denied')
            elif error.kind == 'expired':
                self.connection_state.setText('Backend reachable · session expired; authentication required')
            elif error.disconnect:
                self.connection_state.setText('Backend reachable · session expired or permission denied')
            elif error.kind == 'auth':
                self.connection_state.setText('Backend reachable · authentication required')
            self.status.setText(str(error))
        else:
            if self.client is not None:
                self.connection_state.setText('Backend reachable · authenticated')
            self.status.setText('Connected · refreshed ' + datetime.now().astimezone().strftime('%H:%M:%S %Z'))
            self.receive(value)
        self.controls()

    def connect_backend(self):
        if self.busy or self.auth is None:
            return
        email, password = self.email.text().strip(), self.password.text()
        self.password.clear()
        if not email or not password:
            self.status.setText('Enter your operator email and password.')
            return
        self.cancel_login = Event()
        service, cancelled = self.auth, self.cancel_login
        self.fetch(lambda: service.sign_in(email, password, cancelled), self.authenticated, 'Signing in… Local modules remain available.')

    def restore_session(self):
        if self.auth is not None and not self.busy:
            service = self.auth
            def restore():
                result = service.restore()
                if result is None:
                    service.connection.check()
                return result
            self.fetch(restore, self.authenticated, 'Checking saved sign-in and backend reachability… Local modules remain available.')

    def authenticated(self, result):
        if result is None:
            self.client = None
            self.connection_state.setText('Backend reachable · authentication required')
            self.status.setText('Backend reachable. Authentication required: sign in with your operator account. Local modules remain available offline.')
            self.controls()
            return
        self.client, actor = result
        self.connection_state.setText('Backend reachable · authenticated')
        self.email.clear()
        self.account.setText(f"Signed in: {actor.get('display_name') or actor.get('role', 'staff')}")
        self.offset = 0
        self.load_page()

    def show_rows(self, rows):
        self.rows = rows
        self.clear_detail()
        self.fill(self.queue, [(r['reference'], r.get('customer_name') or '—', r['declared_quantity'], r['received_quantity'], self.date(r.get('submitted_at')), self.state(r['status'])) for r in rows])
        if not rows:
            self.status.setText('Connected · no submitted submissions on this page matching the search.')

    def refresh(self):
        if self.busy:
            return
        if self.client is None:
            self.restore_session()
            return
        self.offset = 0
        self.load_page()

    def page(self, delta):
        if self.client is None or self.busy:
            return
        self.offset = max(0, self.offset + delta)
        self.load_page()

    def load_page(self):
        client, search, offset = self.client, self.search.text(), self.offset
        identifier = self.selected
        self.fill(self.queue, [])
        self.clear_detail()

        def load():
            rows = client.submissions(search, offset)
            detail = client.submission(identifier) if identifier and any(r['id'] == identifier for r in rows) else None
            return rows, detail

        self.fetch(self.business(load), self.refreshed)

    def refreshed(self, result):
        rows, detail = result
        self.show_rows(rows)
        if detail:
            self.show_detail(detail)
            index = next(i for i, row in enumerate(rows) if row['id'] == detail['id'])
            self.queue.blockSignals(True)
            self.queue.selectRow(index)
            self.queue.blockSignals(False)

    def open_selected(self):
        index = self.queue.currentRow()
        if self.busy or self.client is None or not 0 <= index < len(self.rows):
            return
        identifier, client = self.rows[index]['id'], self.client
        self.clear_detail()
        self.fetch(self.business(lambda: client.submission(identifier)), self.show_detail)

    def show_detail(self, data):
        self.selected = data['id']
        names = {entry['id']: entry.get('card_name', '') for entry in data['entries']}
        parcels = {parcel['id']: parcel.get('reference', '') for parcel in data['parcels']}
        self.photo_rows = [photo for entry in data['entries'] for photo in entry.get('pre_shipment_photos', [])]
        self.fill(self.photos, [(names.get(photo.get('entry_id'), ''), photo.get('copy_number'), photo.get('side'), self.date(photo.get('uploaded_at'))) for photo in self.photo_rows])
        self.detail.setText(
            f"{data['reference']} · {data.get('customer_name', '')}\n"
            f"Declared: {data['declared_quantity']} · Received: {data['received_quantity']} · "
            f"Matched to declarations: {sum(card.get('status') == 'matched' for card in data['cards'])} · "
            f"Intake/reconciliation: {self.state(data['status'])} ({data['status']})\n"
            f"Commercial quote accepted: {data.get('commercially_accepted', False)} · "
            f"Payment: {data.get('payment_status', 'unknown')}\n"
            'Production link: unavailable (no local mapping). Backend grading-card UUIDs are not SLB-C IDs. '
            'This preview grants no inspection or payment clearance.')
        self.fill(self.expected, [(r.get(k) for k in ('card_name', 'game', 'expansion', 'card_number', 'language', 'quantity')) for r in data['entries']])
        self.fill(self.physical, [(card.get('reference'), names.get(card.get('entry_id'), 'Unidentified'), card.get('status'), parcels.get(card.get('parcel_id'), ''), card.get('notes', '')) for card in data['cards']])
        self.fill(self.parcels, [(parcel.get('reference'), parcel.get('status')) for parcel in data['parcels']])
        self.fill(self.issues, [(*[r.get(k) for k in ('kind', 'quantity', 'entry_id', 'card_id', 'status')],
                                str(r.get('notes', '')) + ' / ' + str(r.get('resolution') or '')) for r in data['discrepancies']])

    def open_labels(self):
        if not self.labels_button.isEnabled():
            return
        from .labels_ui import LabelDialog
        self.labels_dialog = LabelDialog(self.auth, self.selected, self)
        self.labels_dialog.show()

    def open_production(self):
        if not self.production_button.isEnabled():
            return
        from .production_ui import ProductionDialog
        from .orders import DEFAULT_PATH
        workstation = self.window()
        path = getattr(workstation, 'orders_path', DEFAULT_PATH)

        def reopen(identity):
            workstation.open_orders()
            workstation.orders_dialog.open_order(identity)

        self.production_dialog = ProductionDialog(
            self.auth, self.selected, path, self,
            open_order=reopen if hasattr(workstation, 'open_orders') else None)
        self.production_dialog.show()

    def open_intake(self):
        if self.client is None or self.auth is None or self.selected is None or self.busy:
            return
        from .intake_ui import PhysicalIntake
        try:
            self.intake_dialog = PhysicalIntake(self.auth,self.selected,self)
        except Exception:
            self.status.setText('Unable to open physical intake. Check local request-journal permissions; local orders are unchanged.')
            return
        self.intake_dialog.finished.connect(lambda result:self.refresh() if self.client is not None else None)
        self.intake_dialog.show()

    def open_photo(self):
        index = self.photos.currentRow()
        if self.busy or self.client is None or self.selected is None or not 0 <= index < len(self.photo_rows):
            return
        client, sid, photo = self.client, self.selected, self.photo_rows[index]
        self.photo_preview.clear()
        self.photo_preview.setText(f"Loading customer pre-shipment photo: declared copy {photo.get('copy_number')}, {photo.get('side')}.")
        self.fetch(self.business(lambda: client.photo(sid, photo)), self.show_photo)

    def photo_selection_changed(self):
        self.photo_preview.clear()
        self.photo_preview.setText('View the selected customer photograph to preview it.')
        self.controls()

    def show_photo(self, data):
        image = QPixmap()
        if not image.loadFromData(data):
            self.photo_preview.setText('Customer photograph preview unavailable.')
            return
        self.photo_preview.setPixmap(image.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    @staticmethod
    def state(value):
        return {'awaiting_receipt':'Awaiting receipt', 'partially_received':'Partially received', 'reconciliation_pending':'Reconciliation pending', 'reconciled':'Reconciled', 'on_hold':'On hold'}.get(value, value)

    @staticmethod
    def date(value):
        if not value:
            return '\u2014'
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M')
        except (ValueError, TypeError, AttributeError):
            return '\u2014'
