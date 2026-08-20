"""
NEXUS site backend.

Serves the static site (index.html, features.html, pricing.html, about_us.html,
style.css, motion.js, images) and powers the chat widget already wired up in
those pages (POST /chat -> {"question": "..."} => {"answer": "..."}).

Run:
    pip install -r requirements.txt
    python server.py

Then open http://localhost:5000
"""

import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

gemini_client = None
if GEMINI_API_KEY:
    from google import genai

    gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# --- Payments (test/sandbox mode) --------------------------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET")
PAYPAL_API_BASE = os.environ.get("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")

PRO_PLAN_NAME = "NEXUS Pro プラン"
PRO_PLAN_PRICE_JPY = 980  # matches the price shown on pricing.html

if STRIPE_SECRET_KEY:
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY

# --- Contact form email --------------------------------------------------
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
CONTACT_EMAIL_TO = os.environ.get("CONTACT_EMAIL_TO") or SMTP_USERNAME


# ---------------------------------------------------------------------------
# Chatbot: keyword-scored intent matching over the site's real content
# (features, pricing, FAQ, company story). No external API needed.
# ---------------------------------------------------------------------------

INTENTS = [
    {
        "name": "greeting",
        "keywords": ["こんにちは", "おはよう", "こんばんは", "はじめまして", "やあ", "hello", "hi"],
        "answer": "こんにちは！NEXUSです。スケジュール管理、スマートホーム連携、メモ・要約、健康サポート、料金プランなど、気になることを聞いてくださいね。",
    },
    {
        "name": "thanks",
        "keywords": ["ありがとう", "thanks", "thank you", "サンキュー", "助かった"],
        "answer": "どういたしまして！他に気になることがあれば、いつでも聞いてください。",
    },
    {
        "name": "overview",
        "keywords": ["nexusとは", "nexusって", "何ができる", "できること", "機能一覧", "概要", "紹介"],
        "answer": (
            "NEXUSは毎日に寄り添うAIアシスタントです。①スケジュール管理（プランナー）"
            "②スマートホーム連携（ガーディアン）③メモ・要約（スクライブ）"
            "④健康サポート（コンパニオン）の4つのモードがあります。詳しく知りたいモードはありますか？"
        ),
    },
    {
        "name": "schedule",
        "keywords": ["スケジュール", "予定", "プランナー", "リマインド", "カレンダー", "音声で予定"],
        "answer": (
            "スケジュール管理（プランナーモード）は、予定を自動で整理して最適なタイミングで教えてくれます。"
            "音声での予定登録、予定の衝突を自動検知、前日リマインドに対応しています。"
        ),
    },
    {
        "name": "smart_home",
        "keywords": ["スマートホーム", "家電", "照明", "エアコン", "ガーディアン", "遠隔操作"],
        "answer": (
            "スマートホーム連携（ガーディアンモード）では、照明やエアコンを声だけで操作できます。"
            "主要メーカーに対応し、外出先からの遠隔操作や、外出時の一括オフにも対応しています。"
        ),
    },
    {
        "name": "notes",
        "keywords": ["メモ", "要約", "スクライブ", "文字起こし", "議事録", "ノート"],
        "answer": (
            "メモ・要約（スクライブモード）は、会話やメモを自動で整理・要約します。"
            "音声の自動文字起こし、要約とタグ付け、キーワード検索に対応しています。"
        ),
    },
    {
        "name": "wellbeing",
        "keywords": ["健康", "睡眠", "水分", "コンパニオン", "休憩", "体調"],
        "answer": (
            "健康サポート（コンパニオンモード）は、生活リズムに合わせて軽くアドバイスします。"
            "睡眠リズムの記録、水分補給の提案、体調メモの簡易記録ができます。"
        ),
    },
    {
        "name": "pricing_overview",
        "keywords": ["料金", "プラン", "値段", "いくら", "price", "価格", "月額"],
        "answer": (
            "料金プランは3種類です。スターター（無料/月）、パートナー（Proプラン・¥980/月・人気）、"
            "コマンダー（Businessプラン・¥2,980/月）。どのプランについて詳しく知りたいですか？"
        ),
    },
    {
        "name": "free_plan",
        "keywords": ["無料プラン", "フリープラン", "スターター", "無料で"],
        "answer": (
            "無料プラン（スターター）は¥0/月です。基本のスケジュール管理、1日10回までの会話、"
            "メモ機能が使えます。まずはここから気軽に始められます。"
        ),
    },
    {
        "name": "pro_plan",
        "keywords": ["proプラン", "プロプラン", "パートナー", "980"],
        "answer": (
            "Proプラン（パートナー）は¥980/月です。無制限の会話、スマートホーム連携、"
            "健康サポート機能が使える、一番人気のプランです。"
        ),
    },
    {
        "name": "business_plan",
        "keywords": ["businessプラン", "ビジネスプラン", "コマンダー", "2980", "法人"],
        "answer": (
            "Businessプラン（コマンダー）は¥2,980/月です。チームでの共有機能、専用サポート、"
            "API連携が含まれます。基本は5名までのご利用で、それ以上のチームはお問い合わせください。"
        ),
    },
    {
        "name": "plan_change",
        "keywords": ["プラン変更", "アップグレード", "ダウングレード", "変更できます"],
        "answer": "はい、プランはいつでもアップグレード・ダウングレードが可能です。差額は日割り計算で調整されます。",
    },
    {
        "name": "cancel",
        "keywords": ["解約", "キャンセル", "退会", "やめたい"],
        "answer": "はい、契約期間の縛りはなく、いつでも解約可能です。",
    },
    {
        "name": "free_plan_limits",
        "keywords": ["無料プランでも", "全部の機能", "無料でも使えます"],
        "answer": (
            "基本のスケジュール管理とメモ機能は無料プランでもご利用いただけます。"
            "スマートホーム連携や健康サポートはProプラン以上が対象です。"
        ),
    },
    {
        "name": "business_team_size",
        "keywords": ["何人まで", "人数", "チーム人数", "何名"],
        "answer": "Businessプランは基本5名までとなっており、それ以上のチームでのご利用はお問い合わせください。",
    },
    {
        "name": "company",
        "keywords": ["会社", "設立", "誰が作った", "開発者", "起源", "nexusについて", "運営会社"],
        "answer": (
            "NEXUSは2023年、「本当に必要な時だけそっと支えてくれるAIを作りたい」という開発者チームの想いから生まれました。"
            "現在は12万人以上に利用され、平均評価は4.7です。"
        ),
    },
    {
        "name": "philosophy",
        "keywords": ["哲学", "理念", "コンセプト", "静かであるべき", "考え方"],
        "answer": "NEXUSの哲学は「テクノロジーは、静かであるべき」。目立つ通知や複雑な設定ではなく、必要な瞬間に必要なだけ寄り添うことを目指しています。",
    },
    {
        "name": "future",
        "keywords": ["未来", "今後", "これから", "展望", "ロードマップ"],
        "answer": "現在は個人の日常サポートが中心ですが、「一人から、みんなへ」を合言葉に、家庭やチームでも使える機能へ少しずつ広げています。",
    },
    {
        "name": "contact",
        "keywords": ["問い合わせ", "連絡", "サポート窓口", "相談したい", "contact"],
        "answer": "お問い合わせは About Usページ下部のフォームからお願いします（about_us.html の「お問い合わせ」セクションです）。",
    },
    {
        "name": "signup",
        "keywords": ["始める", "登録", "サインアップ", "使ってみたい", "申し込み"],
        "answer": "Plansページの「始める」ボタンから、無料のスターターですぐに始められます。",
    },
]

