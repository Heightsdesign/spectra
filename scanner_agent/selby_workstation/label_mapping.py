"""Read-only local production mappings for label navigation; never migrates a registry."""

import sqlite3
from pathlib import Path

from .incoming import PreviewError


def mapped_orders(path):
    path = Path(path).resolve()
    if not path.is_file():
        return []
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        if db.execute("PRAGMA user_version").fetchone()[0] != 2:
            return []
        registry = db.execute("SELECT id FROM bridge_registry WHERE singleton=1").fetchone()[0]
        result = []
        for row in db.execute(
            "SELECT b.* FROM bridge_orders b JOIN orders o ON o.id=b.order_id ORDER BY o.number"
        ):
            record = dict(row, registry_id=registry, path=str(path))
            record["cards"] = [
                dict(c)
                for c in db.execute(
                    "SELECT pc_id,pc,card_id FROM bridge_cards WHERE scope=? AND sid=? AND order_id=? ORDER BY card_id",
                    (row["scope"], row["sid"], row["order_id"]),
                )
            ]
            result.append(record)
        return result


def checked_labels(context, client):
    current = next(
        (row for row in mapped_orders(context["path"]) if row["order_id"] == context["order_id"]),
        None,
    )
    if current != context or not context["confirmed"]:
        raise PreviewError(
            "Local production mapping changed or is unconfirmed. Refresh Labels; no identities were changed."
        )
    if client.connection.backend_origin != context["scope"]:
        raise PreviewError(
            "This order belongs to another backend origin. Select the original connection in Settings."
        )
    snapshot = client.production(context["sid"])
    data, binding = snapshot["submission"], snapshot["binding"]
    pairs = {card["pc_id"]: card["card_id"] for card in context["cards"]}
    refs = {card["pc_id"]: card["pc"] for card in context["cards"]}
    active = {
        str(card["id"]): card["reference"] for card in data["cards"] if card["status"] != "voided"
    }
    if (
        str(data["id"]) != context["sid"]
        or data["reference"] != context["sp"]
        or not binding
        or str(binding["registry_id"]) != context["registry_id"]
        or binding["local_order_id"] != context["order_id"]
        or binding["cards"] != pairs
        or active != refs
    ):
        raise PreviewError(
            "Local/backend production mappings disagree. Restore or review the original mapping; printing is disabled."
        )
    state = client.labels(context["sid"])
    if state["reference"] != context["sp"] or any(
        label["kind"] == "physical_card" and label["reference"] not in refs.values()
        for label in state["labels"]
    ):
        raise PreviewError(
            "Backend label identities disagree with the selected order. Refresh and review the mapping."
        )
    return state
