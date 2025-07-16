import os
import json
import re
import random
import base64
from datetime import datetime
from flask import Flask, request, jsonify
import requests
from github import Github # PyGithubライブラリを使用

# Flaskアプリケーションの初期化
app = Flask(__name__)

# --- 設定項目 ---
# 環境変数から取得することを推奨 (Renderデプロイ時に設定)
CHATWORK_API_TOKEN = os.getenv('CHATWORK_API_TOKEN', 'YOUR_CHATWORK_API_TOKEN')
CHATWORK_GROUP_ID = os.getenv('CHATWORK_GROUP_ID', '404646956')

# GitHubリポジトリ設定
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN")
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "YOUR_GITHUB_USERNAME_OR_ORG") # リポジトリのオーナー名
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "YOUR_REPOSITORY_NAME")       # リポジトリ名 (例: chatwork-bot-data)
GITHUB_BRANCH_NAME = os.getenv("GITHUB_BRANCH_NAME", "main")                 # コミットするブランチ名

MEMBER_FILE_PATH = "data/members.json" # メンバーリストを保存するファイルパス
LOG_FILE_PATH = "data/logs.json"       # ログを保存するファイルパス (JSON Lines形式推奨)

# Chatwork絵文字のリスト（正規表現用にエスケープ済み）
CHATWORK_EMOJI_CODES = [
  "roger", "bow", "cracker", "dance", "clap", "y", "sweat", "blush", "inlove",
  "talk", "yawn", "puke", "emo", "nod", "shake", "\\^\\^;", ":/", "whew", "flex",
  "gogo", "think", "please", "quick", "anger", "devil", "lightbulb", "h", "F",
  "eat", "\\^", "coffee", "beer", "handshake"
]
CHATWORK_EMOJI_REGEX = re.compile(r'\(' + '|'.join(CHATWORK_EMOJI_CODES) + r'\)')

# PyGithubクライアントの初期化
try:
    g_github = Github(GITHUB_TOKEN)
    github_repo = g_github.get_user().get_repo(GITHUB_REPO_NAME)
    # もしOrganizationのリポジトリなら:
    # org = g_github.get_organization(GITHUB_REPO_OWNER)
    # github_repo = org.get_repo(GITHUB_REPO_NAME)
except Exception as e:
    app.logger.critical(f"GitHubクライアントの初期化に失敗しました。トークンやリポジトリ名を確認してください: {e}")
    exit(1)

# --- GitHub ファイル操作ヘルパー関数 ---

def get_github_file_content(file_path):
    """GitHubリポジトリから指定されたファイルのコンテンツを取得する"""
    try:
        contents = github_repo.get_contents(file_path, ref=GITHUB_BRANCH_NAME)
        # ファイルコンテンツはbase64でエンコードされているのでデコードする
        file_content = contents.decoded_content.decode('utf-8')
        app.logger.info(f"GitHubからファイル '{file_path}' のコンテンツを取得しました。")
        return file_content, contents.sha
    except Exception as e:
        app.logger.warning(f"GitHubからファイル '{file_path}' のコンテンツ取得に失敗しました (新規ファイルまたはエラー): {e}")
        return None, None

def update_github_file_content(file_path, new_content, commit_message, sha=None):
    """GitHubリポジトリのファイルを更新または新規作成する"""
    try:
        if sha:
            # 既存ファイルの更新
            github_repo.update_file(
                path=file_path,
                message=commit_message,
                content=new_content,
                sha=sha,
                branch=GITHUB_BRANCH_NAME
            )
            app.logger.info(f"GitHubファイル '{file_path}' を更新しました。")
        else:
            # 新規ファイルの作成
            github_repo.create_file(
                path=file_path,
                message=commit_message,
                content=new_content,
                branch=GITHUB_BRANCH_NAME
            )
            app.logger.info(f"GitHubファイル '{file_path}' を新規作成しました。")
        return True
    except Exception as e:
        app.logger.error(f"GitHubファイル '{file_path}' のコミットに失敗しました: {e}")
        return False

# --- Chatwork API ヘルパー関数 (変更なし) ---

