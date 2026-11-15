"""Tests for non-destructive graph WAL recovery."""

from pathlib import Path

from kairos import graph_memory


def test_is_wal_error():
    assert graph_memory._is_wal_error(
        "Runtime exception: Corrupted wal file. Read out invalid WAL record type.")
    assert not graph_memory._is_wal_error("disk full")
    assert not graph_memory._is_wal_error("")


def test_quarantine_wal_preserves_data(tmp_path):
    db = tmp_path / "graph.lbdb"
    db.write_bytes(b"fake-db-bytes")
    wal = tmp_path / "graph.lbdb.wal"
    wal.write_bytes(b"corrupt-wal")

    res = graph_memory.quarantine_wal(str(db))

    assert res["backup"] and Path(res["backup"]).exists()
    assert Path(res["backup"]).read_bytes() == b"fake-db-bytes"
    assert res["quarantined"] and Path(res["quarantined"]).exists()
    assert Path(res["quarantined"]).read_bytes() == b"corrupt-wal"
    # main DB preserved; corrupt WAL moved aside (nothing deleted)
    assert db.exists() and db.read_bytes() == b"fake-db-bytes"
    assert not wal.exists()


def test_quarantine_no_backup(tmp_path):
    db = tmp_path / "graph.lbdb"
    db.write_bytes(b"x")
    res = graph_memory.quarantine_wal(str(db), keep_backup=False)
    assert res["backup"] is None and res["quarantined"] is None
