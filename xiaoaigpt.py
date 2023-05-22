#!/usr/bin/env python3
import asyncio
import json
import os
import subprocess
from http.cookies import SimpleCookie
from pathlib import Path
import threading
import time
from aiohttp import ClientSession
from requests.utils import cookiejar_from_dict
from config import Config
from minaservice import MiNAService
from miaccount import MiAccount
from slackclient import SlackClient

HARDWARE_COMMAND_DICT = {
    "L05B": "5-3",  # 小爱音箱Play
    "L05C": "5-3",  # 小爱音箱Play增强版
    "L06A": "5-1",  # 小爱音箱
    "L17A": "7-3",  # 小爱音箱Sound Pro
    "LX01": "5-1",  # 小爱音箱mini
    "LX04": "5-1",  # 小爱触屏音箱
    "LX05A": "5-1",  # 小爱音箱遥控版（黑色）
    "LX06": "5-1",  # 小爱音箱Pro（黑色）
    "LX5A": "5-1",  # 小爱音箱遥控版（黑色）
    "M03A": "7-3",  # 小爱Sound Move
    "S12A": "5-1",  # 小爱音箱
    "X08E": "7-3",  # 红米小爱触屏音箱Pro
    # add more here
}

SWITCH = True  # 是否开启chatgpt回答


# HELP FUNCTION
def parse_cookie_string(cookie_string):
    cookie = SimpleCookie()
    cookie.load(cookie_string)
    cookies_dict = {}
    cookiejar = None
    for k, m in cookie.items():
        cookies_dict[k] = m.value
        cookiejar = cookiejar_from_dict(cookies_dict, cookiejar=None, overwrite=True)
    return cookiejar


