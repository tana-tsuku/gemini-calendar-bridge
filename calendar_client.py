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
            # タイムゾーンの取得（環境変数 TZ があればそれを使用。デフォルトは Asia/Tokyo）
            # TZ="" (空文字) の場合も "Asia/Tokyo" にフォールバックする
            time_zone = Config.get_env_var("TZ", "Asia/Tokyo") or "Asia/Tokyo"

            start_time = booking_data.get('start_time')
            end_time = booking_data.get('end_time')
            booking_id = booking_data.get('booking_id')

            logger.info(f"イベント作成パラメータ: start={start_time}, end={end_time}, tz={time_zone}")

            # Google Calendar API イベントリソースの形式に従って構築
            event_body = {
                'summary': booking_data.get('title', 'サービス予約'),
            }

            # 必須項目のバリデーションを設定
            if start_time and end_time:
                event_body['start'] = {
                    'dateTime': start_time,
                    'timeZone': time_zone,
                }
                event_body['end'] = {
                    'dateTime': end_time,
                    'timeZone': time_zone,
                }
            else:
                logger.error("start_time または end_time が不足しているため、イベントを作成できません。")
                return None

            # 外部システム（ここでは予約管理）のIDを保持（キャンセル検索用）
            # NoneがAPIに渡ると 400 Required エラーが発生するため、存在する場合のみ追加する
            if booking_id:
                event_body['extendedProperties'] = {
                    'private': {
                        'booking_id': str(booking_id)
                    }
                }

            logger.info(f"イベント作成リクエスト: {event_body['summary']} (ID: {booking_id})")
            
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

    def cancel_event(
        self,
        booking_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> bool:
        """
        指定された booking_id（拡張プロパティ）を持つイベントを検索し、削除する。
        booking_id が不明な場合は start_time / end_time が一致するイベントを削除する。

        Args:
            booking_id (Optional[str]): 削除対象の予約一意ID
            start_time (Optional[str]): booking_id がない場合に使用する検索開始日時（RFC3339形式）
            end_time   (Optional[str]): booking_id がない場合に使用する検索終了日時（RFC3339形式）

        Returns:
            bool: 削除が成功したか否か
        """
        try:
            if booking_id:
                logger.info(f"booking_id '{booking_id}' に紐づくイベントを検索中...")

                # 拡張プロパティを指定して検索（サーバーサイド検索のため非常に高速・確実）
                response = self.service.events().list(
                    calendarId=self.calendar_id,
                    privateExtendedProperty=f"booking_id={booking_id}"
                ).execute()

            elif start_time and end_time:
                logger.info(f"booking_id が未指定のため、期間 ({start_time} ～ {end_time}) でイベントを検索中...")

                # timeMin / timeMax で範囲検索。singleEvents=True で繰り返しイベントも展開
                response = self.service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=start_time,
                    timeMax=end_time,
                    singleEvents=True,
                ).execute()

            else:
                logger.warning(
                    "booking_id も start_time/end_time も指定されていません。キャンセルフローをスキップします。"
                )
                return False

            events = response.get('items', [])

            # start_time / end_time 検索時は「範囲内に存在する全イベント」が返るため、
            # 開始・終了日時が完全一致するイベントのみに絞り込んで誤削除を防ぐ
            if start_time and end_time and not booking_id:
                events = [
                    e for e in events
                    if e.get('start', {}).get('dateTime') == start_time
                    and e.get('end', {}).get('dateTime') == end_time
                ]
                if not events:
                    logger.warning(
                        f"start_time={start_time}, end_time={end_time} に完全一致するイベントが見つかりませんでした。"
                    )

            if not events:
                logger.warning("削除対象のイベントが見つかりませんでした。既に削除済みか、未登録の可能性があります。")
                return False

            # 一致したイベントを全削除（通常は1件を想定）
            for target_event in events:
                event_id = target_event.get('id', '')
                if not event_id:
                    logger.warning("イベントIDが見つからないためスキップします。")
                    continue
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
