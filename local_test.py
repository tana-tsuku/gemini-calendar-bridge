from lambda_function import lambda_handler

if __name__ == "__main__":
    print("=== ローカルテスト開始 ===")
    
    # Lambdaハンドラを疑似的なイベントとコンテキストで呼び出し
    test_event = {}
    test_context = None
    
    result = lambda_handler(test_event, test_context)
    
    print("\n=== ローカルテスト終了 ===")
    print("結果:", result)
