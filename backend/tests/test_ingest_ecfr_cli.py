"""CLI smoke tests — use sys.argv + monkeypatched service."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _run(args, monkeypatch, tmp_path, fake_service=None, fake_fetch=None, fake_parse=None):
    from scripts import ingest_ecfr as cli

    if fake_service:
        monkeypatch.setattr(cli, "ingest_ecfr_source", fake_service)
    if fake_fetch:
        monkeypatch.setattr(cli, "fetch_ecfr_xml", fake_fetch)
        monkeypatch.setattr(cli, "resolve_current_date", lambda **kw: "2025-10-01")
    if fake_parse:
        monkeypatch.setattr(cli, "parse_ecfr_xml", fake_parse)

    monkeypatch.setattr(cli, "_get_connection", lambda: _FakeConn())
    monkeypatch.setattr(cli, "get_embedding_provider", lambda: _FakeEmbed())
    monkeypatch.setattr(sys, "argv", ["ingest_ecfr.py", *args])
    return cli.main()


class _FakeConn:
    def close(self): pass
    def cursor(self): raise AssertionError("should not hit DB in dry-run")


class _FakeEmbed:
    dim = 8
    def embed(self, t): return [0.0] * self.dim
    def embed_batch(self, ts): return [self.embed(t) for t in ts]


def test_single_invocation_calls_service(monkeypatch, tmp_path):
    calls = []
    def fake(conn, **kwargs):
        calls.append(kwargs)
        return "sid-123"

    rc = _run(["--title", "36", "--part", "800"], monkeypatch, tmp_path, fake_service=fake)
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["title"] == 36
    assert calls[0]["part"] == "800"
    assert calls[0]["trigger"] == "cli"


def test_dry_run_does_not_hit_db(monkeypatch, tmp_path):
    def fake_fetch(**kw): return b"<DIV5 N='800' TYPE='PART'><HEAD>Hi</HEAD></DIV5>"
    def fake_parse(blob): return ([], [])

    rc = _run(
        ["--title", "36", "--part", "800", "--dry-run"],
        monkeypatch, tmp_path,
        fake_fetch=fake_fetch, fake_parse=fake_parse,
    )
    assert rc == 0


def test_batch_mode_reads_yaml(monkeypatch, tmp_path):
    yaml_path = tmp_path / "parts.yaml"
    yaml_path.write_text(
        "- title: 36\n  part: '800'\n- title: 23\n  part: '771'\n"
    )
    calls = []
    def fake(conn, **kwargs):
        calls.append((kwargs["title"], kwargs["part"]))
        return f"sid-{kwargs['title']}-{kwargs['part']}"

    rc = _run(
        ["--from-file", str(yaml_path)],
        monkeypatch, tmp_path, fake_service=fake,
    )
    assert rc == 0
    assert calls == [(36, "800"), (23, "771")]


def test_batch_continues_after_failure(monkeypatch, tmp_path, capsys):
    yaml_path = tmp_path / "parts.yaml"
    yaml_path.write_text(
        "- title: 36\n  part: '800'\n- title: 23\n  part: '771'\n"
    )
    def fake(conn, **kwargs):
        if kwargs["part"] == "800":
            raise RuntimeError("simulated failure")
        return "sid-ok"

    rc = _run(
        ["--from-file", str(yaml_path)],
        monkeypatch, tmp_path, fake_service=fake,
    )
    assert rc != 0  # non-zero because one failed
    out = capsys.readouterr().out
    assert "800" in out and "771" in out
