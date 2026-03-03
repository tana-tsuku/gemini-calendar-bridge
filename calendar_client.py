from typing import Dict, Any, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import Config
from logger import get_logger

logger = get_logger(__name__)

class CalendarClient:
    """
    Google Calendar API を使用して予定の登録・削除を行うクラス。
    
    ベストプラクティス:
    拡張プロパティ (extendedProperties) に独自の `booking_id` を埋め込むことで、
    キャンセル時にタイトルなどに依存せず、API側で安全かつ高速に検索・削除が可能です。
    """

    # イベントの読み書きに必要な最小スコープ
    SCOPES = ['https://www.googleapis.com/auth/calendar.events']

    def __init__(self) -> None:
        credentials_info = Config.get_google_calendar_credentials()
        if not credentials_info:
            logger.error("Google Calendarの認証情報が設定されていません。")
            raise ValueError("Missing Google Calendar Credentials")

        try:
            # 辞書形式のJSON情報からサービスアカウントクレデンシャルを構築
            self.credentials = service_account.Credentials.from_service_account_info(
                credentials_info, scopes=self.SCOPES
            )
            # cache_discovery=False を指定しておくことで環境差異（ファイルパーミッション等）によるエラーを防ぎます
            self.service = build('calendar', 'v3', credentials=self.credentials, cache_discovery=False)
            
            # 使用するカレンダーID。サービスアカウント自身のアドレスが primary ですが、
            # 汎用性を持たせるため環境変数 GOOGLE_CALENDAR_ID でオーバライド可能に設計しています。
            self.calendar_id = Config.get_env_var("GOOGLE_CALENDAR_ID", "primary")
            
            logger.info(f"CalendarClient 初期化完了 (Calendar ID: {self.calendar_id})")
        except Exception as e:
            logger.error(f"CalendarClientの初期化に失敗しました: {e}")
            raise e

    def create_event(self, booking_data: Dict[str, Any]) -> Optional[str]:
        """
        予約データに基づいてカレンダーにイベントを作成する。
        
        Args:
            booking_data (Dict[str, Any]): Geminiから抽出・整形されたJSONデータ等
            
        Returns:
            Optional[str]: 作成されたイベントID（失敗時は None）
        """
        try:
            # Google Calendar API イベントリソースの形式に従って構築
            event_body = {
                'summary': booking_data.get('title', 'サービス予約'),
                'start': {
                    'dateTime': booking_data.get('start_time'),
                },
                'end': {
                    'dateTime': booking_data.get('end_time'),
                },
                # 外部システム（ここでは予約管理）のIDを保持（キャンセル検索用）
                'extendedProperties': {
                    'private': {
                        'booking_id': booking_data.get('booking_id')
                    }
                }
            }

            logger.info(f"イベント作成リクエスト: {event_body['summary']} (ID: {booking_data.get('booking_id')})")
            
            created_event = self.service.events().insert(
                calendarId=self.calendar_id, body=event_body
            ).execute()
            
            event_id = created_event.get('id')
            logger.info(f"イベント作成成功: Event ID = {event_id}")
            return event_id

        except HttpError as error:
            logger.error(f"カレンダーのイベント作成中にAPIエラーが発生しました: {error}")
            return None
        except Exception as e:
            logger.error(f"予期せぬエラーが発生しました: {e}")
            return None

    def cancel_event(self, booking_id: str) -> bool:
        """
        指定された booking_id（拡張プロパティ）を持つイベントを検索し、削除する。
        
        Args:
            booking_id (str): 削除対象の予約一意ID
            
        Returns:
            bool: 削除が成功したか否か
        """
        if not booking_id:
            logger.warning("削除対象の booking_id が指定されていません。キャンセルフローをスキップします。")
            return False

        try:
            logger.info(f"booking_id '{booking_id}' に紐づくイベントを検索中...")
            
            # 拡張プロパティを指定して検索（サーバーサイド検索のため非常に高速・確実）
            response = self.service.events().list(
                calendarId=self.calendar_id,
                privateExtendedProperty=f"booking_id={booking_id}"
            ).execute()
            
            events = response.get('items', [])
            
            if not events:
                logger.warning(f"booking_id '{booking_id}' に一致するイベントが見つかりませんでした。既に削除済みか、未登録の可能性があります。")
                return False

            # 一致したイベントを全削除（通常は1件を想定）
            for target_event in events:
                event_id = target_event['id']
                logger.info(f"イベント(Event ID: {event_id}) を削除します...")
                self.service.events().delete(
                    calendarId=self.calendar_id, eventId=event_id
                ).execute()
                
            logger.info("キャンセル処理（イベント削除）が正常に完了しました。")
            return True

        except HttpError as error:
            logger.error(f"カレンダーのイベント削除中にAPIエラーが発生しました: {error}")
            return False
        except Exception as e:
            logger.error(f"予期せぬエラーが発生しました: {e}")
            return False
