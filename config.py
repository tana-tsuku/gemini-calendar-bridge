import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from logger import get_logger

logger = get_logger(__name__)

# ローカル開発用に .env ファイルを読み込む
# 既に環境変数が設定されている場合（Lambda上など）は上書きしない
load_dotenv()

class Config:
    """
    アプリケーションの設定を管理するクラス。
    ローカル環境では .env から、AWS 環境では環境変数および Secrets Manager から取得する。
    """

    @staticmethod
    def get_env_var(key: str, default: Optional[str] = None) -> str:
        """環境変数を取得する"""
        val = os.getenv(key, default)
        if val is None:
            logger.warning(f"環境変数 '{key}' が設定されていません。")
            return ""
        return val

    @classmethod
    def get_mail_filters(cls) -> Dict[str, Any]:
        """
        Lambdaの環境変数に JSON 形式で保存されたメールのフィルター定義を取得する。
        """
        filters_json = cls.get_env_var("MAIL_FILTERS_JSON", "{}")
        try:
            return json.loads(filters_json)
        except json.JSONDecodeError as e:
            logger.error(f"MAIL_FILTERS_JSON のパースに失敗しました: {e}")
            return {}

    @staticmethod
    def get_secret(secret_name: str, region_name: str = "ap-northeast-1") -> Dict[str, Any]:
        """
        AWS Secrets Manager からシークレットを取得する。
        ローカル開発等で USE_AWS_SECRETS が false の場合は、環境変数からのフォールバック取得を試みる。
        """
        use_aws_secrets = os.getenv("USE_AWS_SECRETS", "false").lower() == "true"
        
        if not use_aws_secrets:
            logger.info("USE_AWS_SECRETS が false のため、環境変数からのシークレット取得を試みます。")
            local_secret = os.getenv(f"LOCAL_SECRET_{secret_name}")
            if local_secret:
                try:
                    return json.loads(local_secret)
                except json.JSONDecodeError:
                    return {"value": local_secret}
            return {}

        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name=region_name
        )

        try:
            logger.info(f"Secrets Manager から '{secret_name}' を取得します...")
            response = client.get_secret_value(SecretId=secret_name)
        except ClientError as e:
            logger.error(f"Secrets Manager からの取得に失敗しました: {e}")
            raise e

        if 'SecretString' in response:
            secret = response['SecretString']
            try:
                return json.loads(secret)
            except json.JSONDecodeError:
                return {"value": secret}
        else:
            logger.warning("バイナリタイプのシークレットは現在サポートしていません。")
            return {}

    @classmethod
    def get_graph_api_credentials(cls) -> Dict[str, str]:
        """Microsoft Graph API のクレデンシャルを取得する"""
        secret_name = cls.get_env_var("GRAPH_API_SECRET_NAME", "graph-api-credentials")
        secrets = cls.get_secret(secret_name)
        return {
            "client_id": secrets.get("GRAPH_CLIENT_ID") or cls.get_env_var("GRAPH_CLIENT_ID"),
            "client_secret": secrets.get("GRAPH_CLIENT_SECRET") or cls.get_env_var("GRAPH_CLIENT_SECRET"),
            "tenant_id": secrets.get("GRAPH_TENANT_ID") or cls.get_env_var("GRAPH_TENANT_ID"),
        }

    @classmethod
    def get_gemini_api_key(cls) -> str:
        """Gemini APIキーを取得する"""
        secret_name = cls.get_env_var("GEMINI_API_SECRET_NAME", "gemini-api-key")
        secrets = cls.get_secret(secret_name)
        return secrets.get("GEMINI_API_KEY") or cls.get_env_var("GEMINI_API_KEY")
        
    @classmethod
    def get_google_calendar_credentials(cls) -> Dict[str, Any]:
        """Google Calendar API の認証情報（JSON）を取得する"""
        secret_name = cls.get_env_var("GOOGLE_CALENDAR_SECRET_NAME", "google-calendar-credentials")
        secrets = cls.get_secret(secret_name)
        
        if not secrets:
            # ローカル環境用のフォールバック：JSONファイルからの読み込み
            local_path = cls.get_env_var("GOOGLE_APPLICATION_CREDENTIALS")
            if local_path and Path(local_path).exists():
                logger.info(f"ローカルの認証情報ファイル '{local_path}' を読み込みます。")
                with open(local_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        return secrets
