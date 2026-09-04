from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_contains_no_secret_or_direct_external_boundaries():
    frontend = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "app" / "static").iterdir()
        if path.is_file()
    ).casefold()

    for forbidden in (
        "razorpay_key_secret",
        "razorpay_key_id",
        "localhost:11434",
        "/api/chat",
        "/api/generate",
        "api.razorpay",
        "razorpay.com",
        "/mcp",
    ):
        assert forbidden not in frontend


def test_dotenv_is_ignored_by_git():
    result = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0
