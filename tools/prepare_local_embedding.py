"""Explicitly download a local ONNX embedding model into the project runtime cache."""

import argparse
from pathlib import Path

from fastembed import TextEmbedding


def main():
    parser = argparse.ArgumentParser(description='Prepare the optional local Chinese embedding model')
    parser.add_argument('--model', default='BAAI/bge-small-zh-v1.5')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cache = root / '.runtime' / 'fastembed'
    cache.mkdir(parents=True, exist_ok=True)
    model = TextEmbedding(model_name=args.model, cache_dir=str(cache))
    width = len(next(iter(model.query_embed('中文检索'))))
    print(f'Model ready in {cache}; vector dimensions: {width}')


if __name__ == '__main__':
    main()
