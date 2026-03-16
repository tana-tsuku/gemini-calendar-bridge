import json
from typing import Dict, Any

from config import Config
from logger import get_logger
from outlook_client import OutlookClient
from gemini_parser import GeminiParser
from calendar_client import CalendarClient

logger = get_logger(__name__)

# Lambda環境におけるベストプラクティス:
# 大きなクラスやデータベース接続の初期化をハンドラの外（グローバルスコープ）に置くことで、
# コンテナが再利用された（ウォームスタート）際のオーバーヘッドを削減できます。
# ただし、今回は設定エラーなどで起動不能になるのを防ぐため、最低限の初期化をハンドラ内で行います。
# 運用フェーズに入って設定が安定したら、これらの初期化を外に出す構成をお勧めします。

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda のエントリポイント（メインロジック）。
    定期実行（EventBridge）をトリガーとする想定です。
    """
    logger.info("Lambda関数が開始されました。")

    try:
        # --- 1. 設定の読み込み ---
        filters = Config.get_mail_filters()
        if not filters.get("rules"):
            logger.warning("メールフィルター定義が存在しません。処理を完了します。")
            return {"statusCode": 200, "body": "No filter rules configured."}

        # アプリケーション認証（Client Credentials）では /me が使えないため、
        # 対象ユーザー（共有メールボックスなど）のアドレスを環境変数で指定する必要があります。
        target_user = Config.get_env_var("GRAPH_TARGET_USER", "reservations@yourdomain.com")

        # --- 2. クライアントの初期化 ---
        try:
            outlook = OutlookClient(user_principal_name=target_user)
            parser = GeminiParser()
            calendar = CalendarClient()
        except Exception as e:
            logger.error(f"クライアント初期化エラーにより処理を中断します: {e}")
            return {"statusCode": 500, "body": "Failed to initialize clients."}

        # --- 3. メールの取得とフィルタリング ---
        messages = outlook.fetch_messages()
        if not messages:
            logger.info("対象のメールはありませんでした。")
            return {"statusCode": 200, "body": "No messages."}

        target_messages = outlook.filter_messages(messages, filters)
        if not target_messages:
            logger.info("処理対象となる（フィルターに一致した）メールはありませんでした。")
            return {"statusCode": 200, "body": "No target messages to process."}

        logger.info(f"処理対象のメールが {len(target_messages)} 件見つかりました。")

        # --- 4. 順次処理（解析 -> カレンダー登録 -> 既読化） ---
        success_count = 0
        error_count = 0

        for msg in target_messages:
            msg_id = msg.get("id")
            subject = msg.get("subject", "No Subject")
            # メールの形式（HTML/Text）に応じて本文を取得
            body_content = msg.get("body", {}).get("content", "")
            action_hint = msg.get("_action_hint")

            logger.info(f"--- メール処理開始: '{subject}' (Action: {action_hint}) ---")

            # 4.1 Gemini 解析
            booking_data = parser.parse_booking_email(body_content, action_hint)
            
            if not booking_data:
                logger.error(f"メール解析に失敗したためスキップします。Subject: {subject}")
                error_count += 1
                continue
                
            action = booking_data.get("action")
            booking_id = booking_data.get("booking_id")
            
            logger.info(f"解析結果: Action={action}, Booking ID={booking_id}")

            # 4.2 カレンダー反映
            process_success = False
            if action == "CREATE":
                event_id = calendar.create_event(booking_data)
                if event_id:
                    process_success = True
            elif action == "CANCEL":
                if calendar.cancel_event(
                    booking_id=booking_id,
                    start_time=booking_data.get("start_time"),
                    end_time=booking_data.get("end_time"),
                ):
                    process_success = True
            else:
                logger.warning(f"未知のアクション '{action}' のためスキップします。")

            # 4.3 冪等性の担保: 成功した場合のみ、メールのフラグを完了にして次回の再処理を防ぐ
            # コンテキストマネージャ (with 構文) の代替として、ここでは状態ベースのステートマシン的な処理を適用
            if process_success:
                logger.info("カレンダー連携が成功しました。メールのフラグを完了済みに更新します。")
                if outlook.mark_as_processed(msg_id):
                    success_count += 1
                else:
                    logger.error("カレンダー登録は成功しましたがフラグ更新処理に失敗しました。（次回重複処理される可能性があります）")
                    error_count += 1
            else:
                logger.error("カレンダー連携に失敗したため、メールはそのまま残します。")
                error_count += 1

        # --- 5. 終了処理 ---
        logger.info(f"全処理完了。成功: {success_count}件, 失敗: {error_count}件")
        
        # 複数件のうち一部でもエラーがあれば 207 Multi-Status を返す
        status_code = 200 if error_count == 0 else 207
        return {
            "statusCode": status_code,
            "body": json.dumps({"success": success_count, "errors": error_count})
        }

    except Exception as e:
        logger.error(f"Lambdaハンドラ内で予期せぬエラーが発生しました: {e}")
        return {
            "statusCode": 500,
            "body": "An unexpected error occurred."
        }