class XiaoAiGPT:

    def __init__(
            self,
            hardware=Config.hardware,
    ):
        self.history = []
        self.mi_token_home = os.path.join(Path.home(), "." + Config.account + ".mi.token")
        self.hardware = hardware
        self.cookie_string = ""
        self.last_timestamp = 0  # timestamp last call mi speaker
        self.session = None
        self.chatbot = None  # a little slow to init we move it after xiaomi init
        self.account = None
        self.user_id = ""
        self.device_id = ""
        self.service_token = ""
        self.cookie = ""
        self.use_command = Config.use_command
        self.tts_command = HARDWARE_COMMAND_DICT.get(hardware, "7-3")
        self.conversation_id = None
        self.parent_id = None
        self.xiaoai_account = None
        self.mina_service = None

    async def init_all_data(self, session):
        await self.login_xiaoai(session)
        await self._init_data_hardware()
        with open(self.mi_token_home) as f:
            user_data = json.loads(f.read())
        self.user_id = user_data.get("userId")
        self.service_token = user_data.get("micoapi")[1]
        self._init_cookie()
        await self._init_first_data_and_chatbot()

    async def login_xiaoai(self, session):
        self.session = session
        self.account = MiAccount(
            session,
            Config.account,
            Config.password,
            str(self.mi_token_home),
        )
        # Forced login to refresh token
        await self.account.login("micoapi")
        self.mina_service = MiNAService(self.account)

    async def _init_data_hardware(self):
        if self.cookie:
            # cookie does not need init
            return
        hardware_data = await self.mina_service.device_list()
        # print(hardware_data)
        for h in hardware_data:
            if h.get("hardware", "") == self.hardware:
                self.device_id = h.get("deviceID")
                break
        else:
            raise Exception(f"we have no hardware: {self.hardware} please check")

    def _init_cookie(self):
        if self.cookie:
            self.cookie = parse_cookie_string(self.cookie)
        else:
            self.cookie_string = Config.cookie_template.format(
                device_id=self.device_id,
                service_token=self.service_token,
                user_id=self.user_id,
            )
            self.cookie = parse_cookie_string(self.cookie_string)

    async def _init_first_data_and_chatbot(self):
        data = await self.get_latest_ask_from_xiaoai()
        self.last_timestamp, self.last_record = self.get_last_timestamp_and_record(data)
        self.chatbot = SlackClient(token=Config.slack_claude_user_token)

    async def get_latest_ask_from_xiaoai(self):
        r = await self.session.get(
            Config.last_ask_api.format(
                hardware=self.hardware, timestamp=str(int(time.time() * 1000))
            ),
            cookies=parse_cookie_string(self.cookie),
        )
        return await r.json()

    def get_last_timestamp_and_record(self, data):
        if d := data.get("data"):
            records = json.loads(d).get("records")
            if not records:
                return 0, None
            last_record = records[0]
            timestamp = last_record.get("time")
            return timestamp, last_record

    async def do_tts(self, value):
        if not self.use_command:
            try:
                await self.mina_service.text_to_speech(self.device_id, value)
            except:
                # do nothing is ok
                pass
        else:
            subprocess.check_output(["micli", self.tts_command, value])

    async def get_if_xiaoai_is_playing(self):
        playing_info = await self.mina_service.player_get_status(self.device_id)
        # WTF xiaomi api
        is_playing = (
                json.loads(playing_info.get("data", {}).get("info", "{}")).get("status", -1)
                == 1
        )
        return is_playing

    async def stop_if_xiaoai_is_playing(self):
        is_playing = await self.get_if_xiaoai_is_playing()
        if is_playing:
            # stop it
            await self.mina_service.player_pause(self.device_id)

    async def check_new_query(self, session):
        try:
            r = await self.get_latest_ask_from_xiaoai()
        except Exception:
            # we try to init all again
            await self.init_all_data(session)
            r = await self.get_latest_ask_from_xiaoai()
        new_timestamp, last_record = self.get_last_timestamp_and_record(r)
        if new_timestamp > self.last_timestamp:
            return new_timestamp, last_record.get("query", "")
        return False, None

    async def run_forever(self):
        global SWITCH
        print("正在运行 XiaoAiGPT, 请用\"开启/关闭高级对话模式\"控制对话模式。")
        async with ClientSession() as session:
            await self.init_all_data(session)
            while True:
                try:
                    r = await self.get_latest_ask_from_xiaoai()
                except Exception:
                    # we try to init all again
                    await self.init_all_data(session)
                    r = await self.get_latest_ask_from_xiaoai()
                new_timestamp, last_record = self.get_last_timestamp_and_record(r)
                if new_timestamp > self.last_timestamp:
                    self.last_timestamp = new_timestamp
                    query = last_record.get("query", "")
                    if query.startswith('停止'):  # 停止操作
                        await self.stop_if_xiaoai_is_playing()
                        continue
                    if query.startswith('开启高级对话模式'):
                        SWITCH = True
                        await self.stop_if_xiaoai_is_playing()
                        # await self.do_tts("高级对话模式已开启")
                        print("\033[1;32m高级对话模式已开启\033[0m")
                        continue
                    if query.startswith('关闭高级对话模式'):
                        SWITCH = False
                        await self.stop_if_xiaoai_is_playing()
                        # await self.do_tts("高级对话模式已关闭")
                        print("\033[1;32m高级对话模式已关闭\033[0m")
                        continue
                    if SWITCH:
                        await self.stop_if_xiaoai_is_playing()
                        await self.do_tts("中断小爱转GPT回答")
                        query = f"{query}，{Config.prompt}"
                        print(query)
                        try:
                            print(
                                "以下是小爱的回答: ",
                                last_record.get("answers")[0]
                                .get("tts", {})
                                .get("text").strip(),
                            )
                        except:
                            print("小爱没回")
                        print("以下是GPT的回答:  ", end="")

                        await self.chatbot.open_channel()
                        await self.chatbot.chat(query)

                        async for final, resp in self.chatbot.get_reply():
                            if final:
                                await self.do_tts(resp)
                                print(resp)
                                break


if __name__ == "__main__":
    xiaoai = XiaoAiGPT()
    asyncio.run(xiaoai.run_forever())