FALLBACK_ANSWER = (
    "すみません、うまく理解できませんでした。"
    "「スケジュール管理」「スマートホーム連携」「メモ・要約」「健康サポート」「料金プラン」"
    "「会社について」などについて聞いてみてください。"
)

EMPTY_ANSWER = "質問を入力してください。"


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[\s、。！？!?,.]", "", text)
    return text


def find_answer(question: str) -> str:
    question = (question or "").strip()
    if not question:
        return EMPTY_ANSWER

    normalized = normalize(question)

    best_intent = None
    best_score = 0
    for intent in INTENTS:
        score = sum(1 for kw in intent["keywords"] if normalize(kw) in normalized)
        if score > best_score:
            best_score = score
            best_intent = intent

    if best_intent is None:
        return FALLBACK_ANSWER
    return best_intent["answer"]


# ---------------------------------------------------------------------------
# Optional: Gemini-powered answers, grounded in the same site content above.
# Used automatically when GEMINI_API_KEY is set; falls back to the
# rule-based find_answer() above if the key is missing or the call fails,
# so the chatbot always works even offline.
# ---------------------------------------------------------------------------

SITE_KNOWLEDGE = "\n".join(
    f"- {intent['answer']}" for intent in INTENTS if intent["name"] not in ("greeting", "thanks")
)

