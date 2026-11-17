"""The results of the evals and the red team as a short report for the CI run's summary page.

    python -m redteam.summary eval-results.json redteam-results.json

A missing file is reported, not hidden: it means that part did not finish.
"""

import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any] | None:
    data: dict[str, Any] | None = json.loads(path.read_text()) if path.exists() else None
    return data


def render(evals: dict[str, Any] | None, redteam: dict[str, Any] | None) -> str:
    lines = ["## Model checks", ""]
    if evals is None:
        lines.append("**Evals: did not finish.**")
    else:
        status = "passed" if evals["ok"] else "FAILED"
        lines.append(
            f"**Evals {status}:** quality {evals['quality']:.1%} (needs {evals['threshold']:.0%}), "
            f"safety failures {len(evals['failed_safety'])}, ${evals['cost_usd']:.4f}"
        )
        lines += [
            f"- `{case['case_id']}` {case['passed']}/{case['repeats']}: "
            + " ".join(f"`{miss}`" for miss in case["misses"])
            for case in evals["cases"]
            if case["passed"] < case["repeats"]
        ]
    lines.append("")
    if redteam is None:
        lines.append("**Red team: did not finish.**")
    else:
        attacks = redteam["attacks"]
        succeeded = [a for a in attacks if a["verdict"] == "SUCCEEDED"]
        lines.append(
            f"**Red team:** {len(attacks) - len(succeeded)}/{len(attacks)} attacks blocked, "
            f"{redteam['repeats']} repeats each"
        )
        lines += [
            f"- **{a['threat']} `{a['id']}` succeeded:** " + "; ".join(a["findings"])
            for a in succeeded
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> None:
    print(render(_load(Path(argv[0])), _load(Path(argv[1]))), end="")


if __name__ == "__main__":
    main(sys.argv[1:])
