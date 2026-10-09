from __future__ import annotations

import os
import re

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
)
from flask_sqlalchemy import SQLAlchemy

# OpenAI SDK（公式）
from openai import OpenAI


# =========================================================
# Flask 基本設定
# =========================================================

app = Flask(__name__)

# セッションを使うために必要
# Renderでは環境変数 SECRET_KEY を使用
# ローカルでは development-secret-key を使用
app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "development-secret-key"
)

# RenderではPostgreSQL、
# ローカルではSQLite（stories.db）を使用
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "sqlite:///stories.db"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


# =========================================================
# データベース
# =========================================================

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


# テーブルがなければ作成
with app.app_context():
    db.create_all()


# =========================================================
# OpenAI設定
# =========================================================

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

MIN_CHARS = 380
MAX_CHARS = 420


def _jp_len(text: str) -> int:
    """日本語の文字数を数える"""
    return len(text.strip())


def _clean(text: str) -> str:
    """余計な前置きや引用符を軽く除去"""
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
        return (
            "（エラー）OPENAI_API_KEY が未設定です。"
            "Renderの環境変数に設定してください。"
        )

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

    resp = client.responses.create(
        model=MODEL,
        input=[
            {
                "role": "system",
                "content": system,
            },
            {
                "role": "user",
                "content": user,
            },
        ],
    )

    text = resp.output_text

    return _clean(text)


# =========================================================
# 通常ページ
# =========================================================

@app.get("/")
def home():
    return render_template(
        "index.html",
        story=None,
        error=None,
        form={},
    )


@app.get("/index.html")
def index_html():
    return home()


@app.get("/ai-app-lab.html")
def ai_app_lab():
    return render_template("ai-app-lab.html")


# =========================================================
# 管理者ログイン
# =========================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        password = request.form.get(
            "password",
            "",
        )

        admin_password = os.getenv(
            "ADMIN_PASSWORD",
            "",
        )

        if (
            admin_password
            and password == admin_password
        ):
            session["admin_logged_in"] = True

            return redirect(
                url_for("add_story")
            )

        return render_template(
            "admin_login.html",
            error="パスワードが違います",
        )

    return render_template(
        "admin_login.html",
        error=None,
    )


# =========================================================
# 管理者ログアウト
# =========================================================

@app.get("/admin/logout")
def admin_logout():

    session.pop(
        "admin_logged_in",
        None,
    )

    return redirect(
        url_for("admin_login")
    )


# =========================================================
# 作品登録
# =========================================================

@app.route(
    "/admin/add",
    methods=["GET", "POST"],
)
def add_story():

    # ログインしていなければログイン画面へ
    if not session.get("admin_logged_in"):

        return redirect(
            url_for("admin_login")
        )

    if request.method == "POST":

        content = request.form.get(
            "content",
            "",
        ).strip()

        # 本文が空なら登録しない
        if not content:

            return render_template(
                "add_story.html",
                error="小説本文を入力してください。",
            )

        story = Story(
            theme=request.form.get(
                "theme",
                "",
            ).strip(),

            genre=request.form.get(
                "genre",
                "",
            ).strip(),

            protagonist=request.form.get(
                "protagonist",
                "",
            ).strip(),

            tone=request.form.get(
                "tone",
                "",
            ).strip(),

            twist=request.form.get(
                "twist",
                "",
            ).strip(),

            forbidden=request.form.get(
                "forbidden",
                "",
            ).strip(),

            content=content,
        )

        db.session.add(story)
        db.session.commit()

        return redirect(
            url_for("admin_list")
        )

    return render_template(
        "add_story.html",
        error=None,
    )


# =========================================================
# DB登録作品一覧（管理用）
# =========================================================

@app.get("/admin/list")
def admin_list():

    # 一覧も管理者だけ見られるようにする
    if not session.get("admin_logged_in"):

        return redirect(
            url_for("admin_login")
        )

    stories = Story.query.order_by(
        Story.id.desc()
    ).all()

    html = """
    <h1>DB登録作品一覧</h1>

    <p>
        <a href="/admin/add">
            新しい作品を登録
        </a>
         |
        <a href="/admin/logout">
            ログアウト
        </a>
    </p>
    """

    for story in stories:

        html += f"""
        <hr>

        <p>
        ID: {story.id}
        </p>

        <p>
        テーマ: {story.theme or ""}
        </p>

        <p>
        ジャンル: {story.genre or ""}
        </p>

        <p>
        本文: {story.content}
        </p>
        """

    return html


# =========================================================
# AI小説生成
# =========================================================

@app.post("/generate")
def generate():

    form = {
        "theme":
            request.form.get(
                "theme",
                "",
            ).strip(),

        "genre":
            request.form.get(
                "genre",
                "",
            ).strip(),

        "protagonist":
            request.form.get(
                "protagonist",
                "",
            ).strip(),

        "tone":
            request.form.get(
                "tone",
                "",
            ).strip(),

        "twist":
            request.form.get(
                "twist",
                "",
            ).strip(),

        "forbidden":
            request.form.get(
                "forbidden",
                "",
            ).strip(),
    }

    story = generate_story(**form)

    if story.startswith("（エラー）"):

        return render_template(
            "index.html",
            story=None,
            error=story,
            form=form,
        )

    # ---------------------------------------------
    # 文字数が380〜420字から外れた場合
    # 1回だけ再生成
    # ---------------------------------------------

    n = _jp_len(story)

    if (
        n < MIN_CHARS
        or n > MAX_CHARS
    ):

        form2 = dict(form)

        form2["twist"] = (
            form2["twist"]
            + "／字数は必ず380〜420字に調整"
        ).strip("／")

        story2 = generate_story(**form2)

        if not story2.startswith("（エラー）"):
            story = story2

    # ---------------------------------------------
    # 生成した小説をDBへ保存
    # ---------------------------------------------

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

    return render_template(
        "index.html",
        story=story,
        error=None,
        form=form,
    )


# =========================================================
# ローカル起動
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "5000",
            )
        ),
    )