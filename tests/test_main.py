from src.app.main import run


def test_run_smoke(capsys):
    run()
    captured = capsys.readouterr()
    assert "AI x Finance" in captured.out
