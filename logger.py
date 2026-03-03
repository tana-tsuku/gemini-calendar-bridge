import logging
import sys

def get_logger(name: str) -> logging.Logger:
    """
    標準の logging モジュールを使用してロガーを設定・取得する。
    AWS Lambda の CloudWatch Logs でも見やすいフォーマットを指定している。
    
    Args:
        name (str): ロガーの名前（通常は __name__ を渡す）
        
    Returns:
        logging.Logger: 設定されたロガーインスタンス
    """
    logger = logging.getLogger(name)
    
    # 既にハンドラが設定されている場合はスキップ
    # （Lambda 環境での二重出力を防ぐため）
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # 標準出力にログを流す
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        
        # ログフォーマット: 時刻, ログレベル, モジュール名, メッセージ
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
        )
        handler.setFormatter(formatter)
        
        logger.addHandler(handler)
        
        # 上位のロガーに伝播させない（重複ログ防止）
        logger.propagate = False
        
    return logger
