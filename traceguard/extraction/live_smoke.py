"""Opt-in real extraction smoke check: python -m traceguard.extraction.live_smoke."""

import os

from traceguard.extraction.openai_provider import OpenAIExtractionProvider


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("SKIPPED: OPENAI_API_KEY is not configured; no external call was made.")
        return 0

    provider = OpenAIExtractionProvider()
    result = provider.extract(
        "New customer ACCT-771 requests 12 units of PART-Z9, "
        "left with security after 4 PM."
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
