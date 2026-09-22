import efferents.cli as cli


def test_serve_subcommand_parses():
    parser = cli.build_parser()
    args = parser.parse_args(["serve", "--lab-root", "lab", "--port", "9001", "--no-open"])
    assert args.func is cli._cmd_serve
    assert args.lab_root == "lab"
    assert args.port == 9001
    assert args.no_open is True
    assert args.paused_demo is False


def test_serve_defaults():
    parser = cli.build_parser()
    args = parser.parse_args(["serve"])
    assert args.lab_root == "lab"
    assert args.port == 8800
    assert args.no_open is False
    assert args.paused_demo is False


def test_serve_paused_demo_parses():
    args = cli.build_parser().parse_args(["serve", "--paused-demo"])
    assert args.paused_demo is True


def test_cmd_serve_loads_config_and_starts(tmp_path, monkeypatch):
    (tmp_path / "hypothesis.md").write_text(
        "---\nslug: t\nfalsifiability_gate: passed\nstatus: active\n---\n# H\n"
    )
    (tmp_path / "lab.yaml").write_text(
        "lab_id: t\ndomain: d\n"
        "source:\n  dir: ./src/\n"
        "executor:\n  run_command: 'python -m x --config {config_path}'\n"
        "  config_template: default.yaml\n"
        "metrics:\n  headline:\n    column: loss\n    direction: min\n"
        "  panels:\n    - { column: loss, label: Loss }\n"
        "budget:\n  daily_cap_usd: 1.0\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "default.yaml").touch()

    called = {}

    def fake_serve(lab_root, port, open_browser, *, paused_demo):
        called["lab_root"] = str(lab_root)
        called["port"] = port
        called["open_browser"] = open_browser
        called["paused_demo"] = paused_demo

    monkeypatch.setattr("efferents.dashboard.server.serve", fake_serve)

    import argparse
    args = argparse.Namespace(lab_root=str(tmp_path), port=8800, no_open=True)
    rc = cli._cmd_serve(args)
    assert rc == 0
    assert called["port"] == 8800
    assert called["open_browser"] is False
    assert called["paused_demo"] is False


def test_cmd_serve_starts_entry_page_without_existing_lab(tmp_path, monkeypatch):
    called = {}

    def fake_serve(lab_root, port, open_browser, *, paused_demo):
        called["lab_root"] = lab_root
        called["port"] = port
        called["paused_demo"] = paused_demo

    monkeypatch.setattr("efferents.dashboard.server.serve", fake_serve)

    import argparse
    args = argparse.Namespace(
        lab_root=str(tmp_path / "not-connected"),
        port=8800,
        no_open=True,
    )
    rc = cli._cmd_serve(args)

    assert rc == 0
    assert called["lab_root"] is None


def test_serve_cluster_flags_dispatch_to_cluster_server(tmp_path, monkeypatch):
    called = {}

    def fake_serve_cluster(root, *, host, port, open_browser):
        called.update(root=root, host=host, port=port, open_browser=open_browser)
        return 0

    monkeypatch.setattr("efferents.cluster.server.serve_cluster", fake_serve_cluster)
    rc = cli.main(["serve", "--cluster", str(tmp_path), "--host", "0.0.0.0",
                   "--port", "8801", "--no-open"])
    assert rc == 0
    assert called == {"root": tmp_path.resolve(), "host": "0.0.0.0", "port": 8801,
                      "open_browser": False}


def test_cluster_init_and_check_commands(tmp_path, monkeypatch, capsys):
    root = tmp_path / "c"
    assert cli.main(["cluster", "init", str(root)]) == 0
    assert (root / "cluster.yaml").exists()
    out = capsys.readouterr().out
    assert "wrote" in out and "efferents cluster check" in out
    # No hosted tracks is valid because a participant harness can build a new
    # executor; missing credentials and Popper still fail readiness.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("POPPER_PROBE_REPO", str(tmp_path / "nope"))
    assert cli.main(["cluster", "check", str(root)]) == 1
    captured = capsys.readouterr()
    assert "tracks: none loaded" in captured.out and "popper-probe" in captured.err
