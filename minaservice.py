import json
from miaccount import MiAccount, get_random

import logging

_LOGGER = logging.getLogger(__package__)


class MiNAService:
    def __init__(self, account: MiAccount):
        self.account = account

    async def mina_request(self, uri, data=None):
        request_id = "app_ios_" + get_random(30)
        if data is not None:
            data["requestId"] = request_id
        else:
            uri += "&requestId=" + request_id
        headers = {
            "User-Agent": "MiHome/6.0.103 (com.xiaomi.mihome; build:6.0.103.1; iOS 14.4.0) Alamofire/6.0.103 MICO/iOSApp/appStore/6.0.103"
        }
        return await self.account.mi_request(
            "micoapi", "https://api2.mina.mi.com" + uri, data, headers
        )

    async def device_list(self, master=0):
        result = await self.mina_request("/admin/v2/device_list?master=" + str(master))
        return result.get("data") if result else None

    async def ubus_request(self, device_id, method, path, message):
        message = json.dumps(message)
        result = await self.mina_request(
            "/remote/ubus",
            {"deviceId": device_id, "message": message, "method": method, "path": path},
        )
        return result

    async def text_to_speech(self, device_id, text):
        return await self.ubus_request(
            device_id, "text_to_speech", "mibrain", {"text": text}
        )

    async def player_set_volume(self, device_id, volume):
        return await self.ubus_request(
            device_id,
            "player_set_volume",
            "mediaplayer",
            {"volume": volume, "media": "app_ios"},
        )

    async def player_pause(self, device_id):
        return await self.ubus_request(
            device_id,
            "player_play_operation",
            "mediaplayer",
            {"action": "pause", "media": "app_ios"},
        )

    async def player_play(self, device_id):
        return await self.ubus_request(
            device_id,
            "player_play_operation",
            "mediaplayer",
            {"action": "play", "media": "app_ios"},
        )

    async def player_get_status(self, device_id):
        return await self.ubus_request(
            device_id,
            "player_get_play_status",
            "mediaplayer",
            {"media": "app_ios"},
        )

    async def play_by_url(self, device_id, url):
        return await self.ubus_request(
            device_id,
            "player_play_url",
            "mediaplayer",
            {"url": url, "type": 1, "media": "app_ios"},
        )

    async def send_message(self, devices, devno, message, volume=None):  # -1/0/1...
        result = False
        for i in range(0, len(devices)):
            if (
                    devno == -1
                    or devno != i + 1
                    or devices[i]["capabilities"].get("yunduantts")
            ):
                _LOGGER.debug(
                    "Send to devno=%d index=%d: %s", devno, i, message or volume
                )
                device_id = devices[i]["deviceID"]
                result = (
                    True
                    if volume is None
                    else await self.player_set_volume(device_id, volume)
                )
                if result and message:
                    result = await self.text_to_speech(device_id, message)
                if not result:
                    _LOGGER.error("Send failed: %s", message or volume)
                if devno != -1 or not result:
                    break
        return result
