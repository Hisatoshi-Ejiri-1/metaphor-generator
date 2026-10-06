# 互換用の入口。本体は app.py。
# Streamlit Cloud の公開設定が「test_metaphor.py」を起動するようになっているため、
# 設定を app.py に切り替えるまで、このファイル経由で app.py を実行する。
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
