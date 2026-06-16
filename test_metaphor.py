import os
import boto3
import json
from datetime import datetime
import streamlit as st
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
S3_BUCKET_NAME = "metaphor-storage-2026"

st.set_page_config(page_title="比喩生成システム", page_icon="📝", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+JP:wght=300;400;700&display=swap');

    .stApp {
        background-color: #FFFFFF;
        color: #2D3748;
        font-family: 'Noto Serif JP', serif;
    }
    
    .main-title {
        color: #1E3A8A;
        font-size: 28px;
        font-weight: 700;
        letter-spacing: 0.08em;
        border-bottom: 1px solid #E2E8F0;
        padding-bottom: 15px;
        margin-bottom: 30px;
    }
    
    .stButton>button {
        background: #1E3A8A;
        color: white !important;
        border: none;
        padding: 12px 0;
        border-radius: 4px;
        font-weight: 400;
        letter-spacing: 0.15em;
        transition: all 0.3s ease;
        width: 100%;
        margin-top: 10px;
    }
    .stButton>button:hover {
        background: #3B82F6;
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
    }
    
    .result-box {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-left: 3px solid #3B82F6;
        padding: 40px;
        border-radius: 4px;
        margin-top: 30px;
        margin-bottom: 30px;
        text-align: center;
    }
    .result-text {
        font-size: 24px;
        font-weight: 400;
        color: #1A202C;
        line-height: 2.0;
        letter-spacing: 0.05em;
    }
    
    .stTextArea textarea {
        background-color: #FFFFFF !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 4px !important;
        font-size: 15px !important;
    }
    
    [data-testid="stSidebar"] {
        background-color: #F8FAFC;
        border-right: 1px solid #E2E8F0;
    }
    .sidebar-title {
        font-size: 16px;
        font-weight: 700;
        color: #64748B;
        letter-spacing: 0.1em;
        margin-bottom: 20px;
        padding-bottom: 10px;
        border-bottom: 1px solid #E2E8F0;
    }
    .history-item {
        font-size: 13px;
        color: #475569;
        padding: 12px;
        border-bottom: 1px solid #F1F5F9;
        line-height: 1.6;
    }
    </style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_global_timeline():
    return []

global_timeline = get_global_timeline()

if "current_result" not in st.session_state:
    st.session_state.current_result = None

with st.sidebar:
    st.markdown('<div class="sidebar-title">WORLD TIMELINE</div>', unsafe_allow_html=True)
    if not global_timeline:
        st.write("世界中で生成された比喩表現がリアルタイムにここに流れます。")
    else:
        for item in reversed(global_timeline):
            st.markdown(f"""
                <div class="history-item">
                    <span style="color: #3B82F6; font-weight: bold;">Public:</span> 「 {item['metaphor']} 」<br>
                    <span style="color: #94A3B8; font-size: 11px;">ある人の違和感：{item['input']}</span>
                </div>
            """, unsafe_allow_html=True)

st.markdown('<div class="main-title">比喩生成システム</div>', unsafe_allow_html=True)
st.write("あなたの言語化しづらい曖昧な違和感を、文学的な比喩表現へと昇華します！")

INPUT_TEXT = st.text_area("あなたの違和感を入力してください（100文字以内）", placeholder="例：SNSで他人の充実した投稿を見て、なんとなく焦ってしまう")

SHARE_TO_WORLD = st.checkbox("この比喩表現を、世界（左側のタイムライン）に匿名で共有する", value=True)

if st.button("思考を紡ぐ"):
    clean_input = INPUT_TEXT.strip()

    if not clean_input:
        st.error("言葉が入力されていません。")
    elif len(clean_input) > 100:
        st.error(f"100文字以内で入力してください。（現在 {len(clean_input)} 文字）")
    elif len(clean_input) < 5:
        st.error("もう少し詳しくモヤモヤを教えてください。")
    else:
        unique_chars = set(clean_input)
        if len(unique_chars) < 3 or (len(unique_chars) / len(clean_input)) < 0.3:
            st.error("入力内容が不適切です。")
        else:
            NG_WORDS_FILE = "ng_words.txt"
            has_ng_word = False
            
            if os.path.exists(NG_WORDS_FILE):
                with open(NG_WORDS_FILE, "r", encoding="utf-8") as f:
                    ng_words = [line.strip() for line in f if line.strip()]
                for word in ng_words:
                    if word in clean_input:
                        st.error("不適切な言葉が含まれています。")
                        has_ng_word = True
                        break
            
            if not has_ng_word:
                with st.spinner("比喩を生成中です..."):
                    try:
                        client = genai.Client(api_key=GOOGLE_API_KEY)
                        s3_client = boto3.client("s3")

                        system_instruction = """
                        あなたはユーザーの日常のモヤモヤを詩的・前衛的な比喩表現へと昇華させ、その理由をめちゃくちゃフランクに、友達に話しかけるようなテンションで解説するシステムです。
                        必ず指定されたJSONフォーマットのみで出力してください。

                        【出力フォーマット】
                        以下のJSONオブジェクトのみを返してください。
                        {
                            "metaphor": "[名詞・形容詞] ＋ [の] ＋ [名詞] みたい",
                            "explanation": "なぜその比喩になったのか、構造・距離・五感の要素をすべて含めて、フランクに「！」を使いながら1つの文章で解説"
                        }

                        【生成ロジック・トーン】
                        1. 比喩はタイトな1行の名詞句（〜みたい）にすること。
                        2. 解説（explanation）のトーンは「！」をたくさん使い、親しみやすい言葉遣い（〜じゃん！、〜ってこと！、〜だよね！）にすること。
                        3. 「意味の距離」や「構造」といった難しい専門用語は一切使わず、「一見全然関係ないものと結びつけたよ！」や「頭の中のイメージを限界までリアルにした結果！」みたいに、誰でも直感的にわかる表現に噛み砕くこと。
                        """

                        response = client.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=clean_input,
                            config=types.GenerateContentConfig(
                                system_instruction=system_instruction,
                                temperature=0.85,
                                response_mime_type="application/json"
                            ),
                        )
                        
                        data = json.loads(response.text.strip())
                        metaphor_result = data["metaphor"]
                        explanation_result = data["explanation"]

                        st.session_state.current_result = {
                            "metaphor": metaphor_result,
                            "explanation": explanation_result
                        }

                        if SHARE_TO_WORLD:
                            global_timeline.append({
                                "input": clean_input,
                                "metaphor": metaphor_result
                            })

                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        file_name = f"{timestamp}.txt"
                        s3_save_content = f"【元の入力】\n{clean_input}\n\n【生成比喩】\n{metaphor_result}\n\n【解説】\n{explanation_result}"

                        s3_client.put_object(
                            Bucket=S3_BUCKET_NAME,
                            Key=file_name,
                            Body=s3_save_content.encode("utf-8"),
                            ContentType="text/plain; charset=utf-8",
                        )

                    except Exception as e:
                        st.error(f"エラーが発生しました: {e}")

if st.session_state.current_result:
    res = st.session_state.current_result
    
    st.markdown(f"""
        <div class="result-box">
            <div style="color: #64748B; font-size: 11px; font-weight: 700; letter-spacing: 0.2em; margin-bottom: 15px;">ANALYSIS COMPLETED</div>
            <div class="result-text">「 {res['metaphor']} 」</div>
        </div>
    """, unsafe_allow_html=True)

    with st.expander("この比喩が生まれたウラ話！"):
        st.write(res['explanation'])
    
    st.caption(f"システムログは正常にクラウドストレージへ同期されました。")