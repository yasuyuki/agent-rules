"""Create a harmless proof using this skill's relative support resource."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--challenge", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    skill = (Path(__file__).parent / "support.txt").read_text(encoding="utf-8").strip()
    if not skill.startswith("SKILL_"):
        parser.error("invalid support file")
    args.output.write_text(json.dumps({"skill": skill, "challenge": args.challenge}), encoding="utf-8")


if __name__ == "__main__":
    main()
