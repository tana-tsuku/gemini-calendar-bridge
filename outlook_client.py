import json
from typing import List, Dict, Any

import requests
from azure.identity import ClientSecretCredential

from config import Config
from logger import get_logger

logger = get_logger(__name__)

class OutlookClient:
    """
    Microsoft Graph API を使用してOutlookのメール操作を行うクラス。
    
    なぜ requests + azure-identity を使うか？:
    Microsoft公式の msgraph-sdk も存在しますが、機能が膨大でLambdaのファイルサイズ肥大化や
    実行速度の低下を招くことがあります。基本的なREST API呼び出しのみであれば、
    `requests` を用いて直接叩く方が軽量で、何をしているか（HTTPメソッド、URL）が明確になり学習にも最適です。
    """

    def __init__(self, user_principal_name: str) -> None:
        """
        Args:
            user_principal_name (str): 対象ユーザーのメールアドレス（またはID）
        """
        self.user_principal_name = user_principal_name
        self.credentials = Config.get_graph_api_credentials()
        self.tenant_id = self.credentials.get("tenant_id")
        self.client_id = self.credentials.get("client_id")
        self.client_secret = self.credentials.get("client_secret")
        
        if not all([self.tenant_id, self.client_id, self.client_secret]):
            logger.error("Graph APIのクレデンシャルに不足があります。")
            raise ValueError("Missing Required Graph API Credentials")

        # Client Credentials Flow（アプリとしての認証）でトークンを取得するための Credential オブジェクト
        # ユーザーの介在なしでバックグラウンド動作させる際に適しています。
        self.credential = ClientSecretCredential(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            client_secret=self.client_secret
        )
        
        # Graph APIのデフォルトスコープ
        self.scopes = ["https://graph.microsoft.com/.default"]
        self.base_url = "https://graph.microsoft.com/v1.0"

    def _get_access_token(self) -> str:
        """Azure AD からアクセストークンを取得する"""
        try:
            token_obj = self.credential.get_token(*self.scopes)
            return token_obj.token
        except Exception as e:
            logger.error(f"アクセストークンの取得に失敗しました: {e}")
            raise e

    def _get_headers(self) -> Dict[str, str]:
        """API呼び出し用の認証ヘッダーを構築する"""
        token = self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def fetch_unread_messages(self) -> List[Dict[str, Any]]:
        """
        受信トレイからメッセージを取得する。
        
        ベストプラクティス: 
        APIのレスポンスサイズを抑えるため $select で取得するフィールドを限定し、
        $top で一度に取得する上限を設けています。
        """
        url = f"{self.base_url}/users/{self.user_principal_name}/mailFolders/inbox/messages"
        
        # $filter: フラグがついていないもののみ取得
        # $select: 必要なプロパティだけ絞り込み
        params = {
            "$filter": "flag/flagStatus eq 'notFlagged'",
            "$select": "id,subject,bodyPreview,body,from,flag",
            "$top": 50
        }

        try:
            logger.info("メールを取得しています...")
            response = requests.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            
            data = response.json()
            messages = data.get("value", [])
            logger.info(f"{len(messages)} 件のメールが見つかりました。")
            return messages
        except requests.exceptions.RequestException as e:
            logger.error(f"メール取得リクエストに失敗しました: {e}")
            return []

    def mark_as_processed(self, message_id: str) -> bool:
        """特定のメールのフラグを完了（complete）状態に更新する"""
        url = f"{self.base_url}/users/{self.user_principal_name}/messages/{message_id}"
        
        # Graph API仕様: complete, flagged, notFlagged のいずれか
        payload = {"flag": {"flagStatus": "complete"}}
        
        try:
            logger.info(f"メール(ID: {message_id}) のフラグを完了にします...")  
            # 部分的なリソースの更新には PATCH メソッドを使用します
            response = requests.patch(
                url, 
                headers=self._get_headers(), 
                json=payload
            )
            response.raise_for_status()
            logger.info("処理済みフラグを立てました。")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"処理済みフラグを立てるのに失敗しました: {e}")
            return False

    def filter_messages(self, messages: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        定義されたフィルター（件名、差出人）に一致するメッセージのみを抽出する。
        戻り値のメッセージ辞書には、予約かキャンセルかを示す情報も付与します。
        """
        filtered = []
        rules = filters.get("rules", [])
        
        if not rules:
            logger.warning("フィルターの定義が存在しません。")
            return []
            
        for msg in messages:
            subject = msg.get("subject", "")
            # 差出人のアドレスは深くネストされているため dict.get() を繋げて安全に取得
            sender_address = msg.get("from", {}).get("emailAddress", {}).get("address", "")
            
            for rule in rules:
                rule_subject = rule.get("subject_keyword", "")
                rule_sender = rule.get("sender", "")
                
                # 件名にキーワードが含まれ、かつ差出人が一致するか判定（大文字小文字を区別しない）
                if rule_subject in subject and rule_sender.lower() == sender_address.lower():
                    # 後の解析で使いやすいようにアクション情報（CREATE/CANCEL）を埋め込む
                    msg["_action_hint"] = rule.get("action")
                    filtered.append(msg)
                    logger.info(f"フィルタに一致したメールを抽出: '{subject}' (Action: {rule.get('action')})")
                    break  # 重複処理を防ぐため、1つのルールに合致したらブレイク
                    
        return filtered
