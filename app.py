from __future__ import annotations

import os
import re

from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy

# OpenAI SDK（公式）
from openai import OpenAI

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

class Story(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    theme = db.Column(db.String(100))
    genre = db.Column(db.String(100))
    protagonist = db.Column(db.String(100))
    tone = db.Column(db.String(100))
    twist = db.Column(db.String(200))
    forbidden = db.Column(db.String(200))
    content = db.Column(db.Text, nullable=False)

with app.app_context():
    db.create_all()

# ---- 設定（必要ならここを変更） ----
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")  # 例：軽量モデル
MIN_CHARS = 380
MAX_CHARS = 420


def _jp_len(text: str) -> int:
    # 日本語の「だいたい400字」チェック用（単純に文字数）
    return len(text.strip())


def _clean(text: str) -> str:
    # 余計な前置きや引用符を軽く除去
    t = text.strip()
    t = re.sub(r"^「|」$", "", t)
    return t.strip()


def generate_story(
    theme: str,
    genre: str,
    protagonist: str,
    tone: str,
    twist: str,
    forbidden: str,
) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "（エラー）OPENAI_API_KEY が未設定です。Renderの環境変数に設定してください。"

    client = OpenAI(api_key=api_key)

    system = (
        "あなたは日本語のショートショート作家です。"
        "ユーザー条件に沿って、約400字（380〜420字）の小説を1本だけ出力してください。"
        "前置き・解説・タイトル案の羅列は不要。本文のみ。"
        "固有名詞の無断使用や個人情報の生成は避ける。"
    )

    user = f"""
# 条件
- テーマ: {theme or "自由"}
- ジャンル: {genre or "自由"}
- 主人公: {protagonist or "自由"}
- 文体/トーン: {tone or "読みやすい、少し余韻が残る"}
- どんでん返し/仕掛け: {twist or "任意（弱めでもOK）"}
- 入れないでほしい要素: {forbidden or "特になし"}

# 出力ルール
- 本文のみ（タイトル不要）
- 380〜420字
- 説教臭くしない
""".strip()

    # Responses API（公式）
    resp = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = resp.output_text
    return _clean(text)


@app.get("/")
def home():
    return render_template("index.html", story=None, error=None, form={})


@app.post("/generate")
def generate():
    form = {
        "theme": request.form.get("theme", "").strip(),
        "genre": request.form.get("genre", "").strip(),
        "protagonist": request.form.get("protagonist", "").strip(),
        "tone": request.form.get("tone", "").strip(),
        "twist": request.form.get("twist", "").strip(),
        "forbidden": request.form.get("forbidden", "").strip(),
    }

    story = generate_story(**form)
    if story.startswith("（エラー）"):
        return render_template("index.html", story=None, error=story, form=form)

    # 文字数が外れたら、1回だけ「字数調整」で再生成
    n = _jp_len(story)
    if n < MIN_CHARS or n > MAX_CHARS:
        form2 = dict(form)
        form2["twist"] = (form2["twist"] + "／字数は必ず380〜420字に調整").strip("／")
        story2 = generate_story(**form2)
        if not story2.startswith("（エラー）"):
            story = story2
    
    # 生成した小説をDBに保存
    saved_story = Story(
        theme=form["theme"],
        genre=form["genre"],
        protagonist=form["protagonist"],
        tone=form["tone"],
        twist=form["twist"],
        forbidden=form["forbidden"],
        content=story,
    )

    db.session.add(saved_story)
    db.session.commit()

    return render_template("index.html", story=story, error=None, form=form)


if __name__ == "__main__":
    # ローカル動作確認用
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))