def send_chatwork_message(room_id, message_body):
    """Chatworkにメッセージを送信する"""
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
    headers = {
        "X-ChatWorkToken": CHATWORK_API_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {"body": message_body}
    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
        app.logger.info(f"Chatworkルーム {room_id} にメッセージを送信しました。")
        return True
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Chatworkメッセージの送信に失敗しました: {e}")
        return False

def get_chatwork_members():
    """Chatworkグループのメンバーリストと役割を取得する"""
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_GROUP_ID}/members"
    headers = {"X-ChatWorkToken": CHATWORK_API_TOKEN}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        members_data = response.json()
        return [{"account_id": m["account_id"], "name": m["name"], "role": m["role"]} for m in members_data]
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Chatworkメンバーの取得に失敗しました: {e}")
        return []

def change_member_role(room_id, target_account_id, new_role, user_name, change_reason=""):
    """Chatworkメンバーの役割を変更する"""
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/members"
    headers = {
        "X-ChatWorkToken": CHATWORK_API_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    current_members = get_chatwork_members()
    if not current_members:
        app.logger.error('役割変更のための現在のメンバーリスト取得に失敗しました。')
        return

    admin_ids = [str(m['account_id']) for m in current_members if m['role'] == 'admin' and m['account_id'] != target_account_id]
    member_ids = [str(m['account_id']) for m in current_members if m['role'] == 'member' and m['account_id'] != target_account_id]
    readonly_ids = [str(m['account_id']) for m in current_members if m['role'] == 'readonly' and m['account_id'] != target_account_id]

    if new_role == 'admin':
        admin_ids.append(str(target_account_id))
    elif new_role == 'member':
        member_ids.append(str(target_account_id))
    elif new_role == 'readonly':
        readonly_ids.append(str(target_account_id))
    
    payload = {
        'members_admin_ids': ','.join(admin_ids),
        'members_member_ids': ','.join(member_ids),
        'members_readonly_ids': ','.join(readonly_ids)
    }
    
    try:
        response = requests.put(url, headers=headers, data=payload)
        response.raise_for_status()
        app.logger.info(f"{user_name} ({target_account_id}) の権限を {new_role} に変更しました。")
        
        notification_message = f"[info][title]権限変更のお知らせ[/title][To:{target_account_id}][pname:{target_account_id}]さんの権限を「閲覧のみ」に変更しました。"
        if change_reason:
            notification_message += f"\n理由: {change_reason}"
        notification_message += "\nルームルールに基づき、ご協力をお願いいたします。[/info]"
        send_chatwork_message(room_id, notification_message)

    except requests.exceptions.RequestException as e:
        app.logger.error(f"メンバーの役割変更中にエラーが発生しました: {e}")
        send_chatwork_message(room_id, f"[error][title]権限変更エラー[/title][To:{target_account_id}][pname:{target_account_id}]さんの権限変更に失敗しました。管理者にご連絡ください。[/error]")

# --- データストア関連ヘルパー関数 (GitHubファイルを使用) ---

def get_previous_members_from_github():
    """GitHubファイルから前回のメンバーリストを取得する"""
    file_content, _ = get_github_file_content(MEMBER_FILE_PATH)
    if file_content:
        try:
            members_data = json.loads(file_content)
            # 日付文字列をdatetimeオブジェクトに変換
            for member in members_data:
                member['join_time'] = datetime.fromisoformat(member['join_time'])
            app.logger.info(f"GitHubファイル '{MEMBER_FILE_PATH}' から過去のメンバー情報を取得しました。")
            return members_data
        except json.JSONDecodeError as e:
            app.logger.error(f"メンバーファイル '{MEMBER_FILE_PATH}' のJSONパースに失敗しました: {e}")
            return []
    return []

def save_current_members_to_github(current_members, previous_members):
    """現在のメンバーリストをGitHubファイルに保存する"""
    data_to_save = []

    previous_members_map = {m['account_id']: m for m in previous_members}

    for member in current_members:
        join_time = None
        if member['account_id'] in previous_members_map:
            join_time = previous_members_map[member['account_id']]['join_time']
        else:
            join_time = datetime.now()

        data_to_save.append({
            "name": member['name'],
            "account_id": member['account_id'],
            "join_time": join_time.isoformat(), # ISOフォーマットで文字列として保存
            "role": member['role']
        })
    
    # JSON文字列としてフォーマット
    new_content = json.dumps(data_to_save, indent=2, ensure_ascii=False)
    
    # GitHubにコミット
    _, sha = get_github_file_content(MEMBER_FILE_PATH) # 最新のSHAを取得
    commit_message = "Update member list via bot"
    return update_github_file_content(MEMBER_FILE_PATH, new_content, commit_message, sha)

def find_new_members(current_members, previous_members):
    """新しいメンバーを検出する"""
    new_members = []
    previous_account_ids = {m['account_id'] for m in previous_members}

    for member in current_members:
        if member['account_id'] not in previous_account_ids:
            new_members.append({
                "account_id": member['account_id'],
                "name": member['name'],
                "join_time": datetime.now(),
                "role": member['role']
            })
    return new_members

def write_to_log_github(user_name, user_id, message_body, message_id):
    """ログをGitHubファイルに記録する (JSON Lines形式)"""
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "user_name": user_name,
        "user_id": user_id,
        "message_body": message_body,
        "message_id": message_id
    }

    # 既存のログを読み込む
    existing_content, sha = get_github_file_content(LOG_FILE_PATH)
    logs = []
    if existing_content:
        try:
            # JSON Lines 形式で1行ずつ読み込む
            for line in existing_content.splitlines():
                if line.strip():
                    logs.append(json.loads(line))
        except json.JSONDecodeError as e:
            app.logger.warning(f"既存のログファイル '{LOG_FILE_PATH}' のJSON Linesパースに失敗しました。新しいログから開始します: {e}")
            logs = []
    
    logs.append(log_entry)
    
    # JSON Lines形式で書き出す (各JSONオブジェクトが1行)
    new_content_lines = [json.dumps(entry, ensure_ascii=False) for entry in logs]
    new_content = "\n".join(new_content_lines) + "\n" # 最後に改行を追加
    
    commit_message = f"Add log for message_id: {message_id} from {user_name}"
    return update_github_file_content(LOG_FILE_PATH, new_content, commit_message, sha)

