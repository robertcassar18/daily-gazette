import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "generate_digest",
    ROOT / "scripts" / "generate_digest.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GenerateDigestTests:
    def test_resolve_model_prefers_explicit_model(self):
        model = module.resolve_model("dummy-key", preferred_model="gemini-2.0-flash")
        assert model == "gemini-2.0-flash"

    def test_format_gemini_error_mentions_quota_and_free_tier(self):
        message = module.format_gemini_error(
            429,
            '{"error":{"message":"Resource has been exhausted"}}',
        )
        lowered = message.lower()
        assert "429" in message
        assert "quota" in lowered
        assert "free tier" in lowered
