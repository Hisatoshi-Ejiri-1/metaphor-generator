import os
import json
import html

import streamlit as st
from google import genai
from google.genai import types
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

TABLE = "global_timeline"
MAX_LEN = 100
NG_WORDS_FILE = "ng_words.txt"

st.set_page_config(page_title="比喩生成システム", page_icon="📝", layout="centered")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@400;600&family=Zen+Kaku+Gothic+New:wght@400;500&display=swap');

:root {
    --paper: #FFFFFF;
    --ink: #26272B;
    --muted: #7A7C82;
    --faint: #A9AAAE;
    --rule: #E6E6E3;
    --alert: #9B3B2E;
}

/* Streamlit 標準の飾りを消す */
header[data-testid="stHeader"], [data-testid="stToolbar"], footer, #MainMenu,
[data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; }

.stApp { background: var(--paper); color: var(--ink); }
.stApp, .stApp p, .stApp label, .stApp textarea, .stApp button, .stApp li {
    font-family: 'Zen Kaku Gothic New', sans-serif;
}
.block-container { max-width: 36rem; padding: 5rem 1.25rem 6rem; }

.title {
    font-family: 'Shippori Mincho', serif;
    font-weight: 600;
    font-size: 1.5rem;
    letter-spacing: 0.04em;
    margin: 0 0 0.75rem;
    color: var(--ink);
}
.lead { color: var(--muted); font-size: 0.9rem; line-height: 1.9; margin-bottom: 2.5rem; }

/* 入力欄：下線だけ */
.stTextArea label p { font-size: 0.85rem; color: var(--muted); }
.stTextArea [data-baseweb="textarea"] {
    border: none !important;
    border-bottom: 1px solid #D4D4D1 !important;
    border-radius: 0 !important;
    background: transparent !important;
}
.stTextArea [data-baseweb="textarea"]:focus-within { border-bottom-color: var(--ink) !important; }
.stTextArea textarea {
    background: transparent !important;
    font-size: 1rem !important;
    line-height: 1.9 !important;
    padding: 0.5rem 0 !important;
    color: var(--ink) !important;
}
.stCheckbox label p { font-size: 0.85rem; color: var(--muted); }

