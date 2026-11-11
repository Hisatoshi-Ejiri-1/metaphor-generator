import os
import re
import json
import html
import time
import uuid
import hashlib
import secrets
import threading
from collections import deque
from datetime import datetime, timezone

import boto3
import streamlit as st
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from urllib.parse import quote

# 設定はすべて環境変数から読む（ECSではタスク定義、手元では export で渡す）。
# APIキーやDBのパスワードは存在しない。AWSへの認証はECSタスクのIAMロールが行う。
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
# 日本国内の推論プロファイル（推論を国内リージョンに限定する）
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "jp.anthropic.claude-haiku-4-5-20251001-v1:0")
TABLE_NAME = os.getenv("TABLE_NAME", "metaphor-generator-timeline")
APP_URL = os.getenv("APP_URL", "")

# 外部通信はタイムアウトを短めにし、一時的なエラーは boto3 に3回まで再試行させる
BOTO_CONFIG = Config(
    region_name=AWS_REGION,
    connect_timeout=5,
    read_timeout=30,
    retries={"max_attempts": 3, "mode": "standard"},
)

# DynamoDB：全投稿を同じパーティションに入れ、ソートキー（投稿日時＋ランダム）で新しい順に並べる
TIMELINE_PK = "TIMELINE"

MAX_LEN = 100
NG_WORDS_FILE = "ng_words.txt"

# 連打・荒らし対策
COOLDOWN_SEC = 10          # 1人が次に生成できるまでの間隔
SESSION_LIMIT = 30         # 1人（1セッション）あたりの生成回数の上限
GLOBAL_PER_MINUTE = 8      # サイト全体で1分あたりに生成できる回数

st.set_page_config(page_title="比喩生成システム", page_icon="☕", layout="wide")

# ---------- ピクセルアート ----------
# 1文字 = 1マス。好きな絵に描き換えられます（行の長さはそろえる）
#   k: 紺（線）  b: 空色  l: 薄い青（湯気）  w: 白  . : 透明
PIXEL_ART = [
    "....l..l........",
    "...l..l.........",
    "....l..l........",
    "...l..l.........",
    "................",
    ".kkkkkkkkkk.....",
    ".kwwwwwwwwkkkk..",
    ".kwwbbwbbwk..k..",
    ".kwwbbbbbwk..k..",
    ".kwwwbbbwwk..k..",
    ".kwwwwbwwwkkkk..",
    ".kwwwwwwwwk.....",
    "..kwwwwwwk......",
    "...kkkkkk.......",
    "kkkkkkkkkkkkkk..",
    "................",
]
PIXEL_COLORS = {"k": "#1B2A3D", "b": "#1185FE", "l": "#A9CCF7", "w": "#FFFFFF"}


def pixel_svg(rows, size=4):
    h, w = len(rows), max(len(r) for r in rows)
    rects = "".join(
        f'<rect x="{x}" y="{y}" width="1" height="1" fill="{PIXEL_COLORS[c]}"/>'
        for y, row in enumerate(rows) for x, c in enumerate(row) if c in PIXEL_COLORS
    )
    return (f'<svg class="pixel" viewBox="0 0 {w} {h}" width="{w*size}" height="{h*size}" '
            f'shape-rendering="crispEdges" aria-hidden="true">{rects}</svg>')


st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Klee+One:wght@400;600&family=Zen+Maru+Gothic:wght@400;500;700&display=swap');

:root {
    --sky: #1185FE;
    --sky-deep: #0A6BD6;
    --mist: #EEF5FF;
    --line: #A9CCF7;
    --ink: #1B2A3D;
    --muted: #6B7A8F;
    --alert: #C2453A;
}

header[data-testid="stHeader"], [data-testid="stToolbar"], footer, #MainMenu,
[data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; }

