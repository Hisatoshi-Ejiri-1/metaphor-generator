import os
import boto3
# 💡 修正ポイント1: 日時を取得するためのライブラリを追加
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
S3_BUCKET_NAME = "metaphor-storage-2026"

print("==================================================")
print(" 🌌 比喩錬成システム ")
print("==================================================")
INPUT_TEXT = input("👉 なるべく具体的に今のモヤモヤや違和感を自由に入力してください（100文字以内）:\n > ")

print()

clean_input = INPUT_TEXT.strip()

if not clean_input:
    print("❌ 入力が空です。プログラムを終了します。")
    exit()

if len(clean_input) > 100:
    print(f"❌ 文字数オーバーです（現在 {len(clean_input)} 文字）。100文字以内で入力してください。")
    exit()

if len(clean_input) < 5:
    print("❌ 入力が短すぎます。もう少し詳しくモヤモヤを教えてください。")
    exit()

unique_chars = set(clean_input)
if len(unique_chars) < 3 or (len(unique_chars) / len(clean_input)) < 0.3:
    print("❌ 不適切な入力パターン（文字列の偏り）が検出されました。")
    exit()

NG_WORDS_FILE = "ng_words.txt"
if os.path.exists(NG_WORDS_FILE):
    with open(NG_WORDS_FILE, "r", encoding="utf-8") as f:
        ng_words = [line.strip() for line in f if line.strip()]
    
    for word in ng_words:
        if word in clean_input:
            print("❌ 不適切な単語が含まれているため、処理を受け付けられません。")
            exit()

client = genai.Client(api_key=GOOGLE_API_KEY)
s3_client = boto3.client("s3")

system_instruction = """
あなたはユーザーの日常のモヤモヤを、極限まで削ぎ落とされた1行の詩的・前衛的な比喩表現へと昇華させる「比喩錬成システム」です。
文学的なキレ味と、冷徹な構造分析を両立させ、ユーザーの心の核心を突く例えを出力してください。

【錬成ロジック】
1. 構造の抽出：ユーザーの感情の具体的なディテール（登場人物や場所）を捨て、その状況が持つ「パターンの骨組み（例：同じ周波数のノイズが続く、形骸化した儀式）」を抽出せよ。
2. 意味の距離の最大化：抽出した構造を、元の事象から最も遠い領域（工業製品のバグ、気象現象、物理的なテクスチャ、化学反応、インフラ）の言葉と衝突させよ。
3. 五感のハック：「壊れた時計」のような凡庸な表現ではなく、光の角度、匂い、手触り、湿度など、五感の解像度を極限まで高めた具体的な「物質」や「現象」として提示せよ。

【出力形式の厳守】
- 前置き、挨拶、比喩の解説は一切出力禁止。
- 必ず「[名詞・形容詞] ＋ [の] ＋ [名詞] みたい」のタイトな1行（名詞句）で出力すること。
- 動詞を使って変化を描くのではなく、静止した一枚の「奇妙な絵画」として差し出すこと。

【錬成お手本（Few-Shot）】
入力：友達が恋愛の話ばっかりしてきてつまらなく感じている
出力：ピンク一色の砂嵐みたい

入力：深夜にスマホをダラダラ見続けて、自己嫌悪に陥っている
出力：蛍光灯の液漏れみたい

入力：就活の面接で、みんな同じような綺麗事を言っている空間
出力：新品のビニール傘のビニール特有の匂いみたい

入力：SNSで他人の充実した投稿を見て、なんとなく焦ってしまう
出力：真夏の無人駅の、加熱された自動販売機の駆動音みたい
"""

print("🔮 比喩を錬成しています…")

try:
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=clean_input,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.8,
        ),
    )
    metaphor_result = response.text.strip()
    print(f"\n✨【錬成結果】:\n{metaphor_result}\n")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{timestamp}.txt"

    
    s3_client.put_object(
        Bucket=S3_BUCKET_NAME,
        Key=file_name,
        Body=metaphor_result.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    print(f"👉 AWS S3への自動保存が正常に完了しました！ (ファイル名: {file_name})")

except Exception as e:
    print(f"\n❌ エラーが発生しました: {e}")