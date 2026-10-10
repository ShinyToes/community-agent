"""Evaluate a manually labeled JSON study; never calls a model or crawler."""

import argparse
import json
from pathlib import Path

from community_research.evaluation import evaluate_study


def main():
    parser = argparse.ArgumentParser(description='Score P5 strategies within an explicitly labeled sample')
    parser.add_argument('study', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = evaluate_study(json.loads(args.study.read_text(encoding='utf-8')))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(payload, encoding='utf-8')
    else:
        print(payload, end='')


if __name__ == '__main__':
    main()
