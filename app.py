import os
import json
import html
import time
import hashlib
import secrets
import threading
from collections import deque

import streamlit as st
from urllib.parse import quote
from google import genai
from google.genai import types, errors
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()



def setting(name):
    """環境変数（.env）→ Streamlit の Secrets の順に探す。Secrets は見出しの下に入っていても見つける"""
    value = os.getenv(name)
    if value:
        return value
    try:
        if name in st.secrets:
            return str(st.secrets[name])
        for section in st.secrets.values():
            if hasattr(section, "get") and section.get(name):
                return str(section.get(name))
    except Exception:  # Secrets が未設定の環境
        pass
    return None


GOOGLE_API_KEY = setting("GEMINI_API_KEY")
SUPABASE_URL = setting("SUPABASE_URL")
SUPABASE_KEY = setting("SUPABASE_KEY")

# 使うモデル。Secrets の GEMINI_MODEL で変えられる（コードを書き換えずに切り替えるため）
GEMINI_MODEL = setting("GEMINI_MODEL") or "gemini-2.5-flash"
# メインのモデルが提供終了（404）だったときに、順に試す予備のモデル（カンマ区切り）
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in (setting("GEMINI_FALLBACK_MODELS") or "gemini-3.8-flash,gemini-3.5-flash-lite").split(",")
    if m.strip()
]

TABLE = "global_timeline"
APP_URL = os.getenv("APP_URL", "https://metaphor-generator.streamlit.app/")
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
    """Streamlit Cloud のログに確実に出す（print はためこまれて出ないことがある）"""
    print(message, flush=True)


def note(text, alert=False):
    cls = "note alert" if alert else "note"
    st.markdown(f'<div class="{cls}">{html.escape(text)}</div>', unsafe_allow_html=True)


# ---------- Supabase ----------

@st.cache_resource
def _supabase_client(url, key):
    return create_client(url, key)


def get_supabase():
    """「未設定」の結果は覚えない。Secrets を後から入れても、次の表示から接続できる"""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return None
    return _supabase_client(SUPABASE_URL, SUPABASE_KEY)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_timeline():
    """失敗したら例外をそのまま上げる（キャッシュされない）"""
    sb = get_supabase()
    res = sb.table(TABLE).select("id, user_input, metaphor, explanation").order("created_at", desc=True).limit(20).execute()
    return res.data


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def post_to_timeline(user_input, metaphor, explanation):
    """投稿して (id, 削除用の合言葉) を返す。DBには合言葉のハッシュだけを保存する"""
    token = secrets.token_urlsafe(24)
    res = get_supabase().table(TABLE).insert({
        "user_input": user_input,
        "metaphor": metaphor,
        "explanation": explanation,
        "delete_token_hash": hash_token(token),
    }).execute()
    fetch_timeline.clear()
    post_id = res.data[0]["id"] if res.data else None
    return post_id, token


def delete_post(post_id, token):
    """合言葉が一致したときだけDB側の関数が削除する（RLSで直接の削除は禁止）"""
    res = get_supabase().rpc("delete_own_post", {"p_id": post_id, "p_token": token}).execute()
    fetch_timeline.clear()
    return bool(res.data)


# ---------- 入力チェック ----------

@st.cache_data(ttl=600, show_spinner=False)
def load_ng_words():
    """本番は Streamlit の Secrets（NG_WORDS）、手元では ng_words.txt から読む"""
    words = []
    try:
        raw = st.secrets.get("NG_WORDS", "")
    except Exception:  # Secrets が未設定の環境
        raw = ""
    if isinstance(raw, str):
        words += raw.splitlines()
    else:
        words += list(raw)
    if os.path.exists(NG_WORDS_FILE):
        with open(NG_WORDS_FILE, "r", encoding="utf-8") as f:
            words += f.read().splitlines()
    return sorted({w.strip() for w in words if w.strip()})


@st.cache_resource
def global_limiter():
    """サイト全体（同じサーバー上の全員）で共有する、直近1分間の生成時刻"""
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


def call_with_retry(fn):
    """Google側の一時的なエラー（5xx）なら、2秒待って1回だけやり直す"""
    try:
        return fn()
    except errors.ServerError as e:
        log(f"[generate] retry after {e.code}: {e}")
        time.sleep(2)
        return fn()


def explain_generate_error(e):
    """例外から、画面に出す文言を決める"""
    code = getattr(e, "code", None)
    if code == 404:
        return "生成に使うモデルが使えなくなっています。管理者に連絡してください。"
    if code == 429:
        return "いまは生成の上限に達しています。しばらく（長いときは翌日まで）待ってから、もう一度押してください。"
    if isinstance(e, errors.ServerError):
        return "生成サービスが混み合っています。1〜2分待ってから、もう一度押してください。"
    if code in (400, 401, 403):
        return "生成サービスの設定に問題があり、生成できません。管理者に連絡してください。"
    return "比喩の生成に失敗しました。少し時間をおいて、もう一度押してください。"


def generate_metaphor(text, avoid=None):
    """avoid に前回の比喩を渡すと、それとは違う発想で作らせる"""
    contents = text
    if avoid:
        contents += f"\n\n（前回は「{avoid}」という比喩でした。これとは違うものに例えてください）"
    client = genai.Client(api_key=GOOGLE_API_KEY)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.85,
        response_mime_type="application/json",
    )
    response = None
    for i, model in enumerate([GEMINI_MODEL] + GEMINI_FALLBACK_MODELS):
        try:
            response = call_with_retry(lambda: client.models.generate_content(
                model=model, contents=contents, config=config,
            ))
            if i > 0:
                log(f"[generate] {GEMINI_MODEL} が使えないため {model} で生成しました。GEMINI_MODEL の更新を検討してください")
            break
        except errors.ClientError as e:
            # 404 = モデルが見つからない（提供終了など）。それ以外のエラーはそのまま上げる
            if e.code != 404 or i == len(GEMINI_FALLBACK_MODELS):
                raise
            log(f"[generate] {model} が見つかりません（404）。予備のモデルを試します")
    data = json.loads(response.text.strip())
    metaphor = str(data.get("metaphor", "")).strip()
    explanation = str(data.get("explanation", "")).strip()
    if not metaphor:
        raise ValueError("比喩が空で返ってきました")
    return metaphor, explanation


# ---------- 共有 ----------

def share_bar(metaphor):
    """コピーとXへの投稿。クリップボードはブラウザ側でしか触れないので小さなHTMLで作る"""
    share_text = f"「{metaphor}」\n#比喩生成システム\n{APP_URL}"
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
    if not GOOGLE_API_KEY:
        note("生成に必要な設定（GEMINI_API_KEY）がありません。管理者に連絡してください。", alert=True)
        return
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
    if share and get_supabase():
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

        if not get_supabase():
            note("みんなの比喩は、いま表示できません（データベースが未設定です）。")
        else:
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
                        if st.button("削除", key=f"del_{item['id']}"):
                            try:
                                token = st.session_state.my_post_ids[item["id"]]
                                if not delete_post(item["id"], token):
                                    raise RuntimeError("delete_own_post returned false")
                                st.session_state.my_post_ids.pop(item["id"], None)
                                st.rerun()
                            except Exception as e:
                                log(f"[delete] {type(e).__name__}: {e}")
                                note("削除できませんでした。もう一度押してください。", alert=True)