SYSTEM_INSTRUCTION = (
    "あなたはAIアシスタントアプリ「NEXUS」の公式サイトに埋め込まれたチャットボットです。"
    "以下の情報のみを根拠に、日本語で簡潔・親切に答えてください。"
    "情報にない質問については、正直に分からないと伝え、About Usページの問い合わせフォームを案内してください。\n\n"
    f"# NEXUSの情報\n{SITE_KNOWLEDGE}"
)


def ask_gemini(question: str) -> str | None:
    if not gemini_client:
        return None
    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=question,
            config={"system_instruction": SYSTEM_INSTRUCTION, "max_output_tokens": 300},
        )
        text = (response.text or "").strip()
        return text or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"answer": EMPTY_ANSWER})

    answer = ask_gemini(question) or find_answer(question)
    return jsonify({"answer": answer})


# --- Payments -----------------------------------------------------------
# Both providers run in test/sandbox mode by default (sandbox PayPal API
# base URL, and whatever mode a Stripe "sk_test_..." key is in) — no real
# money moves until real "live" keys are put in .env.


@app.route("/payment-config")
def payment_config():
    """Public (non-secret) info the frontend needs to render payment buttons."""
    return jsonify(
        {
            "paypalClientId": PAYPAL_CLIENT_ID,
            "stripeEnabled": bool(STRIPE_SECRET_KEY),
            "paypalEnabled": bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET),
            "priceJpy": PRO_PLAN_PRICE_JPY,
        }
    )


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripeが設定されていません。サーバーの.envにSTRIPE_SECRET_KEYを設定してください。"}), 503

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "jpy",
                        "product_data": {"name": PRO_PLAN_NAME},
                        "unit_amount": PRO_PLAN_PRICE_JPY,
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }
            ],
            success_url=request.host_url + "pricing.html?checkout=success",
            cancel_url=request.host_url + "pricing.html?checkout=cancel",
        )
        return jsonify({"url": session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


def get_paypal_access_token() -> str:
    resp = requests.post(
        f"{PAYPAL_API_BASE}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


@app.route("/paypal/create-order", methods=["POST"])
def paypal_create_order():
    if not (PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET):
        return jsonify({"error": "PayPalが設定されていません。サーバーの.envにPAYPAL_CLIENT_ID/SECRETを設定してください。"}), 503

    try:
        token = get_paypal_access_token()
        resp = requests.post(
            f"{PAYPAL_API_BASE}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "amount": {"currency_code": "JPY", "value": str(PRO_PLAN_PRICE_JPY)},
                        "description": f"{PRO_PLAN_NAME}（初月分・手動更新）",
                    }
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/paypal/capture-order/<order_id>", methods=["POST"])
def paypal_capture_order(order_id):
    if not (PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET):
        return jsonify({"error": "PayPalが設定されていません。"}), 503

    try:
        token = get_paypal_access_token()
        resp = requests.post(
            f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# --- Contact form ---------------------------------------------------------
# about_us.html posts a plain HTML form here (no JS needed to submit); we
# email the site owner and redirect back with a status flag the page reads
# from the query string to show a success/error banner.


@app.route("/contact", methods=["POST"])
def contact():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    message = (request.form.get("message") or "").strip()

    if not (name and email and message):
        return redirect("/about_us.html?contact=missing#contact")

    if not (SMTP_USERNAME and SMTP_PASSWORD and CONTACT_EMAIL_TO):
        return redirect("/about_us.html?contact=unconfigured#contact")

    try:
        msg = EmailMessage()
        msg["Subject"] = f"[NEXUS] お問い合わせ: {name}"
        msg["From"] = SMTP_USERNAME
        msg["To"] = CONTACT_EMAIL_TO
        msg["Reply-To"] = email
        msg.set_content(f"名前: {name}\nメール: {email}\n\n{message}")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)

        return redirect("/about_us.html?contact=success#contact")
    except Exception:
        return redirect("/about_us.html?contact=error#contact")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
