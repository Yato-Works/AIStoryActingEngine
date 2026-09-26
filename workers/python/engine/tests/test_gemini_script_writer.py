"""GeminiScriptWriter の単体テスト。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from reading import ReadingDictionary
from script_writer import GeminiScriptWriter


class TestGeminiScriptWriter:
    def test_missing_api_key_raises(self):
        writer = GeminiScriptWriter(api_key="")
        dictionary = ReadingDictionary()
        segments = [{"id": "seg_001", "speaker": "千早", "text": "こんにちは"}]
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY が設定されていません"):
            writer.write_script(segments, dictionary)

    def test_write_script_success_with_mock(self):
        mock_response_json = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "segments": [
                                        {
                                            "id": "seg_001",
                                            "text_reading": "ゆうぐれの しょうてんがいを 🥺たちつくしていた",
                                        },
                                        {
                                            "id": "seg_002",
                                            "text_reading": "……😮‍💨ううん。わたしも、いま きたところ🤭",
                                        },
                                    ],
                                    "readings": [
                                        {"surface": "商店街", "reading": "しょうてんがい"}
                                    ],
                                })
                            }
                        ]
                    }
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response_json
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            writer = GeminiScriptWriter(api_key="test_key_123")
            dictionary = ReadingDictionary({"千早": "ちはや"})
            segments = [
                {"id": "seg_001", "speaker": "ナレーター", "text": "夕暮れの商店街を立ち尽くしていた"},
                {"id": "seg_002", "speaker": "千早", "text": "……ううん。私も、今来たとこ"},
            ]

            result = writer.write_script(segments, dictionary)

            assert mock_post.called
            call_url = mock_post.call_args[0][0]
            assert "generateContent" in call_url
            assert "key=test_key_123" in call_url

            # 辞書提案の取り込み確認
            assert "商店街" in result.new_readings
            assert result.new_readings["商店街"] == "しょうてんがい"

            # セグメントの確認
            segs = result.script.segments
            assert len(segs) == 2
            assert segs[0].id == "seg_001"
            assert "🥺" in segs[0].text_reading
            assert segs[1].id == "seg_002"
            assert "😮‍💨" in segs[1].text_reading
            assert "🤭" in segs[1].text_reading
