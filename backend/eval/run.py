"""Produce the eval scorecard artifact.

    cd backend && python -m eval.run [--output eval-scorecard.json]

Exit code 0 when every deterministic gate passes, 1 otherwise — suitable as a
CI step. The same gates are enforced under pytest by
`tests/test_eval_scorecard.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from eval.scorecard import run_all


async def _main(output: str) -> int:
    scorecard = await run_all()
    with open(output, "w") as fh:
        json.dump(scorecard.to_dict(), fh, indent=2)

    width = max(len(r.name) for r in scorecard.results)
    for result in scorecard.results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status}  {result.name:<{width}}  score={result.score:.2f}  {result.summary}")
    print(f"\nscorecard written to {output}")
    print("overall:", "PASS" if scorecard.passed else "FAIL")
    return 0 if scorecard.passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="eval-scorecard.json")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.output)))


if __name__ == "__main__":
    main()