/* 生成ボタン */
.st-key-generate button {
    background: var(--ink);
    color: #FFFFFF;
    border: none;
    border-radius: 2px;
    padding: 0.55rem 1.8rem;
    font-weight: 500;
    letter-spacing: 0.08em;
}
.st-key-generate button:hover { background: #45474D; color: #FFFFFF; }
.st-key-generate button:focus-visible { outline: 2px solid var(--ink); outline-offset: 3px; }

/* 結果：ここだけ大きく */
.metaphor {
    font-family: 'Shippori Mincho', serif;
    font-size: clamp(1.6rem, 5.5vw, 2.25rem);
    line-height: 1.6;
    color: var(--ink);
    margin: 4rem 0 1.5rem;
    animation: appear 0.9s ease-out both;
}
.explanation { color: #5E6066; font-size: 0.92rem; line-height: 2; }
@keyframes appear { from { opacity: 0; } to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .metaphor { animation: none; } }

/* みんなの比喩 */
.tl-heading {
    font-size: 0.95rem;
    font-weight: 500;
    color: var(--ink);
    margin: 5rem 0 0.5rem;
    padding-top: 2rem;
    border-top: 1px solid var(--rule);
}
.tl-metaphor { font-family: 'Shippori Mincho', serif; font-size: 1.05rem; line-height: 1.8; color: var(--ink); margin-top: 1.25rem; }
.tl-source { font-size: 0.8rem; line-height: 1.7; color: var(--faint); }
.note { font-size: 0.85rem; color: var(--muted); }
.note.alert { color: var(--alert); }

[class*="st-key-del_"] button {
    background: transparent;
    border: none;
    color: var(--faint);
    font-size: 0.8rem;
    padding: 0;
    min-height: 0;
}
[class*="st-key-del_"] button:hover { color: var(--alert); background: transparent; }

/* Streamlit 標準スタイルより優先させる */
.stApp .title { font-size: 1.5rem !important; line-height: 1.5 !important; }
.stApp .lead { font-size: 0.9rem !important; }
.stApp .metaphor { font-size: clamp(1.6rem, 5.5vw, 2.25rem) !important; }
.stApp .tl-heading { font-size: 0.95rem !important; }
.stApp .tl-metaphor { font-size: 1.05rem !important; }
.stApp .tl-source { font-size: 0.8rem !important; }
.stApp .stTextArea [data-baseweb="textarea"] > div,
.stApp .stTextArea [data-baseweb="base-input"] { background: transparent !important; }
.stApp .stMarkdown { margin-bottom: 0 !important; }
</style>
""", unsafe_allow_html=True)


def note(text, alert=False):
    cls = "note alert" if alert else "note"
    st.markdown(f'<div class="{cls}">{html.escape(text)}</div>', unsafe_allow_html=True)


# ---------- Supabase ----------

@st.cache_resource
def get_supabase():
    if not (SUPABASE_URL and SUPABASE_KEY):
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_timeline():
    """失敗したら例外をそのまま上げる（キャッシュされない）"""
    sb = get_supabase()
    res = sb.table(TABLE).select("id, user_input, metaphor").order("created_at", desc=True).limit(20).execute()
    return res.data


def post_to_timeline(user_input, metaphor, explanation):
    sb = get_supabase()
    res = sb.table(TABLE).insert({
        "user_input": user_input,
        "metaphor": metaphor,
        "explanation": explanation,
    }).execute()
    fetch_timeline.clear()
    return res.data[0]["id"] if res.data else None


def delete_post(post_id):
    get_supabase().table(TABLE).delete().eq("id", post_id).execute()
    fetch_timeline.clear()


# ---------- 入力チェック ----------

def load_ng_words():
    if not os.path.exists(NG_WORDS_FILE):
        return []
    with open(NG_WORDS_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


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


def generate_metaphor(text):
    client = genai.Client(api_key=GOOGLE_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.85,
            response_mime_type="application/json",
        ),
    )
    data = json.loads(response.text.strip())
    metaphor = str(data.get("metaphor", "")).strip()
    explanation = str(data.get("explanation", "")).strip()
    if not metaphor:
        raise ValueError("比喩が空で返ってきました")
    return metaphor, explanation


# ---------- 画面 ----------

if "current_result" not in st.session_state:
    st.session_state.current_result = None
if "my_post_ids" not in st.session_state:
    st.session_state.my_post_ids = set()

st.markdown('<div class="title">比喩生成システム</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="lead">うまく言葉にできない違和感や、忘れたくない小さなできごとを、一行の比喩にします。</div>',
    unsafe_allow_html=True,
)

input_text = st.text_area(
    "できごとや気持ち",
    max_chars=MAX_LEN,
    placeholder="例：テストで良い点数を取れて、心がじわっと温かくなった",
)
share = st.checkbox("みんなの比喩に匿名で載せる", value=True)

if st.button("比喩にする", key="generate"):
    clean_input = input_text.strip()
    problem = validate(clean_input)
    if problem:
        note(problem, alert=True)
    elif not GOOGLE_API_KEY:
        note("生成に必要な設定（GEMINI_API_KEY）がありません。管理者に連絡してください。", alert=True)
    else:
        with st.spinner("比喩を考えています…"):
            try:
                metaphor, explanation = generate_metaphor(clean_input)
            except json.JSONDecodeError:
                metaphor = None
                note("うまく比喩にできませんでした。もう一度「比喩にする」を押してください。", alert=True)
            except Exception as e:
                print(f"[generate] {type(e).__name__}: {e}")
                metaphor = None
                note("比喩の生成に失敗しました。少し時間をおいて、もう一度押してください。", alert=True)

        if metaphor:
            st.session_state.current_result = {"metaphor": metaphor, "explanation": explanation}
            if share and get_supabase():
                try:
                    post_id = post_to_timeline(clean_input, metaphor, explanation)
                    if post_id is not None:
                        st.session_state.my_post_ids.add(post_id)
                except Exception as e:
                    print(f"[insert] {type(e).__name__}: {e}")
                    st.session_state.share_failed = True

if st.session_state.current_result:
    res = st.session_state.current_result
    st.markdown(f'<div class="metaphor">{html.escape(res["metaphor"])}</div>', unsafe_allow_html=True)
    if res["explanation"]:
        st.markdown(f'<div class="explanation">{html.escape(res["explanation"])}</div>', unsafe_allow_html=True)
    if st.session_state.pop("share_failed", False):
        note("比喩はできましたが、みんなの比喩には載せられませんでした。")

# ---------- みんなの比喩 ----------

st.markdown('<div class="tl-heading">みんなの比喩</div>', unsafe_allow_html=True)

if not get_supabase():
    note("みんなの比喩は、いま表示できません（データベースが未設定です）。")
else:
    try:
        timeline = fetch_timeline()
    except Exception as e:
        print(f"[timeline] {type(e).__name__}: {e}")
        timeline = None
        note("みんなの比喩を読み込めませんでした。しばらくしてから再読み込みしてください。")

    if timeline == []:
        note("まだ投稿がありません。最初の一行を載せてみてください。")
    elif timeline:
        for item in timeline:
            st.markdown(
                f'<div class="tl-metaphor">{html.escape(item["metaphor"])}</div>'
                f'<div class="tl-source">{html.escape(item["user_input"])}</div>',
                unsafe_allow_html=True,
            )
            if item["id"] in st.session_state.my_post_ids:
                if st.button("削除", key=f"del_{item['id']}"):
                    try:
                        delete_post(item["id"])
                        st.session_state.my_post_ids.discard(item["id"])
                        st.rerun()
                    except Exception as e:
                        print(f"[delete] {type(e).__name__}: {e}")
                        note("削除できませんでした。もう一度押してください。", alert=True)