.stApp { background: #FFFFFF; color: var(--ink); }
.stApp, .stApp p, .stApp label, .stApp textarea, .stApp button {
    font-family: 'Zen Maru Gothic', sans-serif;
}
.block-container { max-width: 68rem; padding: 3.5rem 1.5rem 5rem; }

/* 見出し：手書き風＋ゆがんだ下線 */
.brand { display: flex; align-items: flex-end; gap: 1rem; margin-bottom: 0.5rem; }
.pixel { image-rendering: pixelated; flex-shrink: 0; }
.stApp .title {
    font-family: 'Klee One', serif;
    font-weight: 600;
    font-size: 1.9rem !important;
    line-height: 1.3 !important;
    color: var(--ink);
    margin: 0;
}
.squiggle { display: block; width: 11rem; height: 10px; margin-top: 2px; }
.stApp .lead { color: var(--muted); font-size: 0.92rem !important; line-height: 1.9; margin: 1rem 0 2.5rem; }

/* 注文票：手描きっぽい枠 */
.st-key-order {
    background: var(--mist);
    border: 1.5px solid var(--line);
    border-radius: 255px 14px 225px 14px / 14px 225px 14px 255px;
    padding: 1.6rem 1.6rem 1.4rem;
}
.st-key-order .stTextArea label p { font-family: 'Klee One', serif; font-size: 1rem; color: var(--ink); }
.st-key-order [data-baseweb="textarea"] { border: none !important; border-radius: 10px !important; background: #FFFFFF !important; }
.st-key-order textarea { background: #FFFFFF !important; font-size: 1rem !important; line-height: 1.8 !important; color: var(--ink) !important; }
.st-key-order .stCheckbox label p { font-size: 0.85rem; color: var(--muted); }

.st-key-generate button {
    background: var(--sky);
    color: #FFFFFF;
    border: none;
    border-radius: 999px;
    padding: 0.55rem 1.8rem;
    font-weight: 700;
}
.st-key-generate button:hover { background: var(--sky-deep); color: #FFFFFF; }
.st-key-generate button:focus-visible { outline: 2px solid var(--sky); outline-offset: 3px; }

/* 結果カード：テーブルに置いたように少し傾ける */
.card {
    background: #FFFFFF;
    border: 1.5px solid var(--ink);
    border-radius: 14px 225px 14px 255px / 255px 14px 225px 14px;
    padding: 2rem 1.8rem 1.6rem;
    margin: 2.5rem 0.5rem 1rem;
    transform: rotate(-1.2deg);
    box-shadow: 5px 6px 0 var(--mist);
    animation: settle 0.6s ease-out both;
}
.stApp .metaphor {
    font-family: 'Klee One', serif;
    font-size: clamp(1.5rem, 4.5vw, 2rem) !important;
    line-height: 1.6;
    color: var(--ink);
}
.stApp .explanation { color: var(--muted); font-size: 0.9rem !important; line-height: 1.95; margin-top: 1rem; }
@keyframes settle { from { opacity: 0; transform: rotate(-4deg) translateY(-8px); } to { opacity: 1; transform: rotate(-1.2deg); } }
@media (prefers-reduced-motion: reduce) { .card { animation: none; } }

/* みんなの比喩：小さなメモが並ぶ */
.stApp .tl-heading {
    font-family: 'Klee One', serif;
    font-weight: 600;
    font-size: 1.15rem !important;
    color: var(--ink);
    margin: 0 0 1rem;
}
.memo {
    border-bottom: 1.5px dashed var(--line);
    padding: 0.9rem 0.2rem 0.8rem;
}
.stApp .tl-metaphor { font-family: 'Klee One', serif; font-size: 1.05rem !important; line-height: 1.7; color: var(--ink); }
.stApp .tl-source { font-size: 0.78rem !important; line-height: 1.7; color: var(--muted); margin-top: 0.2rem; }
.stApp .note { font-size: 0.85rem !important; color: var(--muted); margin-top: 0.6rem; }
.stApp .note.alert { color: var(--alert); }

[class*="st-key-del_"] button {
    background: transparent; border: none; color: var(--muted);
    font-size: 0.78rem; padding: 0; min-height: 0;
}
[class*="st-key-del_"] button:hover { color: var(--alert); background: transparent; }
.stApp .stMarkdown { margin-bottom: 0 !important; }

/* 結果の下の操作 */
.st-key-again button {
    background: #FFFFFF;
    color: var(--sky);
    border: 1.5px solid var(--sky);
    border-radius: 999px;
    padding: 0.4rem 1.3rem;
    font-weight: 700;
}
.st-key-again button:hover { background: var(--mist); color: var(--sky-deep); border-color: var(--sky-deep); }

/* みんなの比喩：解説を開く */
.memo details { margin-top: 0.35rem; }
.memo summary {
    font-size: 0.78rem;
    color: var(--sky);
    cursor: pointer;
    list-style: none;
    width: fit-content;
}
.memo summary::-webkit-details-marker { display: none; }
.memo summary::before { content: "＋ "; }
.memo details[open] summary::before { content: "－ "; }
.memo summary:focus-visible { outline: 2px solid var(--sky); outline-offset: 2px; border-radius: 4px; }
.stApp .tl-explanation { font-size: 0.82rem; line-height: 1.85; color: var(--ink); margin-top: 0.3rem; }

@media (min-width: 900px) {
    .st-key-timeline { padding-left: 2rem; border-left: 1.5px dashed var(--line); }
}
</style>
""", unsafe_allow_html=True)


def log(message):
    """CloudWatch Logs に確実に出す（print はためこまれて出ないことがある）"""
    print(message, flush=True)


def note(text, alert=False):
    cls = "note alert" if alert else "note"
    st.markdown(f'<div class="{cls}">{html.escape(text)}</div>', unsafe_allow_html=True)


# ---------- AWS クライアント ----------

@st.cache_resource
def bedrock():
    return boto3.client("bedrock-runtime", config=BOTO_CONFIG)


@st.cache_resource
def timeline_table():
    return boto3.resource("dynamodb", config=BOTO_CONFIG).Table(TABLE_NAME)


# ---------- みんなの比喩（DynamoDB） ----------

@st.cache_data(ttl=30, show_spinner=False)
def fetch_timeline():
    """新しい順に20件。失敗したら例外をそのまま上げる（キャッシュされない）"""
    res = timeline_table().query(
        KeyConditionExpression=Key("pk").eq(TIMELINE_PK),
        ScanIndexForward=False,
        Limit=20,
        # 削除用のハッシュは画面に不要なので読み出さない
        ProjectionExpression="sk, user_input, metaphor, explanation",
    )
    return [
        {"id": i["sk"], "user_input": i["user_input"], "metaphor": i["metaphor"],
         "explanation": i.get("explanation", "")}
        for i in res.get("Items", [])
    ]


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_post_id(now=None):
    """ソートキー。日時の文字列順＝投稿順になるようにし、同時刻の衝突はランダム部分で避ける"""
    now = now or datetime.now(timezone.utc)
    return f"{now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')}#{uuid.uuid4().hex[:8]}"


def post_to_timeline(user_input, metaphor, explanation):
    """投稿して (id, 削除用の合言葉) を返す。DBには合言葉のハッシュだけを保存する"""
    # Supabase ではRLSで掛けていた条件。DBへはこのアプリ（IAMロール）しか書けないので、ここで守る
    if not (5 <= len(user_input) <= MAX_LEN and 1 <= len(metaphor) <= 200 and len(explanation) <= 600):
        raise ValueError("投稿の長さが条件を満たしていません")
    token = secrets.token_urlsafe(24)
    post_id = new_post_id()
    timeline_table().put_item(
        Item={
            "pk": TIMELINE_PK,
            "sk": post_id,
            "user_input": user_input,
            "metaphor": metaphor,
            "explanation": explanation,
            "delete_token_hash": hash_token(token),
        },
        ConditionExpression="attribute_not_exists(sk)",  # 万一IDが重なっても上書きしない
    )
    fetch_timeline.clear()
    return post_id, token


def delete_post(post_id, token):
    """合言葉のハッシュが一致したときだけ消す（条件付き削除。照合と削除を1回の操作で行う）"""
    try:
        timeline_table().delete_item(
            Key={"pk": TIMELINE_PK, "sk": post_id},
            ConditionExpression=Attr("delete_token_hash").eq(hash_token(token)),
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    fetch_timeline.clear()
    return True


# ---------- 入力チェック ----------

@st.cache_data(ttl=600, show_spinner=False)
def load_ng_words():
    """環境変数 NG_WORDS（1行に1語）と ng_words.txt の両方から読む"""
    words = os.getenv("NG_WORDS", "").splitlines()
    if os.path.exists(NG_WORDS_FILE):
        with open(NG_WORDS_FILE, "r", encoding="utf-8") as f:
            words += f.read().splitlines()
    return sorted({w.strip() for w in words if w.strip()})


@st.cache_resource
def global_limiter():
    """サイト全体（同じサーバー上の全員）で共有する、直近1分間の生成時刻。
    メモリ上に持つので、ECSのタスクを2台以上にすると台数分だけ上限が緩む点に注意"""
    return {"times": deque(), "lock": threading.Lock()}


def check_rate_limit():
    """生成してよければ None、だめなら理由を返す。通ったら回数を記録する"""
    now = time.time()
    ss = st.session_state
    wait = COOLDOWN_SEC - (now - ss.get("last_generated", 0))
    if wait > 0:
        return f"続けて生成できるのは{COOLDOWN_SEC}秒おきです。あと{int(wait) + 1}秒待ってから押してください。"
    if ss.get("generate_count", 0) >= SESSION_LIMIT:
        return f"1回の訪問で生成できるのは{SESSION_LIMIT}回までです。時間をおいてから、また来てください。"

    g = global_limiter()
    with g["lock"]:
        while g["times"] and now - g["times"][0] > 60:
            g["times"].popleft()
        if len(g["times"]) >= GLOBAL_PER_MINUTE:
            return "いま混み合っています。1分ほど待ってから、もう一度押してください。"
        g["times"].append(now)

    ss.last_generated = now
    ss.generate_count = ss.get("generate_count", 0) + 1
    return None


def validate(text):
    """問題があればメッセージを返す。なければ None"""
    if not text:
        return "できごとや気持ちを入力してください。"
    if len(text) < 5:
        return "5文字以上で入力してください。もう少し詳しく書くと、比喩も具体的になります。"
    unique = set(text)
    if len(unique) < 3 or len(unique) / len(text) < 0.3:
        return "同じ文字の繰り返しが多いため、生成できません。文章で入力してください。"
    if any(w in text for w in load_ng_words()):
        return "使えない言葉が含まれています。言い換えて入力してください。"
    return None


# ---------- 生成 ----------

SYSTEM_INSTRUCTION = """
あなたはユーザーの日常のあらゆるエピソード（嬉しかったこと、楽しかったこと、モヤモヤした違和感など）を詩的・前衛的な比喩表現へと昇華させ、その理由を友達に話しかけるようなフランクなテンションで解説するシステムです。
必ず指定されたJSONフォーマットのみで出力してください。

【出力フォーマット】
{
    "metaphor": "[名詞・形容詞] ＋ [の] ＋ [名詞] みたい",
    "explanation": "なぜその比喩になったのか、エピソードの感情（喜び、焦り、感動など）の要素を含めて、フランクに1つの文章で解説"
}

【生成ロジック・トーン】
1. 比喩はタイトな1行の名詞句（〜みたい）にすること。ネガティブな内容なら鋭く冷徹に、ポジティブな内容なら色彩豊かで美しい比喩を紡ぐこと。
2. 解説は親しみやすい言葉遣い（〜じゃん！、〜ってこと！、〜だよね！）にすること。「！」は2〜3個まで。
3. 「意味の距離」や「構造」といった専門用語は使わず、誰でも直感的にわかる表現に噛み砕くこと。

【例】
入力：テストで良い点数を取れて、心がじわっと温かくなった
出力：{"metaphor": "冬の朝に届いた、焼きたてのパンの湯気みたい", "explanation": "頑張った分がふわっと返ってきて、体の内側からじんわりあったまる感じ！寒い朝ほど湯気って嬉しいじゃん、それと同じってこと！"}

入力：SNSで同級生の充実した投稿を見て、自分だけ置いていかれた気がした
出力：{"metaphor": "動く歩道に乗り遅れた、片方だけの靴みたい", "explanation": "みんなは勝手に前へ運ばれていくのに、自分だけその場に取り残されてる感じ！しかも片方だけってところに、なんか中途半端な焦りが出てるでしょ！"}
"""


# Bedrock のエラーコード → 画面の文言
BUSY_CODES = {"ServiceUnavailableException", "InternalServerException",
              "ModelNotReadyException", "ModelTimeoutException"}
LIMIT_CODES = {"ThrottlingException", "ServiceQuotaExceededException"}
CONFIG_CODES = {"AccessDeniedException", "ValidationException", "ResourceNotFoundException",
                "UnrecognizedClientException"}


def explain_generate_error(e):
    """例外から、画面に出す文言を決める"""
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "")
        if code in LIMIT_CODES:
            return "いまは生成の上限に達しています。しばらく待ってから、もう一度押してください。"
        if code in BUSY_CODES:
            return "生成サービスが混み合っています。1〜2分待ってから、もう一度押してください。"
        if code in CONFIG_CODES:
            return "生成サービスの設定に問題があり、生成できません。管理者に連絡してください。"
    if isinstance(e, BotoCoreError):  # 通信エラー・認証情報が見つからない など
        return "生成サービスに接続できませんでした。少し時間をおいて、もう一度押してください。"
    return "比喩の生成に失敗しました。少し時間をおいて、もう一度押してください。"


def parse_json_reply(text):
    """モデルの返答からJSON部分だけを取り出す（```json で囲まれていても読めるように）"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0) if match else text)


def generate_metaphor(text, avoid=None):
    """avoid に前回の比喩を渡すと、それとは違う発想で作らせる"""
    contents = text
    if avoid:
        contents += f"\n\n（前回は「{avoid}」という比喩でした。これとは違うものに例えてください）"
    response = bedrock().converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": SYSTEM_INSTRUCTION}],
        messages=[{"role": "user", "content": [{"text": contents}]}],
        inferenceConfig={"temperature": 0.85, "maxTokens": 500},
    )
    reply = "".join(part.get("text", "") for part in response["output"]["message"]["content"])
    data = parse_json_reply(reply)
    metaphor = str(data.get("metaphor", "")).strip()
    explanation = str(data.get("explanation", "")).strip()
    if not metaphor:
        raise ValueError("比喩が空で返ってきました")
    return metaphor, explanation


# ---------- 共有 ----------

def share_bar(metaphor):
    """コピーとXへの投稿。クリップボードはブラウザ側でしか触れないので小さなHTMLで作る"""
    share_text = f"「{metaphor}」\n#比喩生成システム" + (f"\n{APP_URL}" if APP_URL else "")
    x_url = "https://x.com/intent/post?text=" + quote(share_text)
    # LLMの出力を埋め込むので、</script> などで抜け出せないようにする
    text_js = json.dumps(metaphor, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    st.iframe(f"""
<link href="https://fonts.googleapis.com/css2?family=Zen+Maru+Gothic:wght@700&display=swap" rel="stylesheet">
<style>
  body {{ margin: 0; font-family: 'Zen Maru Gothic', sans-serif; }}
  .bar {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
  .bar button, .bar a {{
    font: inherit; font-size: 14px; font-weight: 700; text-decoration: none;
    padding: 6px 18px; border-radius: 999px; cursor: pointer;
    border: 1.5px solid #A9CCF7; background: #EEF5FF; color: #1B2A3D;
  }}
  .bar button:hover, .bar a:hover {{ border-color: #1185FE; }}
  .bar button:focus-visible, .bar a:focus-visible {{ outline: 2px solid #1185FE; outline-offset: 2px; }}
</style>
<div class="bar">
  <button id="copy" type="button">コピー</button>
  <a href="{html.escape(x_url)}" target="_blank" rel="noopener">Xでポスト</a>
</div>
<script>
  const text = {text_js};
  const btn = document.getElementById("copy");
  btn.addEventListener("click", async () => {{
    try {{
      await navigator.clipboard.writeText(text);
    }} catch (e) {{
      const t = document.createElement("textarea");
      t.value = text; document.body.appendChild(t); t.select();
      document.execCommand("copy"); t.remove();
    }}
    btn.textContent = "コピーしました";
    setTimeout(() => (btn.textContent = "コピー"), 1800);
  }});
</script>
""", width=260, height=44)


# ---------- 画面 ----------

if "current_result" not in st.session_state:
    st.session_state.current_result = None
# 投稿ID → 削除用の合言葉。古いバージョンのページでは set で残っていることがあるので作り直す
if not isinstance(st.session_state.get("my_post_ids"), dict):
    st.session_state.my_post_ids = {}

SQUIGGLE = ('<svg class="squiggle" viewBox="0 0 176 10" preserveAspectRatio="none" aria-hidden="true">'
            '<path d="M2 6 C 20 2, 34 9, 52 5 S 88 2, 104 6 S 140 9, 158 4 S 170 5, 174 6" '
            'fill="none" stroke="#1185FE" stroke-width="2.2" stroke-linecap="round"/></svg>')

st.markdown(
    f'<div class="brand">{pixel_svg(PIXEL_ART)}<div><div class="title">比喩生成システム</div>{SQUIGGLE}</div></div>'
    '<div class="lead">うまく言葉にできない違和感や、忘れたくない小さなできごとを、一行の比喩にしてお出しします。</div>',
    unsafe_allow_html=True,
)

def run_generation(text, share, avoid=None):
    """比喩を作って、結果を session_state に入れる。共有がオンならタイムラインにも載せる"""
    limited = check_rate_limit()
    if limited:
        note(limited, alert=True)
        return

    metaphor = None
    with st.spinner("比喩を考えています…"):
        try:
            metaphor, explanation = generate_metaphor(text, avoid=avoid)
        except json.JSONDecodeError:
            note("うまく比喩にできませんでした。もう一度押してください。", alert=True)
        except Exception as e:
            log(f"[generate] {type(e).__name__}: {e}")
            note(explain_generate_error(e), alert=True)
    if not metaphor:
        return

    st.session_state.current_result = {"metaphor": metaphor, "explanation": explanation}
    st.session_state.last_input = text
    if share:
        try:
            post_id, token = post_to_timeline(text, metaphor, explanation)
            if post_id is not None:
                st.session_state.my_post_ids[post_id] = token
        except Exception as e:
            log(f"[insert] {type(e).__name__}: {e}")
            st.session_state.share_failed = True


left, right = st.columns([3, 2], gap="large")

with left:
    with st.container(key="order"):
        input_text = st.text_area(
            "きょうのできごと",
            max_chars=MAX_LEN,
            placeholder="例：テストで良い点数を取れて、心がじわっと温かくなった",
        )
        share = st.checkbox("みんなの比喩に匿名で載せる", value=True)
        clicked = st.button("比喩にする", key="generate")

    if clicked:
        clean_input = input_text.strip()
        problem = validate(clean_input)
        if problem:
            note(problem, alert=True)
        else:
            run_generation(clean_input, share)
    elif st.session_state.pop("regen", False) and st.session_state.get("last_input"):
        prev = st.session_state.current_result["metaphor"] if st.session_state.current_result else None
        run_generation(st.session_state.last_input, share, avoid=prev)

    if st.session_state.current_result:
        res = st.session_state.current_result
        explanation_html = (f'<div class="explanation">{html.escape(res["explanation"])}</div>'
                            if res["explanation"] else "")
        st.markdown(
            f'<div class="card"><div class="metaphor">{html.escape(res["metaphor"])}</div>{explanation_html}</div>',
            unsafe_allow_html=True,
        )
        with st.container(horizontal=True, gap="small", vertical_alignment="center"):
            st.button("別の比喩にする", key="again", on_click=lambda: st.session_state.update(regen=True))
            share_bar(res["metaphor"])
        if st.session_state.pop("share_failed", False):
            note("比喩はできましたが、みんなの比喩には載せられませんでした。")

with right:
    with st.container(key="timeline"):
        st.markdown('<div class="tl-heading">みんなの比喩</div>', unsafe_allow_html=True)

        try:
            timeline = fetch_timeline()
        except Exception as e:
            log(f"[timeline] {type(e).__name__}: {e}")
            timeline = None
            note("みんなの比喩を読み込めませんでした。しばらくしてから再読み込みしてください。")

        if timeline == []:
            note("まだ投稿がありません。最初の一行を載せてみてください。")
        elif timeline:
            for item in timeline:
                explanation = (item.get("explanation") or "").strip()
                details = (f'<details><summary>解説を読む</summary>'
                           f'<div class="tl-explanation">{html.escape(explanation)}</div></details>'
                           if explanation else "")
                st.markdown(
                    f'<div class="memo"><div class="tl-metaphor">{html.escape(item["metaphor"])}</div>'
                    f'<div class="tl-source">{html.escape(item["user_input"])}</div>{details}</div>',
                    unsafe_allow_html=True,
                )
                if item["id"] in st.session_state.my_post_ids:
                    # IDには「#」や「:」が入るので、ボタンのkeyにはハッシュを使う
                    button_key = "del_" + hashlib.sha1(item["id"].encode()).hexdigest()[:12]
                    if st.button("削除", key=button_key):
                        try:
                            token = st.session_state.my_post_ids[item["id"]]
                            if not delete_post(item["id"], token):
                                raise RuntimeError("合言葉が一致しませんでした")
                            st.session_state.my_post_ids.pop(item["id"], None)
                            st.rerun()
                        except Exception as e:
                            log(f"[delete] {type(e).__name__}: {e}")
                            note("削除できませんでした。もう一度押してください。", alert=True)
