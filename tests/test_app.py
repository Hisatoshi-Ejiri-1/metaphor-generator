"""DynamoDB と Bedrock を moto / スタブで置き換えて、app.py の処理を確かめる。

    pip install -r requirements.txt pytest "moto[dynamodb]"
    pytest -q
"""
import importlib
import os
import sys

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from moto import mock_aws

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABLE = "metaphor-generator-timeline"


@pytest.fixture()
def app():
    os.environ.update({
        "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_REGION": "ap-northeast-1", "AWS_DEFAULT_REGION": "ap-northeast-1",
        "TABLE_NAME": TABLE,
    })
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-northeast-1").create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        module = importlib.reload(sys.modules["app"]) if "app" in sys.modules else importlib.import_module("app")
        module.timeline_table.clear()
        module.bedrock.clear()
        module.fetch_timeline.clear()
        yield module


def test_post_then_fetch_newest_first(app):
    app.post_to_timeline("ひとつめのできごと", "比喩1", "解説1")
    app.post_to_timeline("ふたつめのできごと", "比喩2", "解説2")
    items = app.fetch_timeline()
    assert [i["metaphor"] for i in items] == ["比喩2", "比喩1"]
    assert "delete_token_hash" not in items[0]  # ハッシュは画面側に渡さない


def test_delete_needs_correct_token(app):
    post_id, token = app.post_to_timeline("消してみるできごと", "比喩", "解説")
    assert app.delete_post(post_id, "wrong-token") is False
    assert len(app.fetch_timeline()) == 1
    assert app.delete_post(post_id, token) is True
    assert app.fetch_timeline() == []


def test_delete_missing_post_returns_false(app):
    assert app.delete_post("2026-01-01T00:00:00.000000Z#deadbeef", "x") is False


def test_post_rejects_bad_length(app):
    with pytest.raises(ValueError):
        app.post_to_timeline("短い", "比喩", "解説")
    with pytest.raises(ValueError):
        app.post_to_timeline("ちょうどいい長さ", "", "解説")


def test_post_ids_sort_by_time(app):
    from datetime import datetime, timezone
    a = app.new_post_id(datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc))
    b = app.new_post_id(datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc))
    assert a < b


def test_parse_json_reply_handles_code_fence(app):
    reply = '```json\n{"metaphor": "湯気みたい", "explanation": "あったかい！"}\n```'
    assert app.parse_json_reply(reply)["metaphor"] == "湯気みたい"


def _stub_bedrock(app):
    client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
    stubber = Stubber(client)
    app.bedrock.clear()
    app.bedrock = lambda: client
    return stubber


def test_generate_metaphor_with_stubbed_bedrock(app):
    stubber = _stub_bedrock(app)
    stubber.add_response("converse", {
        "output": {"message": {"role": "assistant", "content": [
            {"text": '{"metaphor": "冬の朝のパンの湯気みたい", "explanation": "じんわりあったまる感じ！"}'}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        "metrics": {"latencyMs": 1},
    })
    with stubber:
        metaphor, explanation = app.generate_metaphor("テストで良い点を取った")
    assert metaphor == "冬の朝のパンの湯気みたい"
    assert explanation


@pytest.mark.parametrize("code, keyword", [
    ("ThrottlingException", "上限"),
    ("ServiceUnavailableException", "混み合って"),
    ("AccessDeniedException", "設定"),
])
def test_error_messages(app, code, keyword):
    err = ClientError({"Error": {"Code": code, "Message": "x"}}, "Converse")
    assert keyword in app.explain_generate_error(err)
