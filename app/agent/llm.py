import json
import httpx
from flask import current_app


class ModelUnavailable(ValueError):
    pass


class LLMClient:
    def complete(self, messages, tools=None, *, json_mode=False):
        key = current_app.config.get('LLM_API_KEY')
        model = current_app.config.get('LLM_MODEL')
        if not key or not model:
            raise ModelUnavailable('尚未配置 DeepSeek 密钥/模型；结构化导入和手动预览仍可使用')
        body = {'model': model, 'messages': messages, 'max_tokens': 4096}
        if tools:
            body['tools'] = tools
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
        try:
            with httpx.Client(timeout=25, trust_env=False) as client:
                response = client.post(current_app.config.get('LLM_BASE_URL', 'https://api.deepseek.com').rstrip('/') + '/chat/completions',
                    headers={'Authorization': 'Bearer ' + key}, json=body)
                response.raise_for_status()
                result = response.json()['choices'][0]
            if result.get('finish_reason') == 'length':
                raise ModelUnavailable('模型输出被截断，请缩小文档或问题范围')
            return result['message']
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise ModelUnavailable('模型请求失败，请检查配置或稍后重试；未执行数据库写入') from None


def get_client():
    return current_app.config.get('LLM_CLIENT') or LLMClient()
