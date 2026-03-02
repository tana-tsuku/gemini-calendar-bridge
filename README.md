# gemini-calendar-bridge

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)

Gemini APIを活用して、Outlook（Microsoft 365）に届く予約メールを解析し、Googleカレンダーへ自動登録・同期する自動化ツールです。
勉強用に開発したものです。

---

## 🚀 概要 (Overview)

「予約メールが届くたびに手動でカレンダーに入力する」という手間をAIで解消します。
本プロジェクトは、Microsoft Graph APIとGoogle Calendar APIの橋渡しを行い、LLM（Gemini 1.5 Pro/Flash）を用いることで、複雑なメール本文からの正確な日時抽出と、キャンセル処理の自動化を実現しています。

### 解決する課題
- **予約の自動登録**: Outlookに届く特定の予約メールを即座にGoogleカレンダーに反映。
- **キャンセル対応**: キャンセル通知メールを検知し、該当するカレンダー予定を自動削除。
- **表記ゆれの吸収**: AIによる自然言語解析により、定型・非定型問わず正確に情報を抽出。

## 🛠 技術スタック (Tech Stack)

- **Language**: Python 3.11+
- **AI/LLM**: Gemini API (Google AI Studio)
- **APIs**: Microsoft Graph API (Outlook), Google Calendar API
- **Automation**: AWS Lambdaを検討中
- **Development**: Docker, Antigravity (Python Framework)

## 📐 システム構成図 (Architecture)



1. **Trigger**: AWS Lambdaが定期的に実行（ポーリング）。
2. **Fetch**: Microsoft Graph API経由でOutlookの未読メールを取得。
3. **Analyze**: Gemini APIが本文を解析し、予約/キャンセルの判定および日時を抽出。
4. **Sync**: 解析結果に基づき、Google Calendar APIでイベントを作成・削除。

