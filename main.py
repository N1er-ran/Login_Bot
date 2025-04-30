import discord
from discord.ext import commands
from discord.ui import Button, View
import json
import gspread
import pytz
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# 設定ファイル読込
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

TOKEN = config['bot_token']
CHANNEL_ID = int(config['channel_id'])
SPREADSHEET_NAME = config['spreadsheet_name']

# Google Sheets 認証
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("google_service.json", scope)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME)

# シートを参照
log_sheet = sheet.worksheet('log')
management_sheet = sheet.worksheet('管理')
settings_sheet = sheet.worksheet('設定')

# Bot設定
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# 日本標準時 (JST) のタイムゾーンを指定
jst = pytz.timezone('Asia/Tokyo')

# 設定をディクショナリに格納する関数
def get_settings_from_sheet():
    settings = settings_sheet.get_all_values()   #シート全体を取得

    #設定名をキーに、「値」をバリューとしてディクショナリに格納
    settings_dict = {}
    for row in settings[1:]: # 1行目はヘッダーなのでスキップ
        key = row[0] # 設定名(キー)
        value = row[1] # 設定値(バリュー)
        settings_dict[key] = value
    return settings_dict

# 管理シートからユーザーIDに一致する行を取得する関数
def get_user_data(user_id: str):
    management_data = management_sheet.get_all_values()

    # 1行目はヘッダーなのでスキップして、データ部分を抽出
    for row in management_data[1:]:
        if row[0] == user_id:  # ユーザーIDが一致する行を見つける
            return {
                'ユーザーID': row[0],
                'ユーザー名': row[1],
                'ログイン回数': row[2],
                '募集': row[3],
                'VC接続時間': row[4],
                'ボーナス': row[5],
                '総ポイント': row[6]
            }
    return None  # 一致するユーザーIDが見つからなかった場合

# ログイン済チェック
def already_logged_in_today(user_id: str) -> bool:
    now = datetime.now(jst)
    
    # スプレッドシートから設定をディクショナリとして取得
    settings_dict = get_settings_from_sheet() 
    switch_time_hour = int(settings_dict.get("日切り替え", 6))

    #日本時間での今日の日付(朝６時から新しい日付に切り換え)
    today = now.replace(hour=switch_time_hour, minute=0, second=0, microsecond=0)

    if now < today:
        #現在が切り替え時間前なら、昨日として扱う
        today -= timedelta(days=1)

    today_str = today.strftime("%Y/%m/%d")

    records = log_sheet.get_all_values()  # シート全体を取得

    for row in reversed(records):  # 末尾（最新）からチェックすることで高速化
        if len(row) >= 4 and row[0] == user_id and row[2].startswith(today_str) and row[3] == "ログイン":  # 種別が「ログイン」かつ本日の場合だけ
            return True
    return False

# ボタンクラス
class LoginButton(Button):
    def __init__(self):
        super().__init__(label="LOGIN", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)

        # 現在の日付を取得（すべてのケースで利用）
        today = datetime.now(jst).strftime("%Y/%m/%d %H:%M:%S")

        # すでにログイン済みかをチェック
        logged_in = already_logged_in_today(user_id)

        if not logged_in:
            # ログイン情報の記録
            log_sheet.append_row([
            	user_id,  # ユーザID
            	str(interaction.user),  # ユーザ名
            	today,  # ログ記載時間（変更済みのフォーマット）
            	"ログイン",  # 種別（ログイン）
            	"",  # VC接続時間（後で記録される可能性がある）
            	""   # VC接続終了時間（後で記録される可能性がある）
	        ])
        
            # ログインできたことをユーザーに伝える
            login_message = "ログインできました！"
        
        else:
            # すでにログイン済みの場合
            login_message = "本日はすでにログイン済みです。"
        
		# ユーザーIDに一致する情報を管理シートから取得
        user_data = get_user_data(user_id)
        
        if not user_data:
 			# ユーザーIDが見つからない場合、日切り替え時間を提示しながらポイント照会ができないことを伝える
            settings_dict = get_settings_from_sheet()
            switch_time_hour = int(settings_dict.get("日切り替え", 6))  # 日切り替え時間
            point_message = f"ユーザーIDが見つかりませんでした。明日の{switch_time_hour}時以降にポイントの照会ができるようになります。"
            await interaction.response.send_message(login_message, ephemeral=True)
            await interaction.followup.send(point_message, ephemeral=True)

            print(f'{today}に{str(interaction.user)}がログインしました。')  # コンソールに表示するメッセージ
            return

        # Embedを作成して、ユーザー情報を表示
        embed = discord.Embed(
            title="ユーザー情報",
            description=f"{str(interaction.user)} の情報",
            color=discord.Color.blue()
        )

        # ユーザー情報をEmbedに追加
        for key, value in user_data.items():
            embed.add_field(name=key, value=value, inline=False)

        # ユーザー情報をフッターに追加
        embed.set_footer(text=f"ユーザーID: {user_data['ユーザーID']}")

        # ユーザーのアバターをサムネイルとして設定
        embed.set_thumbnail(url=interaction.user.avatar.url)

        # ログイン成功メッセージとユーザー情報を一緒に送信
        await interaction.response.send_message(f"{login_message}", ephemeral=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
        # コンソールにログイン完了メッセージを表示
        print(f'{today}に{str(interaction.user)}がログインしました。')  # コンソールに表示するメッセージ

# Bot起動時にボタンを送信
@bot.event
async def on_ready():
    # コンソールにログイン完了メッセージを表示
    print(f'{bot.user} としてログインしました。')  # コンソールに表示するメッセージ

    # チャンネルの情報を取得し、ボタンを送信
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        view = View(timeout=None)
        view.add_item(LoginButton())
        await channel.send("ログインするには以下のボタンを押してください。", view=view)

# エラーハンドリング
@bot.event
async def on_error(event, *args, **kwargs):
    print(f"Error in event {event}: {args}")

bot.run(TOKEN)