# --- その他のヘルパー関数 (変更なし) ---

def count_chatwork_emojis(text):
    """Chatwork絵文字の数をカウントする"""
    return len(CHATWORK_EMOJI_REGEX.findall(text))

def draw_omikuji(is_admin):
    """おみくじを引く"""
    fortunes = ['大吉', '中吉', '吉', '小吉', '凶', '★大凶★']
    special_fortune = '　ゆ　ゆ　ゆ　ス　ペ　シ　ャ　ル　大　吉　'
    
    rand = random.random()
    special_chance = 0.002 # 非管理者の場合 0.2%
    if is_admin:
        special_chance = 0.25 # 管理者の場合 25%

    if rand < special_chance:
        return special_fortune
    else:
        return random.choice(fortunes)

def is_user_admin(account_id, all_members):
    """ユーザーが管理者かどうかを判断する"""
    for member in all_members:
        if member['account_id'] == account_id and member['role'] == 'admin':
            return True
    return False

# --- Webhook エンドポイント ---
@app.route('/webhook', methods=['POST'])
def chatwork_webhook():
    """ChatworkからのWebhookイベントを処理するエンドポイント"""
    try:
        event = request.json
        app.logger.info(f"Webhookイベントを受信しました: {json.dumps(event)}")

        if 'webhook_event_type' not in event:
            app.logger.warning("不正なWebhookイベントです: 'webhook_event_type' が見つかりません。")
            return jsonify({"status": "error", "message": "Invalid webhook event"}), 400

        if event['webhook_event_type'] == 'message_created':
            message_data = event['webhook_event']['message']
            sender_data = event['webhook_event']['account']
            
            message_id = message_data['message_id']
            message_body = message_data['body']
            sender_account_id = sender_data['account_id']
            sender_name = sender_data['name']

            app.logger.info(f"メッセージID: {message_id}, 送信者: {sender_name} ({sender_account_id}) を処理中")

            # ログをGitHubに記録
            write_to_log_github(sender_name, sender_account_id, message_body, message_id)

            # 現在のChatworkメンバーリストを取得（権限チェックのため）
            current_chatwork_members = get_chatwork_members()
            if not current_chatwork_members:
                app.logger.error("現在のChatworkメンバーの取得に失敗しました。権限ベースのアクションをスキップします。")
                return jsonify({"status": "error", "message": "Chatwork members retrieval failed"}), 500

            is_sender_admin = is_user_admin(sender_account_id, current_chatwork_members)

            # 1. [toall] 検知と権限変更
            if '[toall]' in message_body and not is_sender_admin:
                app.logger.info(f"非管理者による [toall] を検出: {sender_name} ({sender_account_id})")
                change_member_role(CHATWORK_GROUP_ID, sender_account_id, 'readonly', sender_name, "[toall] を使用したため")

            # 2. おみくじ機能
            if message_body.strip() == 'おみくじ':
                app.logger.info(f"「おみくじ」を検出: {sender_name} ({sender_account_id})")
                omikuji_result = draw_omikuji(is_sender_admin)
                reply_message = f"[rp aid={sender_account_id} to={CHATWORK_GROUP_ID}-{message_id}]{sender_name}さん、[info][title]おみくじ[/title]おみくじの結果は…\n\n{omikuji_result}\n\nでした！[/info]"
                send_chatwork_message(CHATWORK_GROUP_ID, reply_message)

            # 3. Chatwork絵文字50個以上で権限変更
            if not is_sender_admin:
                emoji_count = count_chatwork_emojis(message_body)
                if emoji_count >= 50:
                    app.logger.info(f"非管理者によるChatwork絵文字50個以上を検出: {sender_name} ({sender_account_id}), 絵文字数: {emoji_count}")
                    change_member_role(CHATWORK_GROUP_ID, sender_account_id, 'readonly', sender_name, f"Chatwork絵文字を{emoji_count}個送信したため")

            return jsonify({"status": "success", "message": "Message processed"})

        else:
            app.logger.info(f"Webhookイベントタイプ '{event['webhook_event_type']}' は処理されません。")
            return jsonify({"status": "ignored", "message": "Event type not handled"}), 200

    except Exception as e:
        app.logger.error(f"Webhook処理中にエラーが発生しました: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# --- メンバー管理のための定期実行エンドポイント ---
@app.route('/update_members', methods=['GET'])
def update_members_endpoint():
    """メンバーリストを更新し、新規参加者がいれば歓迎メッセージを送信するエンドポイント"""
    try:
        previous_members = get_previous_members_from_github()
        current_chatwork_members = get_chatwork_members()

        if not current_chatwork_members:
            app.logger.error("現在のChatworkメンバーの取得に失敗しました。")
            return jsonify({"status": "error", "message": "Failed to retrieve current Chatwork members."}), 500

        new_members = find_new_members(current_chatwork_members, previous_members)

        if new_members:
            total_members = len(current_chatwork_members)
            for member in new_members:
                message = f"[To:{member['account_id']}][pname:{member['account_id']}]さん！こんにちは！\nこれでこのグループの人数は{total_members}人になりました！\nよろしくお願いします！"
                send_chatwork_message(CHATWORK_GROUP_ID, message)
                app.logger.info(f"新しいメンバーを検出しました: {member['name']} ({member['account_id']})")
                # Chatwork APIのレートリミットを考慮し、必要であればここで短い遅延を入れる
                # time.sleep(1) 
        else:
            app.logger.info('新しいメンバーはいません。')

        # メンバー情報をGitHubに保存（更新）
        if not save_current_members_to_github(current_chatwork_members, previous_members):
            return jsonify({"status": "error", "message": "メンバーリストのGitHubへの保存に失敗しました。"}), 500

        return jsonify({"status": "success", "message": "メンバーリストが更新され、新規メンバーが処理されました。"})

    except Exception as e:
        app.logger.error(f"/update_members エンドポイントでエラーが発生しました: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# アプリケーションの実行
if __name__ == '__main__':
    # ローカル開発用: デバッグモードを有効にし、ポート5000で実行
    # 本番環境ではGunicornなどのWSGIサーバーを使用することを推奨
    app.run(debug=True, port=int(os.environ.get('PORT', 5000)))
