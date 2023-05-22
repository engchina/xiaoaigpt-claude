import os
from dataclasses import dataclass, field

LATEST_ASK_API = "https://userprofile.mina.mi.com/device_profile/v2/conversation?source=dialogu&hardware={hardware}&timestamp={timestamp}&limit=2"
COOKIE_TEMPLATE = "deviceId={device_id}; serviceToken={service_token}; userId={user_id}"
PROMPT = "请用100字以内回答，并且请快速生成前2句话。请只回答文字不要带链接。请只说明事实。请简要扼要回答问题。请只包含必要信息，删除次要内容。"


@dataclass
class Config:
    hardware: str = os.getenv("SOUND_TYPE", "")  # 音箱型号
    account: str = os.getenv("MI_USER", "")
    password: str = os.getenv("MI_PASS", "")
    mi_did: str = os.getenv("MI_DID", "")
    last_ask_api: str = LATEST_ASK_API
    cookie_template: str = COOKIE_TEMPLATE
    use_command: bool = False
    prompt: str = PROMPT
    slack_claude_user_token: str = os.getenv("SLACK_CLAUDE_USER_TOKEN", "")
    slack_claude_bot_id: str = os.getenv("SLACK_CLAUDE_BOT_ID", "")
