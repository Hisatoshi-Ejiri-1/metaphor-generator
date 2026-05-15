import os
import boto3
from google import genai
from google.genai import types
# dotenvから環境変数を読み込むためのライブラリ
from dotenv import load_dotenv

# 1. `.env` ファイルに書かれた秘密情報をシステム（環境変数）にロードする
load_dotenv()

# 2. システムから安全にAPIキーを取得（コード上にキーが生書きされなくなりました！）
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
S3_BUCKET_NAME = "metaphor-storage-2026"
INPUT_TEXT = "友達が恋愛の話ばっかりしてきてつまらなく感じている"

# 3. 各種クライアントの初期化（AWSの鍵は以前 set した環境変数から自動で読み込まれます）
client = genai.Client(api_key=GOOGLE_API_KEY)
s3_client = boto3.client("s3")

# 4. 確定したキラープロンプト
system_instruction = """
ユーザーの日常のモヤモヤを、極限まで削ぎ落とされた「単語の組み合わせ（名詞句）」に変換し、鮮烈な「〇〇みたい」という1行の比喩を錬成してください。
【生成ルール】
1. 「無機質な退屈」×「過剰な記号」の衝突（例：ピンク一色の砂嵐）を徹底すること。
2. 動詞は完全禁止。「[形容詞・名詞]＋[の]＋[名詞]みたい」のタイトな形式にすること。
3. 前置きや解説は一切出力せず、比喩の1行のみを出力すること。
"""

print("比喩を錬成中 ＆ クラウドへ保存中...")

try:
    # 5. Geminiで比喩表現を生成
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=INPUT_TEXT,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
        ),
    )
    metaphor_result = response.text.strip()
    print(f"\n【錬成結果】: {metaphor_result}")

    # 6. AWS S3へ自動保存
    s3_client.put_object(
        Bucket=S3_BUCKET_NAME,
        Key="output.txt",
        Body=metaphor_result.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    print("👉 AWS S3への自動保存が正常に完了しました！")

except Exception as e:
    print(f"\nエラーが発生しました: {e}")