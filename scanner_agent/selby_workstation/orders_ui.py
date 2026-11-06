"""Orders workbench, independent of the active inspection's unsaved state."""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .orders import CARD_TRANSITIONS, ORDER_TRANSITIONS, OrderStore
from .form_widgets import FormComboBox as QComboBox, FormSpinBox as QSpinBox


class OrdersDialog(QDialog):
    def __init__(self, workstation, path):
        super().__init__(workstation)
        self.workstation = workstation
        self.store = OrderStore(path)
        self.order_id = None
        self.card_id = None
        self.setWindowTitle("SELBY V0.5a · Orders and individual cards")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(1100, 900)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Local registry: {path}"))
        self.operator = QLineEdit(workstation.operator.text())
        self.operator.setPlaceholderText("Operator identity for registry actions")
        root.addWidget(self.operator)
        searches = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search order ID or customer name")
        searches.addWidget(self.search)
        self.card_search = QLineEdit()
        self.card_search.setPlaceholderText("SLB-C-000001")
        searches.addWidget(self.card_search)
        self.button(searches, "Find card", self.find_card)
        root.addLayout(searches)
        self.orders = self.table(root, ["Order", "Customer", "Status", "Cards"])
        self.orders.cellClicked.connect(lambda row, _: self.run(
            lambda: self.open_order(self.orders.item(row, 0).text())))
        form = QFormLayout()
        self.customer = QLineEdit()
        self.contact = QLineEdit()
        self.external = QLineEdit()
        self.notes = QLineEdit()
        for label, field in (("Customer", self.customer), ("Contact", self.contact),
                             ("External reference", self.external), ("Order notes", self.notes)):
            form.addRow(label, field)
        root.addLayout(form)
        actions = QHBoxLayout()
        self.button(actions, "New order / clear form", self.clear_order)
        self.button(actions, "Create order", self.create_order)
        self.button(actions, "Update selected customer", self.update_customer)
        self.count = QSpinBox()
        self.count.setRange(1, 1000)
        actions.addWidget(self.count)
        self.metadata = QLineEdit()
        self.metadata.setPlaceholderText("Optional card description (applies to batch)")
        actions.addWidget(self.metadata)
        self.button(actions, "Add cards", self.add_cards)
        root.addLayout(actions)
        self.order_label = QLabel("Select or create an order")
        root.addWidget(self.order_label)
        self.bridge_label = QLabel("Production mapping: unverified local identity")
        self.bridge_label.setTextFormat(Qt.TextFormat.PlainText)
        self.bridge_label.setWordWrap(True)
        root.addWidget(self.bridge_label)
        self.cards = self.table(root, ["Card", "Position", "Status", "Description", "Session", "Backend PC", "Mapping"])
        self.cards.cellClicked.connect(lambda row, _: self.run(
            lambda: self.open_card(self.cards.item(row, 0).text())))
        statuses = QHBoxLayout()
        self.order_status = QComboBox()
        self.order_status.addItems(ORDER_TRANSITIONS)
        statuses.addWidget(self.order_status)
        self.button(statuses, "Set order status", lambda: self.set_status(False, confirm=True))
        self.card_status = QComboBox()
        self.card_status.addItems(CARD_TRANSITIONS)
        statuses.addWidget(self.card_status)
        self.button(statuses, "Set card status", lambda: self.set_status(True, confirm=True))
        self.correction = QCheckBox("Authorized correction")
        statuses.addWidget(self.correction)
        root.addLayout(statuses)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Pairing explanation / correction or cancellation reason")
        root.addWidget(self.reason)
        links = QHBoxLayout()
        self.button(links, "Associate saved grading session…", lambda: self.link_session(confirm=True))
        self.button(links, "Verify associated evidence", self.verify_session)
        self.button(links, "Unlink (authorized correction)", lambda: self.unlink_session(confirm=True))
        self.button(links, "Show order audit", self.show_order)
        root.addLayout(links)
        workflow = QHBoxLayout()
        self.print_labels_button = self.button(workflow, 'Print labels / preview…',
                    lambda: workstation.desktop.open_labels(self.order_id))
        self.print_labels_button.setEnabled(False)
        self.print_labels_button.setToolTip('Select an order with a confirmed backend production mapping. Labels creates no identities.')
        self.button(workflow, "Open linked inspection", lambda: workstation.desktop.open_card_workflow())
        self.button(workflow, "Open linked grading", lambda: workstation.desktop.open_card_workflow(True))
        self.button(workflow, "Inspection tools / open scan…",
                    lambda: workstation.desktop.navigate("Inspection"))
        root.addLayout(workflow)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        root.addWidget(self.details)
        self.message = QLabel("Changes commit immediately; IDs are permanent. No certification issued.")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        self.search.textChanged.connect(lambda _: self.run(self.refresh))
        self.card_search.returnPressed.connect(lambda: self.run(self.find_card))
        self.refresh()

    def run(self, callback):
        return self.workstation.guard(callback)

    def button(self, layout, text, callback):
        button = QPushButton(text)
        button.setAutoDefault(False)
        button.clicked.connect(lambda: self.run(callback))
        layout.addWidget(button)
        return button

    @staticmethod
    def table(layout, labels):
        table = QTableWidget(0, len(labels))
        table.setHorizontalHeaderLabels(labels)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(table)
        return table

    @staticmethod
    def fill(table, rows):
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()

    def refresh(self):
        self.fill(self.orders, [(o["id"], o["customer_name"], o["status"], o["card_count"])
                                for o in self.store.search_orders(self.search.text())])
        if self.orders.rowCount() == 0:
            self.message.setText("No matching orders. Clear the search or choose New order / clear form to create one.")

    def clear_order(self):
        self.order_id = self.card_id = None
        for field in (self.customer, self.contact, self.external, self.notes):
            field.clear()
        self.cards.setRowCount(0)
        self.details.clear()
        self.order_label.setText("New order")
        self.bridge_label.setText("Production mapping: unverified local identity")
        self.print_labels_button.setEnabled(False)
        self.print_labels_button.setToolTip('Select an order with a confirmed backend production mapping.')
        self.workstation.desktop.update_context()

    def customer_values(self):
        return dict(customer_name=self.customer.text(), contact=self.contact.text(),
                    external_reference=self.external.text(), notes=self.notes.text(),
                    operator=self.operator.text())

    def create_order(self):
        if self.order_id:
            raise ValueError("Choose New order / clear form before creating another order")
        order = self.store.create_order(**self.customer_values())
        self.refresh()
        self.open_order(order["id"])

    def update_customer(self):
        self.require_order()
        self.store.update_customer(self.order_id, **self.customer_values())
        self.refresh()
        self.open_order(self.order_id)

    def require_order(self):
        if not self.order_id:
            raise ValueError("Select an order first")

    def require_card(self):
        if not self.card_id:
            raise ValueError("Select an individual card first")

    def open_order(self, identity):
        order = self.store.get_order(identity)
        self.order_id, self.card_id = identity, None
        for field, key in ((self.customer, "customer_name"), (self.contact, "contact"),
                           (self.external, "external_reference"), (self.notes, "notes")):
            field.setText(order[key])
        self.order_status.setCurrentText(order["status"])
        self.order_label.setText(f"{identity} · {order['status']} · {order['card_count']} cards")
        with self.store.connection() as db:
            bridge = None
            physical = {}
            if db.execute('PRAGMA user_version').fetchone()[0] == 2:
                bridge = db.execute('SELECT * FROM bridge_orders WHERE order_id=?', (identity,)).fetchone()
                physical = {r['card_id']: r['pc'] for r in db.execute(
                    'SELECT card_id,pc FROM bridge_cards WHERE order_id=?', (identity,))}
            self.bridge_label.setText(
                f"SP: {bridge['sp']} · ORD: {identity} · Mapping: {'confirmed' if bridge['confirmed'] else 'PENDING backend confirmation'}\n"
                "Reconciliation/payment/inspection eligibility: refresh the production bridge online; local status is not clearance."
                if bridge else "Production mapping: unverified local identity")
            self.print_labels_button.setEnabled(bool(bridge and bridge['confirmed']))
            self.print_labels_button.setToolTip('Open Labels for this exact ORD/SP mapping; sign-in and current backend eligibility are checked online.'
                if bridge and bridge['confirmed'] else 'This local order has no confirmed backend mapping. Complete the existing production bridge; Labels never creates or confirms identities.')
        self.fill(self.cards, [(c["id"], c["position"], c["status"],
                               c["metadata"].get("description", ""), c["session_id"] or "",
                               physical.get(c['id'], ''),
                               ('confirmed' if bridge['confirmed'] else 'pending') if bridge and c['id'] in physical else 'unverified')
                              for c in self.store.cards(identity)])
        self.show_order()
        if not order["card_count"]:
            self.message.setText("This order has no cards. Set a count and choose Add cards.")
        self.workstation.desktop.update_context()

    def show_order(self):
        self.require_order()
        self.show_record(self.store.get_order(self.order_id))

    def show_record(self, record):
        with self.store.connection() as db:
            mapping = None
            if db.execute('PRAGMA user_version').fetchone()[0] == 2:
                row = db.execute('SELECT * FROM bridge_cards WHERE card_id=?', (record['id'],)).fetchone()
                mapping = dict(row) if row else None
        self.details.setPlainText(json.dumps(dict(record=record,
            production_mapping=mapping,
            audit=self.store.history(record["id"])), indent=2, ensure_ascii=False))

    def open_card(self, identity):
        card = self.store.get_card(identity)
        self.open_order(card["order_id"])
        self.card_id = identity
        self.card_status.setCurrentText(card["status"])
        self.show_record(card)
        self.message.setText("Saved grading session linked. Use Open linked inspection / grading to resume."
                             if card["session_reference"] else
                             "No grading session linked. Use Inspection tools to open a scan or saved session, "
                             "then explicitly associate a saved grading dossier.")
        self.workstation.desktop.update_context()

    def find_card(self):
        self.open_card(self.store.search_card(self.card_search.text())["id"])

    def add_cards(self):
        self.require_order()
        self.store.add_cards(self.order_id, self.count.value(),
                             metadata={"description": self.metadata.text()},
                             operator=self.operator.text())
        self.refresh()
        self.open_order(self.order_id)

    def confirm(self, message):
        return QMessageBox.question(self, "Confirm registry action", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes

    def set_status(self, card, confirm=False):
        self.require_card() if card else self.require_order()
        identity = self.card_id if card else self.order_id
        status = self.card_status.currentText() if card else self.order_status.currentText()
        if confirm and (self.correction.isChecked() or status in ("cancelled", "completed", "shipped")):
            if not self.confirm(f"Change {identity} to {status}?\nReason: {self.reason.text()}\n"
                                "This action will be retained in audit history."):
                return
        self.store.transition(identity, status, self.operator.text(), self.reason.text(),
                              self.correction.isChecked())
        order_id = self.order_id
        self.refresh()
        self.open_order(order_id)
        if card:
            self.open_card(identity)

    def link_session(self, confirm=False):
        self.require_card()
        path, _ = QFileDialog.getOpenFileName(self, "Select saved grading session", "",
                                              "Inspection session (*.json)")
        if path:
            if confirm and not self.confirm(f"Associate {self.card_id} with this saved dossier?\n{path}\n"
                                             "Confirm the physical card pairing. Existing evidence stays unchanged."):
                return
            self.store.associate_session(self.card_id, Path(path), self.operator.text(),
                                         self.reason.text())
            self.open_card(self.card_id)

    def unlink_session(self, confirm=False):
        self.require_card()
        if confirm and not self.confirm(f"Remove the saved-session association from {self.card_id}?\n"
                                         "An authorized operator and correction reason are required."):
            return
        self.store.unlink_session(self.card_id, self.operator.text(), self.reason.text())
        self.open_card(self.card_id)

    def verify_session(self):
        self.require_card()
        self.store.verify_association(self.card_id)
        self.message.setText("Associated saved session and recorded evidence verified.")
