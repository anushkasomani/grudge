"""Thin wrapper over Sibyl Memory.

Two things this layer guarantees, both of which the demo depends on:

1. ``--no-memory`` is NOT a stub. It points MemoryClient at a throwaway
   empty database, so every call the agent makes is a real Sibyl call that
   simply finds nothing. The agent is never told it has no memory; it just
   gets no hits. That is what makes the "delete the memory layer" test honest.

2. ``update_dossier`` is read-modify-write. Sibyl's ``set_entity`` REPLACES
   the body wholesale (verified against v0.8.0), so a blind ``set_entity``
   silently destroys the tactic and bluff ledgers - the exact data the whole
   project rests on.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sibyl_memory_client import MemoryClient
from sibyl_memory_client.exceptions import NotFoundError

CAT_DOSSIER = "vendor_dossier"
CAT_NEGOTIATION = "negotiation_record"

DEFAULT_SIBYL_DB = Path("~/.sibyl-memory/memory.db")
DEFAULT_TENANT_ID = "grudge-acme"


def sibyl_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve the Sibyl memory database used by normal Grudge sessions."""
    return Path(db_path or os.getenv("SIBYL_MEMORY_DB") or DEFAULT_SIBYL_DB).expanduser()


class GrudgeMemory:
    """Sibyl-backed store for vendor dossiers and negotiation records."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        tenant_id: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self._tempdir: str | None = None

        if enabled:
            path = sibyl_db_path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            # A real Sibyl DB that is guaranteed empty: same code path,
            # same API calls, zero recall.
            self._tempdir = tempfile.mkdtemp(prefix="grudge-nomem-")
            path = Path(self._tempdir) / "empty.db"

        self.db_path = path
        self.tenant_id = tenant_id or os.getenv("SIBYL_TENANT_ID") or DEFAULT_TENANT_ID
        self.client = MemoryClient.local(str(path), tenant_id=self.tenant_id)

    # ---------- vendor dossier (WARM entity tier) ----------

    def get_dossier(self, vendor_id: str) -> dict[str, Any] | None:
        """Return the vendor's learned dossier body, or None on a cold start."""
        try:
            row = self.client.get_entity(CAT_DOSSIER, vendor_id)
        except NotFoundError:
            return None
        return row.get("body")

    def put_dossier(self, vendor_id: str, body: dict[str, Any]) -> None:
        self.client.set_entity(CAT_DOSSIER, vendor_id, body)

    def update_dossier(self, vendor_id: str, mutate) -> dict[str, Any]:
        """Read-modify-write a dossier.

        ``mutate`` receives the existing body (or a fresh skeleton) and
        returns the body to persist. Never call set_entity directly for a
        dossier: Sibyl replaces bodies rather than merging them.
        """
        current = self.get_dossier(vendor_id) or new_dossier(vendor_id)
        updated = mutate(current)
        self.put_dossier(vendor_id, updated)
        return updated

    def list_dossiers(self) -> list[dict[str, Any]]:
        return self.client.list_entities(CAT_DOSSIER, limit=200)

    # ---------- negotiation records (WARM entity tier, composite key) ----------

    def put_negotiation(self, vendor_id: str, negotiation_id: str, body: dict[str, Any]) -> None:
        """Persist one immutable negotiation record.

        The name is composite because Sibyl enforces UNIQUE(tenant, category,
        name); keying on vendor_id alone would make each renewal overwrite the
        last one.
        """
        self.client.set_entity(CAT_NEGOTIATION, f"{vendor_id}__{negotiation_id}", body)

    def get_negotiation(self, vendor_id: str, negotiation_id: str) -> dict[str, Any] | None:
        try:
            row = self.client.get_entity(CAT_NEGOTIATION, f"{vendor_id}__{negotiation_id}")
        except NotFoundError:
            return None
        return row.get("body")

    def past_negotiations(self, vendor_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """All prior negotiation records for a vendor, oldest first."""
        rows = self.client.list_entities(CAT_NEGOTIATION, limit=200)
        bodies = [
            r["body"]
            for r in rows
            if str(r.get("name", "")).startswith(f"{vendor_id}__") and r.get("body")
        ]
        bodies.sort(key=lambda b: b.get("started_at", ""))
        return bodies[-limit:]

    # ---------- journal (COLD tier) ----------

    def log_round(
        self,
        *,
        evaluated: list[str],
        acted: list[str],
        forward: list[str],
        extra: dict[str, Any],
    ) -> str:
        """Append one reasoning step to the journal. This is the audit trail."""
        return self.client.write_event(
            evaluated=evaluated, acted=acted, forward=forward, extra=extra
        )

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.client.read_events(limit=limit)

    # ---------- search (FTS5) ----------

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return list(self.client.search(query, limit=limit))

    # ---------- lifecycle ----------

    def wipe(self) -> None:
        """Delete the memory store outright. Used by `grudge wipe-memory`."""
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.db_path) + suffix)
            if p.exists():
                p.unlink()

    def close(self) -> None:
        if self._tempdir:
            shutil.rmtree(self._tempdir, ignore_errors=True)
            self._tempdir = None

    def __enter__(self) -> "GrudgeMemory":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def new_dossier(vendor_id: str) -> dict[str, Any]:
    """The empty skeleton for a vendor we have never negotiated with."""
    return {
        "vendor_id": vendor_id,
        "negotiations": [],
        "list_price_history": [],
        "best_settled": None,
        "last_settled": None,
        "floor_estimate": None,
        "tactic_ledger": {},
        "bluff_ledger": {},
        "concession_curve": {},
        "counterparty_notes": [],
    }
