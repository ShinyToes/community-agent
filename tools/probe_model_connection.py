"""Check configured chat-model connectivity without sending project or user content."""

import asyncio
from pathlib import Path

from community_research.agent.model import ChatModel, ModelError


async def main():
    model = ChatModel(Path(__file__).resolve().parents[1])
    try:
        reply = await model.complete([{'role': 'user', 'content': 'Return a JSON object with one key: ok = true.'}])
    except ModelError as exc:
        print(f'model_error={exc}')
        raise SystemExit(1) from None
    print(f'model_connected=true reply_chars={len(reply)} finish={model.diagnostics.get("finish_reason")}')


if __name__ == '__main__':
    asyncio.run(main())
