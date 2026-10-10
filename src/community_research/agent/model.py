import json
import os
import re
from urllib.parse import urlparse

from dotenv import dotenv_values
import httpx


class ModelError(Exception):
    pass


def parse_action(raw):
    """Accept only a complete object, optionally wrapped in one JSON code fence."""
    text = raw.strip().lstrip('\ufeff').strip()
    fenced = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    action = json.loads(text, object_pairs_hook=unique_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))
    # Unambiguous missing discriminator only; normal answer/citation validation still applies.
    if isinstance(action, dict) and set(action) == {'outcome', 'paragraphs', 'limitations'}:
        action = {'action': 'answer', **action}
    if isinstance(action, dict) and set(action) == {'action', 'arguments'} and isinstance(action['action'], str) and action['action'] in ('search_posts', 'search_comments', 'read_evidence', 'compare_sources', 'source_versions'):
        action = {'action': 'tool', 'name': action['action'], 'arguments': action['arguments']}
    return action


class ChatModel:
    """Configured chat-completions transport; structured actions validated by harness."""
    def __init__(self, root):
        values = {**dotenv_values(root / '.env.research'), **os.environ}
        self.base = (values.get('RESEARCH_BASE_URL') or '').rstrip('/')
        self.key = values.get('RESEARCH_API_KEY') or ''
        self.model = values.get('RESEARCH_MODEL') or ''
        self.diagnostics = {}

    @property
    def configured(self):
        return bool(self.base and self.key and self.model)

    async def complete(self, messages):
        self.diagnostics = {}
        if not self.configured:
            raise ModelError('model_not_configured')
        parsed = urlparse(self.base)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1'))):
            raise ModelError('invalid_model_endpoint')
        try:
            payload = {'model': self.model, 'messages': messages, 'max_tokens': 4096, 'stream': False}
            if parsed.hostname == 'api.deepseek.com':
                payload.update(response_format={'type': 'json_object'}, thinking={'type': 'disabled'})
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                async with client.stream('POST', self.base + '/chat/completions', headers={'Authorization': 'Bearer ' + self.key},
                                         json=payload) as response:
                    if response.status_code in (401, 403):
                        raise ModelError('model_auth_failed')
                    if response.status_code == 429:
                        raise ModelError('model_rate_limited')
                    if response.status_code >= 400:
                        raise ModelError('model_request_rejected' if response.status_code < 500 else 'model_service_error')
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 2_000_000:
                            raise ModelError('model_response_too_large')
            envelope = json.loads(data)
            choice = envelope['choices'][0]
            content = choice['message']['content']
            reason = choice.get('finish_reason')
            self.diagnostics = {'finish_reason': reason if reason in ('stop', 'length', 'content_filter', 'tool_calls') else 'unknown',
                                'content_chars': len(content) if isinstance(content, str) else 0}
            if reason == 'length':
                raise ModelError('model_output_truncated')
            if reason == 'content_filter':
                raise ModelError('model_content_filtered')
            if not isinstance(content, str):
                raise ValueError()
            if not content.strip():
                raise ModelError('model_empty_response')
            return content
        except httpx.TimeoutException:
            raise ModelError('model_timeout') from None
        except httpx.RequestError:
            raise ModelError('model_connection_failed') from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelError('model_response_invalid') from None
