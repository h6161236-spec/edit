from __future__ import annotations

import unittest

from vcut_studio.providers.translation import (
    TranslationRequest,
    TranslationProviderError,
    _friendly_http_error_message,
    _friendly_timeout_error_message,
    _is_timeout_reason,
    _retry_delay_seconds,
    extract_json_object,
    parse_proofread_response,
    parse_translation_response,
    proofread_request_payload,
    proxy_configuration,
    request_payload,
    should_bypass_proxy,
    translation_endpoint,
)


class TranslationProviderHelperTests(unittest.TestCase):
    def test_translation_endpoint(self) -> None:
        self.assertEqual(
            translation_endpoint("https://example.com/v1/"),
            "https://example.com/v1/chat/completions",
        )

    def test_request_payload_contains_segments(self) -> None:
        payload = request_payload(
            model="demo-model",
            system_prompt="demo-prompt",
            requests=[TranslationRequest(segment_id="seg1", source_text="你好")],
        )
        self.assertEqual(payload["model"], "demo-model")
        self.assertEqual(payload["response_format"]["type"], "json_object")
        self.assertEqual(payload["messages"][0]["content"], "demo-prompt")
        self.assertIn("seg1", payload["messages"][1]["content"])

    def test_proofread_request_payload_contains_segments(self) -> None:
        payload = proofread_request_payload(
            model="demo-model",
            requests=[TranslationRequest(segment_id="seg1", source_text="你好")],
        )
        self.assertEqual(payload["model"], "demo-model")
        self.assertEqual(payload["response_format"]["type"], "json_object")
        self.assertIn("corrections", payload["messages"][1]["content"])

    def test_extract_json_object_from_code_block(self) -> None:
        payload = extract_json_object(
            "```json\n{\"translations\":[{\"segment_id\":\"seg1\",\"translated_text\":\"Hello\"}]}\n```"
        )
        self.assertIn("translations", payload)

    def test_parse_translation_response_with_list(self) -> None:
        requests = [
            TranslationRequest(segment_id="seg1", source_text="你好"),
            TranslationRequest(segment_id="seg2", source_text="世界"),
        ]
        response_text = (
            '{"translations":['
            '{"segment_id":"seg1","translated_text":"Hello"},'
            '{"segment_id":"seg2","translated_text":"World"}'
            "]}"
        )
        results = parse_translation_response(response_text, requests)
        self.assertEqual([item.translated_text for item in results], ["Hello", "World"])

    def test_parse_translation_response_with_mapping(self) -> None:
        requests = [TranslationRequest(segment_id="seg1", source_text="你好")]
        response_text = '{"translations":{"seg1":"Hello"}}'
        results = parse_translation_response(response_text, requests)
        self.assertEqual(results[0].translated_text, "Hello")

    def test_parse_translation_response_with_root_list(self) -> None:
        requests = [TranslationRequest(segment_id="seg1", source_text="你好")]
        response_text = '[{"segment_id":"seg1","translated_text":"Hello"}]'
        results = parse_translation_response(response_text, requests)
        self.assertEqual(results[0].translated_text, "Hello")

    def test_parse_proofread_response_with_list(self) -> None:
        requests = [TranslationRequest(segment_id="seg1", source_text="你好")]
        response_text = '[{"segment_id":"seg1","corrected_text":"你好啊"}]'
        results = parse_proofread_response(response_text, requests)
        self.assertEqual(results[0].corrected_text, "你好啊")

    def test_extract_json_object_accepts_python_style_literal(self) -> None:
        payload = extract_json_object("{'translations': [{'segment_id': 'seg1', 'translated_text': 'Hello'}]}")
        self.assertIsInstance(payload, dict)
        self.assertIn("translations", payload)

    def test_parse_translation_response_raises_on_missing_ids(self) -> None:
        requests = [
            TranslationRequest(segment_id="seg1", source_text="你好"),
            TranslationRequest(segment_id="seg2", source_text="世界"),
        ]
        with self.assertRaises(TranslationProviderError):
            parse_translation_response('{"translations":[{"segment_id":"seg1","translated_text":"Hello"}]}', requests)

    def test_should_bypass_proxy_matches_exact_host_and_suffix(self) -> None:
        self.assertTrue(should_bypass_proxy("https://model.corp.local/v1", "localhost,.corp.local"))
        self.assertTrue(should_bypass_proxy("https://localhost/api", "localhost,.corp.local"))
        self.assertFalse(should_bypass_proxy("https://api.openai.com/v1", "localhost,.corp.local"))

    def test_proxy_configuration_uses_manual_proxy_values(self) -> None:
        proxy_map = proxy_configuration(
            proxy_enabled=True,
            http_proxy="http://127.0.0.1:7890",
            https_proxy="http://127.0.0.1:7890",
            no_proxy="",
            target_url="https://api.openai.com/v1/chat/completions",
        )
        self.assertEqual(
            proxy_map,
            {
                "http": "http://127.0.0.1:7890",
                "https": "http://127.0.0.1:7890",
            },
        )

    def test_proxy_configuration_returns_empty_map_when_bypassed(self) -> None:
        proxy_map = proxy_configuration(
            proxy_enabled=True,
            http_proxy="http://127.0.0.1:7890",
            https_proxy="http://127.0.0.1:7890",
            no_proxy=".openai.com",
            target_url="https://api.openai.com/v1/chat/completions",
        )
        # Bypassing means "no proxy at all": an empty map disables proxying
        # (including environment-variable proxies).
        self.assertEqual(proxy_map, {})

    def test_proxy_configuration_disabled_returns_none(self) -> None:
        proxy_map = proxy_configuration(
            proxy_enabled=False,
            http_proxy="http://127.0.0.1:7890",
            https_proxy="http://127.0.0.1:7890",
            no_proxy="",
            target_url="https://api.openai.com/v1/chat/completions",
        )
        # Proxy mode off -> default opener, which honors system/environment
        # proxies (so a user relying on the OS default proxy still connects).
        self.assertIsNone(proxy_map)

    def test_proxy_configuration_enabled_without_addresses_returns_none(self) -> None:
        proxy_map = proxy_configuration(
            proxy_enabled=True,
            http_proxy="",
            https_proxy="",
            no_proxy="",
            target_url="https://api.openai.com/v1/chat/completions",
        )
        # None keeps the default opener, which honors environment proxies.
        self.assertIsNone(proxy_map)

    def test_retry_delay_seconds_exponential_backoff_with_cap(self) -> None:
        self.assertEqual(_retry_delay_seconds(0), 1.0)
        self.assertEqual(_retry_delay_seconds(1), 2.0)
        self.assertEqual(_retry_delay_seconds(2), 4.0)
        # Large attempts hit the cap instead of exploding.
        self.assertEqual(_retry_delay_seconds(20), 8.0)

    def test_retry_delay_seconds_honors_retry_after(self) -> None:
        self.assertEqual(_retry_delay_seconds(0, retry_after_seconds=3.5), 3.5)
        self.assertEqual(_retry_delay_seconds(0, retry_after_seconds=999), 60.0)
        self.assertEqual(_retry_delay_seconds(0, retry_after_seconds=-1), 0.0)

    def test_friendly_http_error_message_for_cloudflare_1010(self) -> None:
        message = _friendly_http_error_message(403, "error code: 1010", "Forbidden")
        self.assertIn("Cloudflare/WAF", message)
        self.assertIn("1010", message)

    def test_friendly_http_error_message_for_401_mentions_api_key(self) -> None:
        message = _friendly_http_error_message(401, "Your api key is invalid", "Unauthorized")
        self.assertIn("401", message)
        self.assertIn("API Key", message)

    def test_friendly_http_error_message_for_generic_403(self) -> None:
        message = _friendly_http_error_message(403, "insufficient permissions", "Forbidden")
        self.assertIn("403", message)
        self.assertNotIn("1010", message)

    def test_is_timeout_reason_detects_python_timeout_text(self) -> None:
        self.assertTrue(_is_timeout_reason("The read operation timed out"))
        self.assertTrue(_is_timeout_reason(TimeoutError("timed out")))
        self.assertFalse(_is_timeout_reason("forbidden"))

    def test_friendly_timeout_error_message_mentions_setting_hints(self) -> None:
        message = _friendly_timeout_error_message(60)
        self.assertIn("60", message)
        self.assertIn("超时", message)
        self.assertIn("批大小", message)


if __name__ == "__main__":
    unittest.main()
