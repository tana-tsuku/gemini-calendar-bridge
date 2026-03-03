import json
from typing import Dict, Any, Optional

from google import genai
from google.genai import types

from config import Config
from logger import get_logger

logger = get_logger(__name__)

class GeminiParser:
    """
    Gemini API を利用してメール本文から予約情報を抽出するパーサー。
    
    なぜこの実装がベストプラクティスか:
    - `google-genai`：最新の公式SDKです。
    - 構造化出力（JSON戻り値強制）：`response_mime_type="application/json"` を指定することで、
      API側がJSONフォーマットで返すことを保証し、パースエラーの確率を劇的に下げます。
    - Temperature=0.0：創作を避け、事実（メール本文の情報）のみを正確に抽出するための適正な設定です。
    """

    def __init__(self) -> None:
        api_key = Config.get_gemini_api_key()
        if not api_key:
            logger.error("Gemini APIキーが設定されていません。")
            raise ValueError("Missing Gemini API Key")

        # 推奨されるクライアント初期化
        self.client = genai.Client(api_key=api_key)
        # より高速かつコスト効率の良い flash モデルを使用
        self.model_name = "gemini-2.5-flash"
        
        # ユーザー指定の要件に基づくプロンプト定義
        self.system_instruction = (
            "以下のメールを解析し、予約状況を抽出しなさい。\n"
            "返却は必ず以下のJSONフォーマットのみで行うこと。\n"
            "{\n"
            '  "action": "CREATE" または "CANCEL",\n'
            '  "title": "サービス予約: [サービス名]",\n'
            '  "start_time": "ISO8601形式の日時",\n'
            '  "end_time": "ISO8601形式の日時（不明な場合は開始の30分後）",\n'
            '  "booking_id": "メールに含まれる固有の予約番号（削除時のキー）"\n'
            "}"
        )

    def parse_booking_email(self, email_body: str, action_hint: str) -> Optional[Dict[str, Any]]:
        """
        メール本文を解析し、JSON形式の予約情報を返す。
        
        Args:
            email_body (str): 解析対象のメール本文
            action_hint (str): 件名などから予め判断した「CREATE」か「CANCEL」かのヒント
            
        Returns:
            Optional[Dict[str, Any]]: パースされたJSON辞書（解析失敗時は None）
        """
        # メールの文面からのアクション判定は不要というユーザー要件に従い、
        # 前段（件名ルールフィルター）で特定したアクションをプロンプトで明示し、推論のブレを無くします。
        prompt = (
            f"このメールの予約に対するアクションは「{action_hint}」です。\n\n"
            f"--- メール本文 ---\n{email_body}\n------------------"
        )
        
        try:
            logger.info("Gemini APIでメールの解析を開始します...")
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_instruction,
                    response_mime_type="application/json",
                    temperature=0.0  # 決定論的な出力を目指し、抽出精度を上げる
                )
            )
            
            response_text = response.text.strip()
            logger.info("Geminiによる解析が完了しました。")
            
            try:
                parsed_data = json.loads(response_text)
                
                # 要件「予約かキャンセルかは件名から判定できる。フラグで判断するため文面での考慮は不要」を
                # 確実に担保するため、Geminiが万が一推論を間違えても action_hint の値で強制上書きします。
                parsed_data["action"] = action_hint
                
                return parsed_data
                
            except json.JSONDecodeError as decode_err:
                logger.error(f"Geminiの応答が有効なJSONではありませんでした:\n{response_text}\nエラー: {decode_err}")
                return None
                
        except Exception as e:
            logger.error(f"Gemini API 呼び出し中にエラーが発生しました: {e}")
            return None
